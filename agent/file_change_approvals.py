"""Staged file-change approvals.

Folder policies may require managerial approval for writes by declaring
``write_approval_roles`` / ``write_approval_users`` (see
``agent.governance.file_write_approval_requirement``). When a write to such a
path is requested by an actor who cannot approve it themselves, the file tools
stage the FINAL proposed content here instead of applying it. The staged
change mutates the filesystem only after an authorized human approves it via
the dashboard API or a gateway approval card.

The store mirrors ``agent.enterprise_knowledge`` approvals: a JSON list under
HERMES_HOME with audit events on request and decision. Unlike the synchronous
dangerous-command prompt in ``tools.approval``, staged changes are durable —
they never expire, and the requesting agent finishes its turn immediately.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from hermes_constants import get_hermes_home

_APPROVALS_FILE = "file_changes/approvals.json"
_MAX_STORED_DIFF_CHARS = 20000

_store_lock = threading.Lock()

# Optional callback fired after a change is staged, so the gateway can post an
# approval card to the origin channel. Registered once at gateway startup via
# set_file_approval_notifier; staging never depends on it.
_notifier: Optional[Callable[[dict[str, Any]], None]] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def approvals_path() -> Path:
    return get_hermes_home() / _APPROVALS_FILE


def set_file_approval_notifier(cb: Optional[Callable[[dict[str, Any]], None]]) -> None:
    """Register (or clear) the gateway notification callback."""

    global _notifier
    _notifier = cb


def _fire_notifier(request: dict[str, Any]) -> None:
    cb = _notifier
    if cb is None:
        return
    try:
        cb(dict(request))
    except Exception:
        # Notification is best-effort; the staged request is already durable
        # and visible in the dashboard regardless.
        pass


def _read_approvals() -> list[dict[str, Any]]:
    path = approvals_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write_approvals(items: list[dict[str, Any]]) -> None:
    from tools.skill_manager_tool import _atomic_write_text

    _atomic_write_text(approvals_path(), json.dumps(items, indent=2, sort_keys=True))


def _actor_payload(actor: Optional[Any] = None) -> dict[str, Any]:
    try:
        from agent.governance import actor_display, current_actor

        who = current_actor() if actor is None else actor
        return {
            "id": actor_display(who),
            "platform": getattr(who, "platform", None),
            "user_id": getattr(who, "user_id", None),
            "user_name": getattr(who, "user_name", None),
        }
    except Exception:
        return {"id": "unknown"}


def _origin_payload() -> dict[str, Any]:
    """Capture where the request came from, for notification routing."""

    try:
        from gateway.session_context import get_session_env

        origin = {
            "platform": get_session_env("HERMES_SESSION_PLATFORM", ""),
            "chat_id": get_session_env("HERMES_SESSION_CHAT_ID", ""),
            "chat_name": get_session_env("HERMES_SESSION_CHAT_NAME", ""),
            "thread_id": get_session_env("HERMES_SESSION_THREAD_ID", ""),
            "session_key": get_session_env("HERMES_SESSION_KEY", ""),
        }
        return {k: v for k, v in origin.items() if v}
    except Exception:
        return {}


def _resolve(path: str) -> Path:
    return Path(str(path)).expanduser().resolve(strict=False)


def _hash_file(path: Path) -> Optional[str]:
    """SHA-256 of the file's current bytes, or None when it doesn't exist."""

    try:
        if not path.exists() or not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read_file_text(path: Path) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _unified_diff(before: str, after: str, path: str) -> str:
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    if len(diff) > _MAX_STORED_DIFF_CHARS:
        return diff[:_MAX_STORED_DIFF_CHARS] + "\n[diff truncated for storage]"
    return diff


def _write_denied_reason(path: Path) -> Optional[str]:
    """Mirror the protected system/credential file denylist from file_ops.

    The staged apply writes directly (not through ShellFileOperations), so the
    same floor must be enforced here — both at staging (fast feedback) and at
    approval (defense in depth). Uses the STATIC denylist only: governance
    folder policies are checked against the requester (at staging by the file
    tools, at apply by ``_apply_request``), not the ambient actor.
    """

    try:
        from agent.file_safety import is_write_denied_static

        if is_write_denied_static(str(path)):
            return f"Write denied: '{path}' is a protected system/credential file."
    except Exception:
        return None
    return None


def _requester_actor(request: dict[str, Any]):
    from agent.governance import Actor

    payload = request.get("requested_by") or {}
    return Actor(
        platform=str(payload.get("platform") or "local"),
        user_id=str(payload.get("user_id") or ""),
        user_name=str(payload.get("user_name") or ""),
    )


def _audit(event: str, *, actor: Any, request: dict[str, Any], outcome: str,
           reason: Optional[str] = None) -> None:
    try:
        from agent.audit_log import record_audit_event

        record_audit_event(
            event,
            actor=actor,
            action=f"file_change.{request.get('operation') or 'write'}",
            resource=str(request.get("path") or ""),
            outcome=outcome,
            reason=reason,
            metadata={"request_id": request.get("id")},
        )
    except Exception:
        pass


def stage_file_change(
    *,
    path: str,
    content: str,
    requirement: dict[str, Any],
    operation: str = "write",
    display_path: Optional[str] = None,
    note: Optional[str] = None,
    actor: Optional[Any] = None,
) -> dict[str, Any]:
    """Stage the final proposed *content* for *path* pending human approval.

    Returns a tool-result-shaped dict. ``pending_approval: True`` signals the
    caller (and the agent) that nothing was written yet.
    """

    resolved = _resolve(path)
    denied = _write_denied_reason(resolved)
    if denied:
        return {"success": False, "error": denied}

    before = _read_file_text(resolved)
    request: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "status": "pending",
        "created_at": _now(),
        "requested_by": _actor_payload(actor),
        "origin": _origin_payload(),
        "path": str(resolved),
        "display_path": str(display_path or path),
        "operation": str(operation or "write"),
        "content": content,
        "base_hash": _hash_file(resolved),
        "base_exists": resolved.exists(),
        "diff": _unified_diff(before, content, str(display_path or path)),
        "requirement": {
            "roles": list(requirement.get("roles") or []),
            "users": list(requirement.get("users") or []),
            "policy_path": requirement.get("policy_path"),
        },
        "note": note,
    }

    with _store_lock:
        items = _read_approvals()
        items.append(request)
        _write_approvals(items)

    _audit(
        "file_change.approval_requested",
        actor=actor,
        request=request,
        outcome="pending",
    )
    _fire_notifier(request)

    roles = request["requirement"]["roles"]
    users = request["requirement"]["users"]
    who_can = (
        f"roles {roles}" if roles else ""
    ) + ("" if not users else (" or " if roles else "") + f"users {users}")
    return {
        "success": True,
        "pending_approval": True,
        "approval_id": request["id"],
        "path": str(resolved),
        "message": (
            f"Change to {request['display_path']} staged for human approval "
            f"(required approvers: {who_can or 'per governance'}). Nothing was "
            "written yet. The change applies automatically once an approver "
            "accepts it in the dashboard File Approvals panel or via the "
            "approval card in chat."
        ),
    }


def list_file_change_approvals(status: str = "pending") -> list[dict[str, Any]]:
    items = _read_approvals()
    if status and status != "all":
        items = [item for item in items if item.get("status") == status]
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


def get_file_change_approval(approval_id: str) -> Optional[dict[str, Any]]:
    for item in _read_approvals():
        if item.get("id") == approval_id:
            return item
    return None


def _atomic_write_file(path: Path, content: str) -> None:
    from utils import atomic_replace

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.tmp.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        atomic_replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _apply_request(request: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(str(request.get("path") or ""))
    denied = _write_denied_reason(path)
    if denied:
        return {"success": False, "error": denied}
    # Re-check the REQUESTER's write grant: if their access was revoked after
    # staging, approval must not resurrect it. Fails closed on evaluation
    # errors — this apply bypasses the file tools' own governance gate.
    try:
        from agent.governance import check_file_access

        allowed, reason = check_file_access(
            str(path), "write", actor=_requester_actor(request)
        )
    except Exception as exc:
        allowed, reason = False, f"governance check failed: {exc}"
    if not allowed:
        return {
            "success": False,
            "error": (
                "Cannot apply staged change: the requester no longer has "
                f"write access to this path. {reason}"
            ),
        }
    if str(request.get("operation") or "write") != "write":
        return {
            "success": False,
            "error": f"Unsupported staged operation {request.get('operation')!r}",
        }
    try:
        _atomic_write_file(path, str(request.get("content") or ""))
    except Exception as exc:
        return {"success": False, "error": f"Failed to apply staged change: {exc}"}
    return {"success": True, "path": str(path), "bytes": len(str(request.get("content") or "").encode("utf-8"))}


def decide_from_platform_click(
    approval_id: str,
    *,
    approve: bool,
    platform: str,
    user_id: str,
    user_name: str = "",
) -> dict[str, Any]:
    """Decide a staged change from a chat approval-card button click.

    Builds the clicker's governance identity from their platform ids;
    ``decide_file_change_approval`` enforces the approver requirement, so an
    unauthorized click comes back as the 403 error message for display.
    """

    from agent.governance import Actor

    actor = Actor(
        platform=str(platform or "").strip().lower() or "local",
        user_id=str(user_id or ""),
        user_name=str(user_name or ""),
    )
    return decide_file_change_approval(approval_id, approve=approve, actor=actor)


def decide_file_change_approval(
    approval_id: str,
    *,
    approve: bool,
    note: Optional[str] = None,
    actor: Optional[Any] = None,
) -> dict[str, Any]:
    """Approve or deny a staged change; approval applies it atomically.

    A base-content check protects the approver: if the file changed on disk
    after the request was staged, the diff they reviewed no longer describes
    reality — the request is marked ``stale`` instead of applied, and the
    requester must re-stage against the current content.
    """

    from agent.governance import can_approve_file_change

    with _store_lock:
        items = _read_approvals()
        for item in items:
            if item.get("id") != approval_id:
                continue
            if item.get("status") != "pending":
                return {"success": False, "error": "Approval is not pending."}
            allowed, reason = can_approve_file_change(
                item.get("requirement") or {}, actor=actor
            )
            if not allowed:
                return {"success": False, "error": reason, "status_code": 403}

            apply_result: dict[str, Any] = {"success": True}
            if approve:
                current_hash = _hash_file(_resolve(str(item.get("path") or "")))
                if current_hash != item.get("base_hash"):
                    item["status"] = "stale"
                    item["decided_at"] = _now()
                    item["decided_by"] = _actor_payload(actor)
                    item["decision_note"] = note
                    _write_approvals(items)
                    _audit(
                        "file_change.approval_decided",
                        actor=actor,
                        request=item,
                        outcome="stale",
                        reason="file changed on disk after staging",
                    )
                    return {
                        "success": False,
                        "error": (
                            "The file changed on disk after this request was "
                            "staged, so the reviewed diff is no longer accurate. "
                            "The request was marked stale — ask the requester "
                            "to stage it again."
                        ),
                        "status_code": 409,
                        "approval": item,
                    }
                apply_result = _apply_request(item)
                if not apply_result.get("success"):
                    return apply_result

            item["status"] = "approved" if approve else "denied"
            item["decided_at"] = _now()
            item["decided_by"] = _actor_payload(actor)
            item["decision_note"] = note
            item["apply_result"] = apply_result
            _write_approvals(items)

            _audit(
                "file_change.approval_decided",
                actor=actor,
                request=item,
                outcome=item["status"],
                reason=note,
            )
            return {"success": True, "approval": item}
    return {"success": False, "error": "Approval not found.", "status_code": 404}

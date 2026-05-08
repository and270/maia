"""Short-lived dashboard login tokens issued from authenticated channels."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from hermes_constants import get_hermes_home

TOKEN_PREFIX = "cdt_"
REQUEST_PREFIX = "dar_"


def _store_path() -> Path:
    return get_hermes_home() / "dashboard" / "channel_login_tokens.json"


def _hash_token(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _read_store() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"tokens": [], "access_requests": [], "revoked_users": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"tokens": [], "access_requests": [], "revoked_users": []}
    if not isinstance(data, dict):
        return {"tokens": [], "access_requests": [], "revoked_users": []}
    tokens = data.get("tokens")
    if not isinstance(tokens, list):
        data["tokens"] = []
    requests = data.get("access_requests")
    if not isinstance(requests, list):
        data["access_requests"] = []
    revoked = data.get("revoked_users")
    if not isinstance(revoked, list):
        data["revoked_users"] = []
    return data


def _write_store(data: dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _actor_payload(actor: Any) -> dict[str, str]:
    return {
        "platform": str(getattr(actor, "platform", "") or "").strip() or "local",
        "user_id": str(getattr(actor, "user_id", "") or "").strip(),
        "user_name": str(getattr(actor, "user_name", "") or "").strip(),
    }


def actor_from_payload(payload: dict[str, Any]) -> Any:
    from agent.governance import Actor

    return Actor(
        platform=str(payload.get("platform") or "local"),
        user_id=str(payload.get("user_id") or ""),
        user_name=str(payload.get("user_name") or ""),
    )


def actor_key_from_payload(payload: dict[str, Any]) -> str:
    platform = str(payload.get("platform") or "local").strip().lower() or "local"
    user_id = str(payload.get("user_id") or "").strip()
    user_name = str(payload.get("user_name") or "").strip()
    if user_id:
        return f"{platform}:{user_id}"
    if user_name:
        return f"{platform}:{user_name}"
    return platform


def actor_key(actor: Any) -> str:
    keys = list(getattr(actor, "keys", ()) or [])
    if keys:
        return str(keys[0])
    return actor_key_from_payload(_actor_payload(actor))


def actor_keys(actor: Any) -> set[str]:
    keys = {str(key) for key in getattr(actor, "keys", ()) or [] if str(key)}
    key = actor_key(actor)
    if key:
        keys.add(key)
    return keys


def _reviewer_payload(reviewer: Any) -> dict[str, str]:
    if reviewer is None:
        return {}
    if isinstance(reviewer, dict):
        return {
            "platform": str(reviewer.get("platform") or "").strip(),
            "user_id": str(reviewer.get("user_id") or "").strip(),
            "user_name": str(reviewer.get("user_name") or "").strip(),
        }
    return _actor_payload(reviewer)


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _request_matches_actor(request: dict[str, Any], keys: Iterable[str]) -> bool:
    key_set = {str(key) for key in keys if str(key)}
    if not key_set:
        return False
    request_key = str(request.get("actor_key") or "").strip()
    if request_key in key_set:
        return True
    actor = request.get("actor")
    if isinstance(actor, dict) and actor_key_from_payload(actor) in key_set:
        return True
    return False


def _revocation_matches_actor(revocation: Any, keys: Iterable[str]) -> bool:
    key_set = {str(key) for key in keys if str(key)}
    if not key_set:
        return False
    if isinstance(revocation, str):
        return revocation in key_set
    if isinstance(revocation, dict):
        return str(revocation.get("actor_key") or "").strip() in key_set
    return False


def list_dashboard_access_requests(status: Optional[str] = None) -> list[dict[str, Any]]:
    """Return dashboard access requests, newest first."""

    wanted = str(status or "").strip().lower()
    requests = [
        dict(item)
        for item in _read_store().get("access_requests", [])
        if isinstance(item, dict)
    ]
    if wanted:
        requests = [
            item
            for item in requests
            if str(item.get("status") or "").strip().lower() == wanted
        ]
    requests.sort(key=lambda item: float(item.get("updated_at") or item.get("requested_at") or 0), reverse=True)
    return requests


def list_dashboard_access_revocations() -> list[dict[str, Any]]:
    """Return actors that are blocked from dashboard token login."""

    result: list[dict[str, Any]] = []
    for item in _read_store().get("revoked_users", []):
        if isinstance(item, str):
            result.append({"actor_key": item, "revoked_at": 0, "reason": ""})
        elif isinstance(item, dict):
            actor_key_value = str(item.get("actor_key") or "").strip()
            if actor_key_value:
                result.append(dict(item))
    result.sort(key=lambda item: float(item.get("revoked_at") or 0), reverse=True)
    return result


def get_dashboard_access_request(request_id: str) -> Optional[dict[str, Any]]:
    wanted = str(request_id or "").strip()
    if not wanted:
        return None
    for item in _read_store().get("access_requests", []):
        if isinstance(item, dict) and str(item.get("id") or "") == wanted:
            return dict(item)
    return None


def is_dashboard_actor_revoked(actor: Any) -> bool:
    keys = actor_keys(actor)
    for item in _read_store().get("revoked_users", []):
        if _revocation_matches_actor(item, keys):
            return True
    return False


def approved_dashboard_access_for_actor(actor: Any) -> Optional[dict[str, Any]]:
    """Return the latest approved dashboard access request for an actor."""

    if is_dashboard_actor_revoked(actor):
        return None
    keys = actor_keys(actor)
    for item in list_dashboard_access_requests():
        if str(item.get("status") or "").lower() == "approved" and _request_matches_actor(item, keys):
            return item
    return None


def request_dashboard_access(
    *,
    actor: Any,
    reason: str = "",
    now: Optional[float] = None,
) -> tuple[dict[str, Any], bool]:
    """Create or return a dashboard access request for a channel actor."""

    current = time.time() if now is None else now
    key = actor_key(actor)
    keys = actor_keys(actor)
    data = _read_store()
    requests = data.get("access_requests", [])

    for item in reversed(requests):
        if not isinstance(item, dict) or not _request_matches_actor(item, keys):
            continue
        status = str(item.get("status") or "").lower()
        if status in {"pending", "approved"}:
            return dict(item), False

    record = {
        "id": REQUEST_PREFIX + secrets.token_hex(8),
        "actor_key": key,
        "actor": _actor_payload(actor),
        "status": "pending",
        "reason": str(reason or "").strip(),
        "requested_at": current,
        "updated_at": current,
        "requested_via": "channel",
    }
    requests.append(record)
    data["access_requests"] = requests
    _write_store(data)
    return dict(record), True


def decide_dashboard_access_request(
    *,
    request_id: str,
    approve: bool,
    reviewer: Any = None,
    roles: Optional[list[str]] = None,
    teams: Optional[list[str]] = None,
    note: str = "",
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Approve or deny a pending dashboard access request."""

    wanted = str(request_id or "").strip()
    current = time.time() if now is None else now
    data = _read_store()
    requests = data.get("access_requests", [])
    reviewer_payload = _reviewer_payload(reviewer)
    reviewer_key = actor_key_from_payload(reviewer_payload) if reviewer_payload else ""

    for index, item in enumerate(requests):
        if not isinstance(item, dict) or str(item.get("id") or "") != wanted:
            continue
        next_item = dict(item)
        next_item["status"] = "approved" if approve else "denied"
        next_item["updated_at"] = current
        next_item["reviewed_at"] = current
        if reviewer_payload:
            next_item["reviewed_by"] = reviewer_payload
        if reviewer_key:
            next_item["reviewed_by_key"] = reviewer_key
        if note:
            next_item["decision_note"] = str(note)
        if approve:
            next_item["approved_roles"] = _coerce_list(roles)
            next_item["approved_teams"] = _coerce_list(teams)
            actor_key_value = str(next_item.get("actor_key") or "").strip()
            data["revoked_users"] = [
                revoked
                for revoked in data.get("revoked_users", [])
                if not _revocation_matches_actor(revoked, [actor_key_value])
            ]
        requests[index] = next_item
        data["access_requests"] = requests
        _write_store(data)
        return dict(next_item)
    raise KeyError(f"Dashboard access request not found: {wanted}")


def revoke_dashboard_access(
    *,
    actor_key_value: str,
    reviewer: Any = None,
    reason: str = "",
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Block a dashboard actor from future channel token login."""

    key = str(actor_key_value or "").strip()
    if not key:
        raise ValueError("actor_key is required")
    current = time.time() if now is None else now
    data = _read_store()
    reviewer_payload = _reviewer_payload(reviewer)
    reviewer_key = actor_key_from_payload(reviewer_payload) if reviewer_payload else ""

    revoked = [
        item
        for item in data.get("revoked_users", [])
        if not _revocation_matches_actor(item, [key])
    ]
    record = {
        "actor_key": key,
        "revoked_at": current,
        "reason": str(reason or "").strip(),
    }
    if reviewer_payload:
        record["revoked_by"] = reviewer_payload
    if reviewer_key:
        record["revoked_by_key"] = reviewer_key
    revoked.append(record)
    data["revoked_users"] = revoked

    for item in data.get("access_requests", []):
        if isinstance(item, dict) and _request_matches_actor(item, [key]):
            item["previous_status"] = str(item.get("status") or "").strip()
            item["status"] = "revoked"
            item["updated_at"] = current
            item["revoked_at"] = current
            if reason:
                item["revocation_reason"] = str(reason)

    tokens = []
    removed_tokens = 0
    for item in data.get("tokens", []):
        if not isinstance(item, dict):
            continue
        actor = item.get("actor")
        if isinstance(actor, dict) and actor_key_from_payload(actor) == key:
            removed_tokens += 1
            continue
        tokens.append(item)
    data["tokens"] = tokens
    _write_store(data)
    record["removed_tokens"] = removed_tokens
    return record


def restore_dashboard_access(
    *,
    actor_key_value: str,
    reviewer: Any = None,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Remove a dashboard access revocation."""

    key = str(actor_key_value or "").strip()
    if not key:
        raise ValueError("actor_key is required")
    current = time.time() if now is None else now
    data = _read_store()
    before = len(data.get("revoked_users", []))
    data["revoked_users"] = [
        item
        for item in data.get("revoked_users", [])
        if not _revocation_matches_actor(item, [key])
    ]
    reviewer_payload = _reviewer_payload(reviewer)
    reviewer_key = actor_key_from_payload(reviewer_payload) if reviewer_payload else ""
    for item in data.get("access_requests", []):
        if not isinstance(item, dict) or not _request_matches_actor(item, [key]):
            continue
        if str(item.get("status") or "").lower() != "revoked":
            continue
        previous_status = str(item.get("previous_status") or "").lower()
        if previous_status == "approved" or item.get("approved_roles"):
            item["status"] = "approved"
            item["updated_at"] = current
            item["restored_at"] = current
            if reviewer_payload:
                item["restored_by"] = reviewer_payload
            if reviewer_key:
                item["restored_by_key"] = reviewer_key
    _write_store(data)
    return {
        "actor_key": key,
        "restored_at": current,
        "restored": len(data.get("revoked_users", [])) != before,
        "restored_by": reviewer_payload,
    }


def prune_channel_dashboard_tokens(now: Optional[float] = None) -> int:
    """Remove expired channel-issued dashboard login tokens."""

    current = time.time() if now is None else now
    data = _read_store()
    original = data.get("tokens", [])
    kept = [
        token
        for token in original
        if isinstance(token, dict) and float(token.get("expires_at") or 0) > current
    ]
    if len(kept) != len(original):
        data["tokens"] = kept
        _write_store(data)
    return len(original) - len(kept)


def issue_channel_dashboard_token(
    *,
    actor: Any,
    roles: list[str],
    ttl_seconds: int,
    now: Optional[float] = None,
) -> str:
    """Create a one-time dashboard login token for a channel-authenticated actor."""

    current = time.time() if now is None else now
    ttl = max(60, int(ttl_seconds or 600))
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    data = _read_store()
    existing = [
        item
        for item in data.get("tokens", [])
        if isinstance(item, dict) and float(item.get("expires_at") or 0) > current
    ]
    existing.append(
        {
            "id": secrets.token_hex(8),
            "token_hash": _hash_token(token),
            "actor": _actor_payload(actor),
            "roles": list(roles or []),
            "issued_at": current,
            "expires_at": current + ttl,
            "source": "channel",
        }
    )
    data["tokens"] = existing
    _write_store(data)
    return token


def consume_channel_dashboard_token(raw_token: str, now: Optional[float] = None) -> Optional[dict[str, Any]]:
    """Consume and return a valid channel dashboard token record, if present."""

    token = str(raw_token or "").strip()
    if not token.startswith(TOKEN_PREFIX):
        return None

    current = time.time() if now is None else now
    wanted_hash = _hash_token(token)
    data = _read_store()
    kept: list[dict[str, Any]] = []
    consumed: Optional[dict[str, Any]] = None
    changed = False

    for item in data.get("tokens", []):
        if not isinstance(item, dict):
            changed = True
            continue
        expires_at = float(item.get("expires_at") or 0)
        if expires_at <= current:
            changed = True
            continue
        if item.get("token_hash") == wanted_hash and consumed is None:
            consumed = item
            changed = True
            continue
        kept.append(item)

    if changed:
        data["tokens"] = kept
        _write_store(data)
    return consumed

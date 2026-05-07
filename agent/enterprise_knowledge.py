"""Governed corporate/team/user knowledge layers.

Coorporate Hermes keeps the upstream user memory and user skill behavior, but
adds shared layers above it:

* corporate: approved tenant-wide facts and skills injected into every session
* team: approved facts and skills injected for actors assigned to that team
* user: private profile-scoped MEMORY.md/USER.md and user-created skills

Writes to corporate and team layers are proposal-first.  The proposal is stored
under HERMES_HOME and must be approved through the dashboard/API by an
authorized human before it mutates the shared files.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hermes_constants import get_hermes_home

_ENTRY_DELIMITER = "\n§\n"
_APPROVALS_FILE = "knowledge/approvals.json"
_SKILL_EXCLUDED_DIRS = frozenset((".git", ".github", ".hub", ".archive"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
    except Exception:
        cfg = {}
    return cfg if isinstance(cfg, dict) else {}


def _knowledge_config(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg = _load_config() if cfg is None else cfg
    raw = cfg.get("knowledge", {})
    return raw if isinstance(raw, dict) else {}


def knowledge_enabled(cfg: Optional[dict[str, Any]] = None) -> bool:
    return bool(_knowledge_config(cfg).get("enabled", True))


def _safe_segment(value: str) -> str:
    text = str(value or "").strip().lower()
    cleaned = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            cleaned.append(ch)
        else:
            cleaned.append("-")
    result = "".join(cleaned).strip(".-_")
    return result or "default"


def corporate_memory_path() -> Path:
    return get_hermes_home() / "corporate" / "memories" / "MEMORY.md"


def corporate_skills_dir() -> Path:
    return get_hermes_home() / "corporate" / "skills"


def team_memory_path(team: str) -> Path:
    return get_hermes_home() / "teams" / _safe_segment(team) / "memories" / "MEMORY.md"


def team_skills_dir(team: str) -> Path:
    return get_hermes_home() / "teams" / _safe_segment(team) / "skills"


def approvals_path() -> Path:
    return get_hermes_home() / _APPROVALS_FILE


def actor_team_names(actor: Optional[Any] = None) -> list[str]:
    try:
        from agent.governance import actor_teams

        return actor_teams(actor)
    except Exception:
        return []


def enterprise_skill_dirs(actor: Optional[Any] = None) -> list[Path]:
    """Return corporate/team skill roots that should be visible to *actor*."""

    if not knowledge_enabled():
        return []
    dirs: list[Path] = []
    corporate = corporate_skills_dir()
    if corporate.exists():
        dirs.append(corporate)
    for team in actor_team_names(actor):
        path = team_skills_dir(team)
        if path.exists() and path not in dirs:
            dirs.append(path)
    return dirs


def _read_text(path: Path, max_chars: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "\n[truncated by knowledge.max_memory_chars]"
    return text


def _iter_skill_md(root: Path) -> list[Path]:
    if not root.exists():
        return []
    result: list[Path] = []
    for skill_md in root.rglob("SKILL.md"):
        if any(part in _SKILL_EXCLUDED_DIRS for part in skill_md.parts):
            continue
        result.append(skill_md)
    return sorted(result)


def _render_skills_block(label: str, root: Path, max_chars: int) -> str:
    chunks: list[str] = []
    used = 0
    for skill_md in _iter_skill_md(root):
        try:
            content = skill_md.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if not content:
            continue
        rel = str(skill_md.parent.relative_to(root))
        header = f"\n--- {label} skill: {rel} ---\n"
        piece = header + content
        if max_chars > 0 and used + len(piece) > max_chars:
            remaining = max_chars - used
            if remaining > len(header) + 80:
                chunks.append(piece[:remaining] + "\n[truncated by knowledge.max_skill_chars]")
            break
        chunks.append(piece)
        used += len(piece)
    return "\n".join(chunks).strip()


def build_enterprise_knowledge_prompt(actor: Optional[Any] = None) -> str:
    """Build the approved shared knowledge block for the system prompt."""

    cfg = _load_config()
    if not knowledge_enabled(cfg):
        return ""

    knowledge = _knowledge_config(cfg)
    max_mem = int(knowledge.get("max_memory_chars") or 12000)
    max_skills = int(knowledge.get("max_skill_chars") or 24000)
    teams = actor_team_names(actor)

    blocks: list[str] = []
    corporate_memory = _read_text(corporate_memory_path(), max_mem)
    if corporate_memory:
        blocks.append(
            "CORPORATE MEMORY (approved tenant-wide facts; applies to every conversation)\n"
            + corporate_memory
        )

    corporate_skills = _render_skills_block("corporate", corporate_skills_dir(), max_skills)
    if corporate_skills:
        blocks.append(
            "CORPORATE SKILLS (approved tenant-wide procedures; follow when relevant)\n"
            + corporate_skills
        )

    per_team_skill_cap = max(1000, max_skills // max(1, len(teams))) if teams else max_skills
    per_team_mem_cap = max(1000, max_mem // max(1, len(teams))) if teams else max_mem
    for team in teams:
        memory = _read_text(team_memory_path(team), per_team_mem_cap)
        if memory:
            blocks.append(f"TEAM MEMORY: {team} (approved shared facts)\n{memory}")
        skills = _render_skills_block(f"team:{team}", team_skills_dir(team), per_team_skill_cap)
        if skills:
            blocks.append(f"TEAM SKILLS: {team} (approved shared procedures)\n{skills}")

    if not blocks:
        return ""

    separator = "═" * 46
    return (
        f"{separator}\n"
        "COORPORATE HERMES SHARED KNOWLEDGE\n"
        f"{separator}\n"
        "Corporate and team memory/skills below are approved shared knowledge. "
        "They outrank user-level memory/skills when there is a conflict. "
        "Do not edit corporate or team knowledge directly; propose changes for "
        "human approval through the knowledge approval workflow.\n\n"
        + "\n\n".join(blocks)
    )


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

    path = approvals_path()
    _atomic_write_text(path, json.dumps(items, indent=2, sort_keys=True))


def list_knowledge_approvals(status: str = "pending") -> list[dict[str, Any]]:
    items = _read_approvals()
    if status and status != "all":
        items = [item for item in items if item.get("status") == status]
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


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


def _scope_approval_roles(scope: str) -> list[str]:
    cfg = _knowledge_config()
    if scope == "corporate":
        section = cfg.get("corporate", {}) if isinstance(cfg.get("corporate"), dict) else {}
        roles = section.get("approver_roles")
        return list(roles) if isinstance(roles, list) else ["admin"]
    section = cfg.get("team", {}) if isinstance(cfg.get("team"), dict) else {}
    roles = section.get("approver_roles")
    return list(roles) if isinstance(roles, list) else ["manager", "admin"]


def can_approve_knowledge(scope: str, actor: Optional[Any] = None) -> tuple[bool, str]:
    try:
        from agent.governance import actor_has_any_role, actor_display

        roles = _scope_approval_roles(scope)
        if actor_has_any_role(roles, actor=actor):
            return True, ""
        return False, f"{actor_display(actor)} cannot approve {scope} knowledge. Required roles: {roles}."
    except Exception as exc:
        return False, str(exc)


def propose_knowledge_change(
    *,
    kind: str,
    scope: str,
    action: str,
    target: str = "memory",
    content: Optional[str] = None,
    old_text: Optional[str] = None,
    team: Optional[str] = None,
    name: Optional[str] = None,
    category: Optional[str] = None,
    file_path: Optional[str] = None,
    file_content: Optional[str] = None,
    replace_all: bool = False,
    note: Optional[str] = None,
    actor: Optional[Any] = None,
) -> dict[str, Any]:
    """Create a pending shared-knowledge change request."""

    scope = str(scope or "user").strip().lower()
    kind = str(kind or "").strip().lower()
    if scope not in {"corporate", "team"}:
        return {"success": False, "error": "Approvals are only required for corporate or team scope."}
    if scope == "team" and not str(team or "").strip():
        return {"success": False, "error": "team is required for team-scoped knowledge changes."}
    if kind not in {"memory", "skill"}:
        return {"success": False, "error": "kind must be memory or skill."}

    request = {
        "id": uuid.uuid4().hex,
        "status": "pending",
        "created_at": _now(),
        "requested_by": _actor_payload(actor),
        "scope": scope,
        "team": _safe_segment(team) if scope == "team" else None,
        "kind": kind,
        "action": action,
        "target": target,
        "content": content,
        "old_text": old_text,
        "name": name,
        "category": category,
        "file_path": file_path,
        "file_content": file_content,
        "replace_all": bool(replace_all),
        "note": note,
    }
    items = _read_approvals()
    items.append(request)
    _write_approvals(items)

    try:
        from agent.audit_log import record_audit_event

        record_audit_event(
            "knowledge.approval_requested",
            actor=actor,
            action=f"knowledge.{kind}.{action}",
            resource=f"{scope}:{request.get('team') or 'all'}",
            outcome="pending",
            metadata={"request_id": request["id"], "kind": kind, "scope": scope},
        )
    except Exception:
        pass

    return {
        "success": True,
        "pending_approval": True,
        "approval_id": request["id"],
        "message": (
            f"{scope.title()} {kind} change staged for human approval. "
            "Open the Knowledge panel to approve or deny it."
        ),
    }


def _target_memory_path(request: dict[str, Any]) -> Path:
    if request.get("scope") == "corporate":
        return corporate_memory_path()
    return team_memory_path(str(request.get("team") or "default"))


def _read_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [item.strip() for item in raw.split(_ENTRY_DELIMITER) if item.strip()]


def _write_entries(path: Path, entries: list[str]) -> None:
    from utils import atomic_replace
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.tmp.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_ENTRY_DELIMITER.join(entries))
        atomic_replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _apply_memory_request(request: dict[str, Any]) -> dict[str, Any]:
    from tools.memory_tool import _scan_memory_content

    path = _target_memory_path(request)
    entries = _read_entries(path)
    action = request.get("action")
    content = str(request.get("content") or "").strip()
    old_text = str(request.get("old_text") or "").strip()

    if action == "add":
        if not content:
            return {"success": False, "error": "content is required"}
        scan_error = _scan_memory_content(content)
        if scan_error:
            return {"success": False, "error": scan_error}
        if content not in entries:
            entries.append(content)
    elif action == "replace":
        if not old_text or not content:
            return {"success": False, "error": "old_text and content are required"}
        scan_error = _scan_memory_content(content)
        if scan_error:
            return {"success": False, "error": scan_error}
        matches = [i for i, entry in enumerate(entries) if old_text in entry]
        if len(matches) != 1:
            return {"success": False, "error": f"Expected one match for {old_text!r}; found {len(matches)}"}
        entries[matches[0]] = content
    elif action == "remove":
        if not old_text:
            return {"success": False, "error": "old_text is required"}
        matches = [i for i, entry in enumerate(entries) if old_text in entry]
        if len(matches) != 1:
            return {"success": False, "error": f"Expected one match for {old_text!r}; found {len(matches)}"}
        entries.pop(matches[0])
    else:
        return {"success": False, "error": f"Unsupported memory action {action!r}"}

    _write_entries(path, entries)
    return {"success": True, "path": str(path), "entry_count": len(entries)}


def _skill_root(request: dict[str, Any]) -> Path:
    if request.get("scope") == "corporate":
        return corporate_skills_dir()
    return team_skills_dir(str(request.get("team") or "default"))


def _find_skill_dir(root: Path, name: str) -> Optional[Path]:
    for skill_md in _iter_skill_md(root):
        if skill_md.parent.name == name:
            return skill_md.parent
    return None


def _skill_dir_for(root: Path, name: str, category: Optional[str]) -> Path:
    return root / _safe_segment(category) / name if category else root / name


def _apply_skill_request(request: dict[str, Any]) -> dict[str, Any]:
    from tools.path_security import has_traversal_component, validate_within_dir
    from tools.skill_manager_tool import (
        _validate_category,
        _validate_content_size,
        _validate_file_path,
        _validate_frontmatter,
        _validate_name,
        _atomic_write_text,
        _security_scan_skill,
    )

    root = _skill_root(request)
    action = str(request.get("action") or "")
    name = str(request.get("name") or "").strip()
    category = request.get("category")
    content = request.get("content")
    file_path = request.get("file_path")
    file_content = request.get("file_content")

    if not name:
        return {"success": False, "error": "name is required"}
    error = _validate_name(name)
    if error:
        return {"success": False, "error": error}
    error = _validate_category(category)
    if error:
        return {"success": False, "error": error}

    if action == "create":
        if not content:
            return {"success": False, "error": "content is required"}
        for check in (_validate_frontmatter(content), _validate_content_size(content)):
            if check:
                return {"success": False, "error": check}
        target = _skill_dir_for(root, name, category)
        if target.exists():
            return {"success": False, "error": f"Skill {name!r} already exists"}
        _atomic_write_text(target / "SKILL.md", content)
        scan_error = _security_scan_skill(target)
        if scan_error:
            import shutil

            shutil.rmtree(target, ignore_errors=True)
            return {"success": False, "error": scan_error}
        return {"success": True, "path": str(target)}

    skill_dir = _find_skill_dir(root, name)
    if not skill_dir:
        return {"success": False, "error": f"Skill {name!r} not found in {root}"}

    if action == "edit":
        if not content:
            return {"success": False, "error": "content is required"}
        for check in (_validate_frontmatter(content), _validate_content_size(content)):
            if check:
                return {"success": False, "error": check}
        original = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        _atomic_write_text(skill_dir / "SKILL.md", content)
        scan_error = _security_scan_skill(skill_dir)
        if scan_error:
            _atomic_write_text(skill_dir / "SKILL.md", original)
            return {"success": False, "error": scan_error}
    elif action == "patch":
        old = str(request.get("old_text") or "")
        new = "" if request.get("content") is None else str(request.get("content"))
        target_file = skill_dir / (file_path or "SKILL.md")
        if file_path:
            err = _validate_file_path(file_path)
            if err:
                return {"success": False, "error": err}
        err = validate_within_dir(target_file, skill_dir)
        if err:
            return {"success": False, "error": err}
        if not target_file.exists():
            return {"success": False, "error": f"File not found: {target_file.relative_to(skill_dir)}"}
        text = target_file.read_text(encoding="utf-8")
        from tools.fuzzy_match import fuzzy_find_and_replace

        new_text, _match_count, _strategy, match_error = fuzzy_find_and_replace(
            text,
            old,
            new,
            bool(request.get("replace_all")),
        )
        if match_error:
            return {"success": False, "error": match_error}
        label = "SKILL.md" if not file_path else str(file_path)
        for check in (
            _validate_content_size(new_text, label=label),
            _validate_frontmatter(new_text) if not file_path else None,
        ):
            if check:
                return {"success": False, "error": check}
        _atomic_write_text(target_file, new_text)
        scan_error = _security_scan_skill(skill_dir)
        if scan_error:
            _atomic_write_text(target_file, text)
            return {"success": False, "error": scan_error}
    elif action == "delete":
        import shutil

        shutil.rmtree(skill_dir)
    elif action == "write_file":
        if not file_path or file_content is None:
            return {"success": False, "error": "file_path and file_content are required"}
        err = _validate_file_path(file_path)
        if err:
            return {"success": False, "error": err}
        target_file = skill_dir / file_path
        err = validate_within_dir(target_file, skill_dir)
        if err or has_traversal_component(file_path):
            return {"success": False, "error": err or "Path traversal is not allowed"}
        original = target_file.read_text(encoding="utf-8") if target_file.exists() else None
        _atomic_write_text(target_file, str(file_content))
        scan_error = _security_scan_skill(skill_dir)
        if scan_error:
            if original is None:
                target_file.unlink(missing_ok=True)
            else:
                _atomic_write_text(target_file, original)
            return {"success": False, "error": scan_error}
    elif action == "remove_file":
        if not file_path:
            return {"success": False, "error": "file_path is required"}
        err = _validate_file_path(file_path)
        if err:
            return {"success": False, "error": err}
        target_file = skill_dir / file_path
        err = validate_within_dir(target_file, skill_dir)
        if err:
            return {"success": False, "error": err}
        if target_file.exists():
            target_file.unlink()
    else:
        return {"success": False, "error": f"Unsupported skill action {action!r}"}

    return {"success": True, "path": str(skill_dir)}


def decide_knowledge_approval(
    approval_id: str,
    *,
    approve: bool,
    note: Optional[str] = None,
    actor: Optional[Any] = None,
) -> dict[str, Any]:
    items = _read_approvals()
    for item in items:
        if item.get("id") != approval_id:
            continue
        if item.get("status") != "pending":
            return {"success": False, "error": "Approval is not pending."}
        allowed, reason = can_approve_knowledge(str(item.get("scope") or ""), actor=actor)
        if not allowed:
            return {"success": False, "error": reason, "status_code": 403}

        apply_result = {"success": True}
        if approve:
            apply_result = (
                _apply_memory_request(item)
                if item.get("kind") == "memory"
                else _apply_skill_request(item)
            )
            if not apply_result.get("success"):
                return apply_result

        item["status"] = "approved" if approve else "denied"
        item["decided_at"] = _now()
        item["decided_by"] = _actor_payload(actor)
        item["decision_note"] = note
        item["apply_result"] = apply_result
        _write_approvals(items)

        try:
            from agent.audit_log import record_audit_event

            record_audit_event(
                "knowledge.approval_decided",
                actor=actor,
                action=f"knowledge.{item.get('kind')}.{item.get('action')}",
                resource=f"{item.get('scope')}:{item.get('team') or 'all'}",
                outcome=item["status"],
                reason=note,
                metadata={"request_id": approval_id, "apply_result": apply_result},
            )
        except Exception:
            pass

        return {"success": True, "approval": item}
    return {"success": False, "error": "Approval not found.", "status_code": 404}


def knowledge_layers_summary(actor: Optional[Any] = None) -> dict[str, Any]:
    teams = actor_team_names(actor)
    return {
        "enabled": knowledge_enabled(),
        "corporate": {
            "memory_path": str(corporate_memory_path()),
            "skills_dir": str(corporate_skills_dir()),
            "memory_exists": corporate_memory_path().exists(),
            "skill_count": len(_iter_skill_md(corporate_skills_dir())),
        },
        "teams": [
            {
                "name": team,
                "memory_path": str(team_memory_path(team)),
                "skills_dir": str(team_skills_dir(team)),
                "memory_exists": team_memory_path(team).exists(),
                "skill_count": len(_iter_skill_md(team_skills_dir(team))),
            }
            for team in teams
        ],
        "user": {
            "memory_dir": str(get_hermes_home() / "memories"),
            "skills_dir": str(get_hermes_home() / "skills"),
        },
        "pending_approvals": len(list_knowledge_approvals("pending")),
    }

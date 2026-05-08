"""Enterprise governance helpers for Coorporate Hermes.

This module keeps identity, role hierarchy, folder policies, and cron
authorization checks in one place.  The runtime remains backward compatible:
governance is inert until ``governance.enabled`` is true and a matching policy
is configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class Actor:
    """Identity observed from a gateway, cron, or local CLI session."""

    platform: str = "local"
    user_id: str = ""
    user_name: str = ""
    roles: tuple[str, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        keys: list[str] = []
        platform = (self.platform or "local").strip().lower()
        user_id = str(self.user_id or "").strip()
        user_name = str(self.user_name or "").strip()
        if user_id:
            keys.extend([f"{platform}:{user_id}", user_id])
        if user_name:
            keys.extend([f"{platform}:{user_name}", user_name])
        if platform == "local":
            local_user = os.getenv("USER") or os.getenv("USERNAME") or ""
            if local_user:
                keys.extend([f"local:{local_user}", local_user])
            keys.append("local")
        # Preserve order while removing duplicates.
        return tuple(dict.fromkeys(k for k in keys if k))


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _config_path() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "config.yaml"


def load_governance_config() -> dict[str, Any]:
    """Load the ``governance`` section from config.yaml."""

    path = _config_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return {}
    governance = cfg.get("governance", {})
    return governance if isinstance(governance, dict) else {}


def is_enabled(config: Optional[dict[str, Any]] = None) -> bool:
    cfg = load_governance_config() if config is None else config
    return bool(cfg.get("enabled"))


def current_actor() -> Actor:
    """Return the current actor from gateway ContextVars or local env."""

    try:
        from gateway.session_context import get_session_env

        platform = get_session_env("HERMES_SESSION_PLATFORM", "") or "local"
        user_id = get_session_env("HERMES_SESSION_USER_ID", "")
        user_name = get_session_env("HERMES_SESSION_USER_NAME", "")
    except Exception:
        platform = "local"
        user_id = ""
        user_name = ""

    # Explicit local/automation override for tests and service accounts.
    user_override = os.getenv("COORPORATE_USER_ID", "").strip()
    if user_override:
        user_id = user_override
        platform = os.getenv("COORPORATE_USER_PLATFORM", platform or "local")

    return Actor(platform=platform or "local", user_id=user_id, user_name=user_name)


def _user_record(config: dict[str, Any], actor: Actor) -> dict[str, Any]:
    users = config.get("users", {})
    if not isinstance(users, dict):
        return {}
    for key in actor.keys:
        record = users.get(key)
        if isinstance(record, dict):
            return record
        if isinstance(record, str):
            return {"roles": _coerce_list(record)}
        if isinstance(record, list):
            return {"roles": _coerce_list(record)}
    return {}


def actor_roles(
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> list[str]:
    cfg = load_governance_config() if config is None else config
    who = current_actor() if actor is None else actor
    direct_roles = _coerce_list(getattr(who, "roles", None))
    if direct_roles:
        return direct_roles
    record = _user_record(cfg, who)
    roles = _coerce_list(record.get("roles"))
    if not roles:
        default_role = str(cfg.get("default_role", "")).strip()
        if default_role:
            roles = [default_role]
    return roles


def actor_teams(
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Return governance team identifiers assigned to *actor*."""

    cfg = load_governance_config() if config is None else config
    who = current_actor() if actor is None else actor
    record = _user_record(cfg, who)
    return _coerce_list(record.get("teams") or record.get("team"))


def actor_display(actor: Optional[Actor] = None) -> str:
    who = current_actor() if actor is None else actor
    return next(iter(who.keys), who.platform or "local")


def _role_rank(config: dict[str, Any], role: str) -> Optional[int]:
    hierarchy = _coerce_list(config.get("role_hierarchy"))
    if not hierarchy:
        return None
    try:
        return hierarchy.index(role)
    except ValueError:
        return None


def role_satisfies(config: dict[str, Any], granted: str, required: str) -> bool:
    if granted == required:
        return True
    granted_rank = _role_rank(config, granted)
    required_rank = _role_rank(config, required)
    if granted_rank is None or required_rank is None:
        return False
    return granted_rank >= required_rank


def actor_has_any_role(
    required_roles: list[str],
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> bool:
    if not required_roles:
        return True
    cfg = load_governance_config() if config is None else config
    roles = actor_roles(actor, cfg)
    return any(
        role_satisfies(cfg, granted, required)
        for granted in roles
        for required in required_roles
    )


def _resolve_policy_path(raw: Any) -> Optional[Path]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return Path(text).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _matching_folder_policy(path: str, config: dict[str, Any]) -> Optional[dict[str, Any]]:
    try:
        target = Path(path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    matches: list[tuple[int, dict[str, Any]]] = []
    policies = config.get("folder_policies", [])
    if not isinstance(policies, list):
        return None
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        root = _resolve_policy_path(policy.get("path"))
        if root is None:
            continue
        recursive = bool(policy.get("recursive", True))
        try:
            if target == root:
                matches.append((len(str(root)), policy))
            elif recursive:
                target.relative_to(root)
                matches.append((len(str(root)), policy))
        except ValueError:
            continue
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def _actor_matches_any(actor: Actor, allowed: list[str]) -> bool:
    return bool(set(actor.keys).intersection(allowed))


def _audit_file_access(
    actor: Actor,
    path: str,
    operation: str,
    allowed: bool,
    reason: str = "",
) -> None:
    try:
        from agent.audit_log import record_audit_event

        record_audit_event(
            "governance.file_access",
            actor=actor,
            action=operation,
            resource=path,
            outcome="allowed" if allowed else "denied",
            reason=reason or None,
            metadata={"operation": operation},
        )
    except Exception:
        pass


def check_file_access(
    path: str,
    operation: str,
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Return ``(allowed, reason)`` for a file read/write/search operation."""

    cfg = load_governance_config() if config is None else config
    if not is_enabled(cfg):
        return True, ""

    who = current_actor() if actor is None else actor
    op = "write" if operation in {"write", "delete", "move", "patch"} else "read"
    policy = _matching_folder_policy(path, cfg)

    def _deny(reason: str) -> tuple[bool, str]:
        _audit_file_access(who, path, op, False, reason)
        return False, reason

    if policy is None:
        default_policy = str(cfg.get("default_file_policy", "allow")).strip().lower()
        if default_policy == "deny":
            return _deny(
                f"Access denied by governance: no folder policy allows {op} on {path!r} for {actor_display(who)}.",
            )
        return True, ""

    denied_users = _coerce_list(policy.get("deny_users"))
    if denied_users and _actor_matches_any(who, denied_users):
        return _deny(
            f"Access denied by governance: {actor_display(who)} is explicitly denied for {path!r}.",
        )

    denied_teams = _coerce_list(policy.get("deny_teams"))
    who_teams = actor_teams(who, cfg)
    if denied_teams and set(who_teams).intersection(denied_teams):
        return _deny(
            f"Access denied by governance: {actor_display(who)} is explicitly denied by team for {path!r}.",
        )

    user_keys = _coerce_list(policy.get(f"{op}_users")) or _coerce_list(policy.get("users"))
    if user_keys and _actor_matches_any(who, user_keys):
        return True, ""

    team_keys = _coerce_list(policy.get(f"{op}_teams")) or _coerce_list(policy.get("teams"))
    if team_keys and set(who_teams).intersection(team_keys):
        return True, ""

    required_roles = _coerce_list(policy.get(f"{op}_roles"))
    if not required_roles and op == "read":
        required_roles = _coerce_list(policy.get("roles"))
    if required_roles and actor_has_any_role(required_roles, actor=who, config=cfg):
        return True, ""

    if user_keys or team_keys or required_roles:
        return _deny(
            "Access denied by governance: "
            f"{actor_display(who)} lacks {op} access to {path!r}. "
            f"Required roles: {required_roles or 'none'}; "
            f"allowed teams: {team_keys or 'none'}; "
            f"allowed users: {user_keys or 'none'}.",
        )

    grant_fields = (
        "roles",
        "read_roles",
        "write_roles",
        "teams",
        "read_teams",
        "write_teams",
        "users",
        "read_users",
        "write_users",
    )
    if any(_coerce_list(policy.get(field)) for field in grant_fields):
        return _deny(
            "Access denied by governance: "
            f"the matching folder policy for {path!r} does not configure {op} access "
            f"for {actor_display(who)}.",
        )

    return True, ""


def file_access_error(path: str, operation: str) -> Optional[str]:
    allowed, reason = check_file_access(path, operation)
    return None if allowed else reason


def can_authorize(
    authorization: dict[str, Any],
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Return whether *actor* can approve/deny a cron authorization node."""

    cfg = load_governance_config() if config is None else config
    who = current_actor() if actor is None else actor
    users = _coerce_list(authorization.get("users") or authorization.get("user"))
    if users and _actor_matches_any(who, users):
        return True, ""

    roles = _coerce_list(authorization.get("roles") or authorization.get("role"))
    if not roles:
        cron_cfg = cfg.get("cron", {}) if isinstance(cfg.get("cron"), dict) else {}
        roles = _coerce_list(cron_cfg.get("default_authorizer_roles")) or ["admin"]
    if actor_has_any_role(roles, actor=who, config=cfg):
        return True, ""
    return (
        False,
        f"{actor_display(who)} is not authorized. Required roles: {roles}; allowed users: {users or 'none'}.",
    )

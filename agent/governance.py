"""Enterprise governance helpers for Maia.

This module keeps identity, role hierarchy, folder policies, and cron
authorization checks in one place. Governance is an always-on Maia security
boundary: non-local actors fail closed unless an explicit policy grants the
requested operation. Malformed configuration also fails closed.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

_CONFIG_ERROR_KEY = "__config_load_error__"
GOVERNANCE_DENIAL_CODE = "governance_access_denied"
_ACCESS_REQUEST_GUIDANCE = (
    "Do not try another tool or alternate path. Tell the requester that Maia "
    "Governance does not grant them access to this resource and that an "
    "authorized manager or administrator must review the path grant. This is "
    "different from a conditional edit review. Never change an access policy "
    "unless an authorized sender explicitly asks to administer access."
)


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


def _config_error_config(message: str) -> dict[str, Any]:
    return {
        "enabled": True,
        _CONFIG_ERROR_KEY: message,
    }


def _governance_config_error(config: dict[str, Any]) -> str:
    return str(config.get(_CONFIG_ERROR_KEY) or "").strip()


def _load_config_document() -> dict[str, Any]:
    """Load config.yaml as a plain dict without importing the CLI loader."""
    path = _config_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as exc:
        return _config_error_config(f"Could not parse {path}: {exc}")
    if not isinstance(cfg, dict):
        return _config_error_config(
            f"Could not parse {path}: expected a mapping at the document root."
        )
    return cfg


def load_governance_config() -> dict[str, Any]:
    """Load the ``governance`` section from config.yaml."""

    cfg = _load_config_document()
    if _governance_config_error(cfg):
        return cfg
    if "governance" in cfg and cfg.get("governance") is not None:
        governance = cfg.get("governance", {})
        if not isinstance(governance, dict):
            return _config_error_config(
                "Could not load governance config: expected the governance "
                "section to be a mapping."
            )
    governance = cfg.get("governance", {})
    return governance if isinstance(governance, dict) else {}


def is_enabled(config: Optional[dict[str, Any]] = None) -> bool:
    """Return the immutable Maia governance posture.

    ``governance.enabled`` existed while the distribution was opt-in. Maia is
    now governed by construction, so even a missing or legacy ``false`` value
    cannot turn authorization checks into allow-all behavior. The config
    migration still rewrites the persisted value to ``true`` so the dashboard
    and backups accurately describe the runtime posture.
    """

    return True


def governance_tool_error(
    reason: str,
    *,
    operation: str = "",
    resource: str = "",
) -> str:
    """Return a structured denial that models can explain consistently."""

    message = str(reason or "Access denied by Maia Governance.").strip()
    if _ACCESS_REQUEST_GUIDANCE not in message:
        message = f"{message} {_ACCESS_REQUEST_GUIDANCE}"
    payload: dict[str, Any] = {
        "error": message,
        "code": GOVERNANCE_DENIAL_CODE,
        "denied_by": "maia_governance",
        "retryable": False,
        "user_guidance": _ACCESS_REQUEST_GUIDANCE,
    }
    if operation:
        payload["operation"] = operation
    if resource:
        payload["resource"] = resource
    return json.dumps(payload, ensure_ascii=False)


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
    user_override = os.getenv("MAIA_USER_ID", "").strip()
    if user_override:
        user_id = user_override
        platform = os.getenv("MAIA_USER_PLATFORM", platform or "local")

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


def is_trusted_local_operator(
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> bool:
    """Return whether *actor* is the unscoped local maintenance authority.

    Gateway, API, cron-origin, and explicitly configured local identities are
    governed. The person operating Maia directly on its host remains the
    bootstrap/break-glass authority unless they deliberately add a ``local``
    governance record, in which case normal policies apply to that identity.
    """

    cfg = load_governance_config() if config is None else config
    who = current_actor() if actor is None else actor
    if str(who.platform or "local").strip().lower() != "local":
        return False
    return not bool(_user_record(cfg, who))


def explicit_user_record(
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return an explicitly configured governance user record.

    Unlike :func:`actor_roles`, this helper never falls back to
    ``governance.default_role``.  Gateway admission uses it as a fail-closed
    membership check: an allowlist or pairing approval is necessary, but a
    human actor is not allowed to reach the bot until an administrator has
    also created a Governance record with at least one role.
    """

    cfg = load_governance_config() if config is None else config
    who = current_actor() if actor is None else actor
    users = cfg.get("users", {})
    if not isinstance(users, dict):
        return None
    platform = str(who.platform or "local").strip().lower()
    user_id = str(who.user_id or "").strip()
    if not user_id:
        return None
    # Gateway membership must be tied to the stable sender ID. Display names
    # are mutable and may collide, so the broader Actor.keys name fallbacks
    # used by legacy policy lookups are intentionally excluded here.
    stable_keys = (f"{platform}:{user_id}", user_id)
    for key in stable_keys:
        if key not in users:
            continue
        value = users[key]
        if isinstance(value, dict):
            record = dict(value)
        elif isinstance(value, (str, list, tuple, set)):
            record = {"roles": _coerce_list(value)}
        else:
            return None
        return record if _coerce_list(record.get("roles")) else None
    return None


def has_explicit_user_access(
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> bool:
    """Whether *actor* has an explicit Governance record with a role."""

    return explicit_user_record(actor=actor, config=config) is not None


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
    if _governance_config_error(cfg):
        return False
    roles = actor_roles(actor, cfg)
    return any(
        role_satisfies(cfg, granted, required)
        for granted in roles
        for required in required_roles
    )


def resolve_governed_path(raw: Any) -> Optional[Path]:
    """Resolve native, WSL, and Windows-style paths to one host identity."""

    text = str(raw or "").strip()
    if not text:
        return None
    # Maia commonly runs in WSL while administrators paste a Windows path in
    # the dashboard or Discord. pathlib on Linux treats ``C:\\...`` as a
    # relative filename; translate it to the actual WSL mount first. Also
    # recover it when a caller already prefixed the current directory.
    match = re.search(r"(?:^|/)([A-Za-z]):[\\/](.+)$", text)
    if match and os.name != "nt":
        drive, remainder = match.groups()
        text = f"/mnt/{drive.lower()}/{remainder.replace(chr(92), '/')}"
    elif os.name == "nt" and text.startswith("/mnt/") and len(text) > 7:
        drive = text[5]
        if text[6] == "/":
            text = f"{drive.upper()}:/{text[7:]}"
    try:
        return Path(text).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _resolve_policy_path(raw: Any) -> Optional[Path]:
    return resolve_governed_path(raw)


def _folder_policies_malformed(config: dict[str, Any]) -> Optional[str]:
    """Return a reason string when ``folder_policies`` is structurally invalid.

    The advertised contract is that a malformed governance configuration fails
    CLOSED. Without this, a ``folder_policies`` written as a mapping instead of
    a list, a non-mapping entry, or an entry whose ``path`` is missing/blank/
    unresolvable is silently dropped — so a policy meant to RESTRICT a folder
    just vanishes and access falls through to the immutable deny default.
    Better to deny-all and alert the admin than to grant-all invisibly.
    Returns None when the structure is well-formed
    (including simply absent).
    """
    if "folder_policies" not in config:
        return None
    policies = config.get("folder_policies")
    if policies is None:
        return None
    if not isinstance(policies, list):
        return "governance.folder_policies must be a list of policy entries"
    for idx, policy in enumerate(policies):
        if not isinstance(policy, dict):
            return f"governance.folder_policies[{idx}] is not a mapping"
        if "path" not in policy:
            return f"governance.folder_policies[{idx}] is missing 'path'"
        if _resolve_policy_path(policy.get("path")) is None:
            return (
                f"governance.folder_policies[{idx}] has an invalid or "
                f"unresolvable 'path': {policy.get('path')!r}"
            )
    return None


def _all_matching_folder_policies(
    path: str, config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return every folder policy whose root contains *path*, most-specific first.

    Both the exact-path policy and every recursive ancestor policy match. The
    caller reads grants from the most-specific entry (``[0]``) but must honor
    ``deny_*`` from ALL entries so a broad parent-folder denial cannot be
    re-granted by a narrower child policy (least privilege).
    """
    try:
        target = resolve_governed_path(path)
    except (OSError, RuntimeError):
        return []
    if target is None:
        return []
    matches: list[tuple[int, dict[str, Any]]] = []
    policies = config.get("folder_policies", [])
    if not isinstance(policies, list):
        return []
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
    matches.sort(key=lambda item: item[0], reverse=True)
    return [policy for _, policy in matches]


def _matching_folder_policy(path: str, config: dict[str, Any]) -> Optional[dict[str, Any]]:
    matches = _all_matching_folder_policies(path, config)
    return matches[0] if matches else None


def _allowed_nonrecursive_parent(
    path: str,
    operation: str,
    *,
    actor: Actor,
    config: dict[str, Any],
) -> Optional[str]:
    """Return the nearest exact-only parent grant that explains a denial.

    A non-recursive policy on a directory intentionally does not match files
    below it.  Detecting that case lets the tool explain the actual scope
    mismatch instead of incorrectly telling a conditional writer that they
    have no write permission at all.
    """

    target = resolve_governed_path(path)
    if target is None:
        return None

    candidates: list[Path] = []
    policies = config.get("folder_policies")
    if not isinstance(policies, list):
        return None
    for policy in policies:
        if not isinstance(policy, dict) or bool(policy.get("recursive", True)):
            continue
        root = _resolve_policy_path(policy.get("path"))
        if root is None or target == root:
            continue
        try:
            target.relative_to(root)
        except ValueError:
            continue
        candidates.append(root)

    for root in sorted(candidates, key=lambda item: len(str(item)), reverse=True):
        allowed, _ = check_file_access(
            str(root),
            operation,
            actor=actor,
            config=config,
        )
        if allowed:
            return str(root)
    return None


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
    who = current_actor() if actor is None else actor
    op = "write" if operation in {"write", "delete", "move", "patch"} else "read"

    def _deny(reason: str) -> tuple[bool, str]:
        if _ACCESS_REQUEST_GUIDANCE not in reason:
            reason = f"{reason} {_ACCESS_REQUEST_GUIDANCE}"
        _audit_file_access(who, path, op, False, reason)
        return False, reason

    config_error = _governance_config_error(cfg)
    if config_error:
        return _deny(
            "Access denied by governance: config.yaml could not be loaded, "
            f"so {op} access to {path!r} is blocked until the governance "
            f"configuration is fixed. {config_error}",
        )

    if is_trusted_local_operator(who, cfg):
        return True, ""

    # Malformed folder_policies must fail closed, matching the top-level
    # config-error contract — otherwise a policy meant to restrict a folder
    # silently disappears and access falls through to the permissive default.
    policies_error = _folder_policies_malformed(cfg)
    if policies_error:
        return _deny(
            "Access denied by governance: folder policies are misconfigured, "
            f"so {op} access to {path!r} is blocked until the governance "
            f"configuration is fixed. {policies_error}",
        )

    matching_policies = _all_matching_folder_policies(path, cfg)
    policy = matching_policies[0] if matching_policies else None

    # Ancestor-deny cascade: an explicit deny on ANY matching policy (the
    # exact folder OR any recursive parent) wins, even when a narrower child
    # policy would otherwise grant. Without this, "deny U on /company" is
    # silently re-granted by a "/company/finance: read_roles [manager]" child
    # policy for a manager U. Checked before grants; least privilege.
    who_teams = actor_teams(who, cfg)
    for ancestor in matching_policies:
        anc_denied_users = _coerce_list(ancestor.get("deny_users"))
        if anc_denied_users and _actor_matches_any(who, anc_denied_users):
            return _deny(
                f"Access denied by governance: {actor_display(who)} is explicitly "
                f"denied for {path!r} (by a folder policy on this path or a parent).",
            )
        anc_denied_teams = _coerce_list(ancestor.get("deny_teams"))
        if anc_denied_teams and set(who_teams).intersection(anc_denied_teams):
            return _deny(
                f"Access denied by governance: {actor_display(who)} is explicitly "
                f"denied by team for {path!r} (by a folder policy on this path or a parent).",
            )

    if policy is None:
        exact_parent = _allowed_nonrecursive_parent(
            path,
            op,
            actor=who,
            config=cfg,
        )
        if exact_parent:
            return _deny(
                "Access denied by governance: the requester has "
                f"{op} access to {exact_parent!r}, but that grant is configured "
                "for the exact path only and does not include files or "
                f"subfolders such as {path!r}. An authorized administrator "
                "must enable files and subfolders on the existing grant. This "
                "is a path-scope mismatch, not an approval decision for a "
                "prepared edit.",
            )
        return _deny(
            f"Access denied by governance: no folder policy allows {op} on {path!r} for {actor_display(who)}.",
        )

    # deny_users/deny_teams (incl. ancestor cascade) were already enforced
    # above across all matching policies.
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

    return _deny(
        "Access denied by governance: "
        f"the matching folder policy for {path!r} has no {op} grant for "
        f"{actor_display(who)}."
    )


def readable_governed_paths(
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Return the configured path roots the actor may currently read.

    This is an actor-scoped projection of ``folder_policies`` for search and
    prompt guidance.  It never broadens access: every returned path is resolved
    through the same path normalizer and rechecked with ``check_file_access``.
    Malformed configuration and trusted-local mode return no projected roots;
    the former fails closed while the latter does not need an allowlist.
    """

    cfg = load_governance_config() if config is None else config
    who = current_actor() if actor is None else actor
    if (
        _governance_config_error(cfg)
        or _folder_policies_malformed(cfg)
        or is_trusted_local_operator(who, cfg)
    ):
        return []

    policies = cfg.get("folder_policies")
    if not isinstance(policies, list):
        return []

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for policy in policies:
        if not isinstance(policy, dict):
            continue
        resolved = _resolve_policy_path(policy.get("path"))
        if resolved is None:
            continue
        path = str(resolved)
        allowed, _ = check_file_access(path, "read", actor=who, config=cfg)
        if not allowed:
            continue
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "path": path,
                "recursive": bool(policy.get("recursive", True)),
            }
        )

    result.sort(key=lambda item: os.path.normcase(str(item["path"])))
    return result


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
    config_error = _governance_config_error(cfg)
    if config_error:
        return (
            False,
            "Cron authorization denied by governance: config.yaml could not "
            "be loaded until the governance configuration is fixed. "
            f"{config_error}",
        )

    # The unscoped local operator is the bootstrap/break-glass authority. This
    # does not auto-approve: the job still waits for an explicit decision.
    if is_trusted_local_operator(who, cfg):
        return True, ""

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


def can_approve_file_change(
    requirement: dict[str, Any],
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Return whether *actor* can approve/deny a staged file change.

    *requirement* is the dict produced by ``file_write_approval_requirement``
    (``roles`` / ``users`` lists). Mirrors ``can_authorize`` semantics: config
    errors fail closed; with governance disabled the local operator is the
    trust authority, so an explicit human decision may proceed.
    """

    cfg = load_governance_config() if config is None else config
    who = current_actor() if actor is None else actor
    config_error = _governance_config_error(cfg)
    if config_error:
        return (
            False,
            "File-change approval denied by governance: config.yaml could not "
            "be loaded until the governance configuration is fixed. "
            f"{config_error}",
        )
    if is_trusted_local_operator(who, cfg):
        return True, ""

    users = _coerce_list(requirement.get("users"))
    if users and _actor_matches_any(who, users):
        return True, ""
    roles = _coerce_list(requirement.get("roles"))
    if roles and actor_has_any_role(roles, actor=who, config=cfg):
        return True, ""
    return (
        False,
        f"{actor_display(who)} cannot approve this file change. "
        f"Required roles: {roles or 'none'}; allowed users: {users or 'none'}.",
    )


def file_write_approval_requirement(
    path: str,
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return the review requirement for a write to *path*, if any.

    Folder policies may declare ``write_approval_roles`` and/or
    ``write_approval_users``. When they do, file tools block execution for an
    actor who holds a conditional write grant and return the eligible writers
    to involve in the conversation. A sender who satisfies the requirement
    writes directly. The nearest (most specific) matching policy that declares
    either key wins; declaring both keys empty on a child policy explicitly
    opts its subtree out of an ancestor's requirement.

    Returns ``None`` when no approval is needed: governance is misconfigured
    (``check_file_access`` already fails closed on config
    errors, so this helper stays quiet), no matching policy declares a
    requirement, or *actor* satisfies the requirement themselves.
    """

    cfg = load_governance_config() if config is None else config
    if _governance_config_error(cfg) or not is_enabled(cfg):
        return None
    if _folder_policies_malformed(cfg):
        return None

    who = current_actor() if actor is None else actor
    for policy in _all_matching_folder_policies(path, cfg):
        if (
            "write_approval_roles" not in policy
            and "write_approval_users" not in policy
        ):
            continue
        roles = _coerce_list(policy.get("write_approval_roles"))
        users = _coerce_list(policy.get("write_approval_users"))
        if not roles and not users:
            return None
        requirement = {
            "roles": roles,
            "users": users,
            "policy_path": str(_resolve_policy_path(policy.get("path"))),
        }
        allowed, _reason = can_approve_file_change(
            requirement, actor=who, config=cfg
        )
        if allowed:
            return None
        return requirement
    return None


def eligible_file_change_approvers(
    requirement: dict[str, Any],
    *,
    config: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Return actor keys that satisfy *requirement*, for notification routing.

    Combines the requirement's explicit ``users`` with every entry in
    ``governance.users`` whose roles satisfy one of the required roles.
    Keys keep their configured form (e.g. ``slack:U123``) so callers can
    filter by platform prefix when formatting mentions.
    """

    cfg = load_governance_config() if config is None else config
    if _governance_config_error(cfg):
        return []
    req_users = _coerce_list(requirement.get("users"))
    req_roles = _coerce_list(requirement.get("roles"))
    result: list[str] = list(req_users)

    users = cfg.get("users", {})
    if isinstance(users, dict) and req_roles:
        for key, record in users.items():
            key_str = str(key).strip()
            if not key_str or key_str in result:
                continue
            if isinstance(record, dict):
                granted = _coerce_list(record.get("roles"))
            else:
                granted = _coerce_list(record)
            if any(
                role_satisfies(cfg, granted_role, required_role)
                for granted_role in granted
                for required_role in req_roles
            ):
                result.append(key_str)
    return result


def _terminal_config(config: dict[str, Any]) -> dict[str, Any]:
    terminal = config.get("terminal", {})
    return terminal if isinstance(terminal, dict) else {}


def terminal_access_error(
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Return a denial reason when *actor* may not run shell commands at all.

    Gateway shell and sandboxed-code execution are isolated to policy-derived
    Docker mounts. This function is the additional whole-tool gate. When
    ``governance.terminal.allowed_roles`` / ``allowed_users`` is configured,
    actors outside it cannot use the terminal or execute_code tools. Unset
    means no restriction (backward compatible).
    """

    cfg = load_governance_config() if config is None else config
    who = current_actor() if actor is None else actor

    def _deny(reason: str) -> str:
        if _ACCESS_REQUEST_GUIDANCE not in reason:
            reason = f"{reason} {_ACCESS_REQUEST_GUIDANCE}"
        try:
            from agent.audit_log import record_audit_event

            record_audit_event(
                "governance.terminal_access",
                actor=who,
                action="terminal.execute",
                resource="terminal",
                outcome="denied",
                reason=reason,
            )
        except Exception:
            pass
        return reason

    config_error = _governance_config_error(cfg)
    if config_error:
        return _deny(
            "Terminal access denied by governance: config.yaml could not be "
            "loaded, so command execution is blocked until the governance "
            f"configuration is fixed. {config_error}"
        )
    if is_trusted_local_operator(who, cfg):
        return None

    terminal_cfg = _terminal_config(cfg)
    allowed_roles = _coerce_list(terminal_cfg.get("allowed_roles"))
    allowed_users = _coerce_list(terminal_cfg.get("allowed_users"))
    if not allowed_roles and not allowed_users:
        return None
    if allowed_users and _actor_matches_any(who, allowed_users):
        return None
    if allowed_roles and actor_has_any_role(allowed_roles, actor=who, config=cfg):
        return None
    return _deny(
        f"Terminal access denied by governance: {actor_display(who)} is not "
        "permitted to run commands. "
        f"Required roles: {allowed_roles or 'none'}; "
        f"allowed users: {allowed_users or 'none'}."
    )


def terminal_approval_requirement(
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Return the approver requirement for *actor*'s flagged commands, if any.

    When ``governance.terminal.approver_roles`` / ``approver_users`` is set,
    dangerous-command approvals raised in gateway sessions must be decided by
    an actor satisfying the requirement — the requesting user can no longer
    self-approve. Returns ``None`` when governance is misconfigured (the
    terminal access gate handles config errors), when no requirement is
    configured, or when *actor* satisfies it themselves (managers and admins
    keep the existing self-approval flow).
    """

    cfg = load_governance_config() if config is None else config
    if _governance_config_error(cfg) or not is_enabled(cfg):
        return None
    terminal_cfg = _terminal_config(cfg)
    roles = _coerce_list(terminal_cfg.get("approver_roles"))
    users = _coerce_list(terminal_cfg.get("approver_users"))
    if not roles and not users:
        return None
    who = current_actor() if actor is None else actor
    requirement = {"roles": roles, "users": users}
    allowed, _reason = can_approve_file_change(requirement, actor=who, config=cfg)
    if allowed:
        return None
    return requirement


def governance_posture_warnings(
    *,
    config: Optional[dict[str, Any]] = None,
    full_config: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Return posture warnings when governance is ENABLED but weak.

    A single source of truth shared by ``maia doctor``, the dashboard status
    endpoint, and the gateway startup log, so all three agree on what "weakly
    configured" means. Each item is
    ``{"severity": "warning"|"error", "code": str, "message": str}``.

    An empty list means either governance is disabled (personal mode — no
    opinion) or the posture is solid. A config-load error surfaces as one
    error item, because sensitive checks fail closed until it is fixed.
    """

    cfg = load_governance_config() if config is None else config
    full = _load_config_document() if full_config is None else full_config
    full = full if isinstance(full, dict) else {}

    config_error = _governance_config_error(cfg)
    if config_error:
        return [{
            "severity": "error",
            "code": "config_error",
            "message": (
                "Governance config could not be loaded; file and cron checks "
                f"fail closed until it is fixed. {config_error}"
            ),
        }]

    if not is_enabled(cfg):
        return []

    warnings: list[dict[str, Any]] = []

    policies = cfg.get("folder_policies")
    has_policies = isinstance(policies, list) and len(policies) > 0
    roots = cfg.get("team_file_roots")
    has_roots = isinstance(roots, dict) and len(roots) > 0
    if not has_policies and not has_roots:
        warnings.append({
            "severity": "warning",
            "code": "no_folder_policies",
            "message": (
                "No folder policies or delegated team roots are configured. "
                "All gateway file access is denied until an administrator "
                "adds explicit grants in the File Access panel."
            ),
        })
    if isinstance(policies, list):
        for policy in policies:
            if not isinstance(policy, dict):
                continue
            requirement = {
                "roles": _coerce_list(policy.get("write_approval_roles")),
                "users": _coerce_list(policy.get("write_approval_users")),
            }
            if not requirement["roles"] and not requirement["users"]:
                continue
            if eligible_file_change_approvers(requirement, config=cfg):
                continue
            warnings.append({
                "severity": "error",
                "code": "file_approval_without_eligible_identity",
                "message": (
                    f"Write approval for {policy.get('path') or 'an unnamed path'} "
                    "has no eligible governed identity. Assign one of the selected "
                    "approver roles to a gateway user or choose a specific approver; "
                    "until then, requested changes fail closed and remain unchanged."
                ),
            })

    terminal_cfg = _terminal_config(cfg)
    terminal_allowed = _coerce_list(terminal_cfg.get("allowed_roles")) or _coerce_list(
        terminal_cfg.get("allowed_users")
    )
    terminal_approver = _coerce_list(terminal_cfg.get("approver_roles")) or _coerce_list(
        terminal_cfg.get("approver_users")
    )
    if not terminal_allowed and not terminal_approver:
        warnings.append({
            "severity": "warning",
            "code": "terminal_ungoverned",
            "message": (
                "Terminal and code execution are ungated and flagged commands "
                "are self-approved by the requester. Set "
                "governance.terminal.allowed_roles and/or approver_roles."
            ),
        })

    approvals = full.get("approvals", {})
    approvals = approvals if isinstance(approvals, dict) else {}
    mode = str(approvals.get("mode", "manual") or "manual").strip().lower()
    if mode == "off":
        warnings.append({
            "severity": "warning",
            "code": "approvals_off",
            "message": (
                "approvals.mode is 'off', so dangerous commands run without "
                "prompting. Use 'manual' or 'smart'."
            ),
        })

    observability = full.get("observability", {})
    observability = observability if isinstance(observability, dict) else {}
    if not observability.get("audit_log_enabled"):
        warnings.append({
            "severity": "warning",
            "code": "audit_disabled",
            "message": (
                "Audit logging is disabled, so governance decisions leave no "
                "trail. Set observability.audit_log_enabled: true."
            ),
        })

    return warnings


def _roles_allow(
    config: dict[str, Any],
    granted_roles: list[str],
    required_roles: list[str],
) -> bool:
    required = _coerce_list(required_roles)
    if not required:
        return True
    granted = _coerce_list(granted_roles)
    if not granted:
        return False
    return any(
        role_satisfies(config, granted_role, required_role)
        for granted_role in granted
        for required_role in required
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _dashboard_auth_config(full_config: dict[str, Any]) -> dict[str, Any]:
    dashboard = full_config.get("dashboard", {})
    if not isinstance(dashboard, dict):
        return {}
    auth = dashboard.get("auth", {})
    return auth if isinstance(auth, dict) else {}


def _knowledge_config(full_config: dict[str, Any]) -> dict[str, Any]:
    knowledge = full_config.get("knowledge", {})
    return knowledge if isinstance(knowledge, dict) else {}


def _knowledge_scope_roles(
    knowledge_config: dict[str, Any],
    scope: str,
) -> list[str]:
    section = knowledge_config.get(scope, {})
    if not isinstance(section, dict):
        section = {}
    fallback = ["admin"] if scope == "corporate" else ["manager", "admin"]
    return _coerce_list(section.get("approver_roles")) or fallback


def _managed_team_roots_for_actor(
    actor: Actor,
    config: dict[str, Any],
) -> dict[str, str]:
    roots = config.get("team_file_roots", {})
    if not isinstance(roots, dict):
        return {}

    actor_keys = set(actor.keys)
    teams = set(actor_teams(actor, config))
    default_roles = _coerce_list(config.get("team_file_manager_roles")) or [
        "manager",
        "admin",
    ]
    result: dict[str, str] = {}

    for team, raw_entry in roots.items():
        if isinstance(raw_entry, str):
            entry: dict[str, Any] = {"path": raw_entry}
        elif isinstance(raw_entry, dict):
            entry = raw_entry
        else:
            continue

        path = str(entry.get("path") or "").strip()
        if not path:
            continue

        managers = set(
            _coerce_list(entry.get("managers") or entry.get("manager_users"))
        )
        if managers and actor_keys.intersection(managers):
            result[str(team)] = path
            continue

        manager_roles = _coerce_list(entry.get("manager_roles")) or default_roles
        if str(team) in teams and actor_has_any_role(
            manager_roles,
            actor=actor,
            config=config,
        ):
            result[str(team)] = path

    return result


def render_self_configuration_context(
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
    full_config: Optional[dict[str, Any]] = None,
) -> str:
    """Render actor-aware self-configuration guidance for skills.

    The returned text is intentionally advisory: it tells the model which
    configuration surfaces should be considered in-scope for the current actor,
    while the dashboard, file tools, knowledge approvals, and cron authorization
    code remain the enforcing controls.
    """

    cfg = dict(load_governance_config() if config is None else config)
    cfg.setdefault("default_role", "viewer")
    cfg.setdefault("role_hierarchy", ["viewer", "operator", "manager", "admin"])
    full = _load_config_document() if full_config is None else full_config
    full = full if isinstance(full, dict) else {}
    who = current_actor() if actor is None else actor

    roles = actor_roles(who, cfg)
    teams = actor_teams(who, cfg)
    hierarchy = _coerce_list(cfg.get("role_hierarchy")) or [
        "viewer",
        "operator",
        "manager",
        "admin",
    ]
    tenant = str(cfg.get("tenant_id") or "default")
    governance_enabled = is_enabled(cfg)
    config_error = _governance_config_error(cfg)
    governance_status = (
        "configuration error"
        if config_error
        else ("enabled" if governance_enabled else "disabled")
    )

    auth = _dashboard_auth_config(full)
    dashboard_auth_enabled = bool(auth.get("enabled"))
    dashboard_read_roles = _coerce_list(auth.get("read_roles")) or [
        "auditor",
        "manager",
        "admin",
    ]
    dashboard_manage_roles = _coerce_list(auth.get("manage_roles")) or [
        "manager",
        "admin",
    ]
    dashboard_admin_roles = _coerce_list(auth.get("admin_roles")) or ["admin"]
    can_dashboard_read = _roles_allow(cfg, roles, dashboard_read_roles)
    can_dashboard_manage = _roles_allow(cfg, roles, dashboard_manage_roles)
    can_dashboard_admin = _roles_allow(cfg, roles, dashboard_admin_roles)

    knowledge = _knowledge_config(full)
    knowledge_enabled = bool(knowledge.get("enabled", True))
    corporate_approver_roles = _knowledge_scope_roles(knowledge, "corporate")
    team_approver_roles = _knowledge_scope_roles(knowledge, "team")
    can_approve_corporate_knowledge = _roles_allow(cfg, roles, corporate_approver_roles)
    can_approve_team_knowledge = _roles_allow(cfg, roles, team_approver_roles)

    cron_cfg = cfg.get("cron", {}) if isinstance(cfg.get("cron"), dict) else {}
    cron_authorizer_roles = _coerce_list(cron_cfg.get("default_authorizer_roles")) or [
        "admin"
    ]
    can_authorize_default_cron = _roles_allow(cfg, roles, cron_authorizer_roles)

    managed_roots = _managed_team_roots_for_actor(who, cfg)
    managed_roots_text = str(managed_roots) if managed_roots else "none"
    default_file_policy = "deny (fixed)"

    lines = [
        "## Live Maia Governance Context",
        "",
        (
            "This block is generated when the skill loads. Use it to choose "
            "safe self-configuration actions for the current actor. "
            "Server-side policy checks remain authoritative."
        ),
        "",
        f"- Governance: {governance_status}",
        f"- Tenant: {tenant}",
        f"- Actor: {actor_display(who)}",
        f"- Roles: {', '.join(roles) if roles else 'none'}",
        f"- Teams: {', '.join(teams) if teams else 'none'}",
        f"- Role hierarchy: {' < '.join(hierarchy)}",
        f"- Default file policy: {default_file_policy}",
        "",
        "### Dashboard Scope",
        f"- Dashboard auth enabled: {_yes_no(dashboard_auth_enabled)}",
        (
            f"- Read dashboard data: {_yes_no(can_dashboard_read)} "
            f"(requires one of: {dashboard_read_roles})"
        ),
        (
            "- Manage approvals or delegated File Access: "
            f"{_yes_no(can_dashboard_manage)} "
            f"(requires one of: {dashboard_manage_roles})"
        ),
        (
            "- Administer config, secrets, models, gateway settings, dashboard "
            "auth, user authorization, plugins, global folder policies, "
            f"and roles: {_yes_no(can_dashboard_admin)} "
            f"(requires one of: {dashboard_admin_roles})"
        ),
        "",
        "### Knowledge And Skills",
        f"- Shared knowledge enabled: {_yes_no(knowledge_enabled)}",
        "- User memory and user skills: immediate when the corresponding tool is enabled.",
        (
            "- Team memory and team skills: stage a pending approval; do not "
            "write shared files directly."
        ),
        (
            "- Corporate memory and corporate skills: stage a pending "
            "approval; do not write shared files directly."
        ),
        (
            f"- Can approve team knowledge now: "
            f"{_yes_no(can_approve_team_knowledge)} "
            f"(approver roles: {team_approver_roles})"
        ),
        (
            "- Can approve corporate knowledge now: "
            f"{_yes_no(can_approve_corporate_knowledge)} "
            f"(approver roles: {corporate_approver_roles})"
        ),
        "",
        "### File And Cron Boundaries",
        (
            "- File reads, searches, writes, patches, deletes, and moves are "
            "checked per path against governance folder policies."
        ),
        (
            "- A prompt or skill instruction cannot grant itself a folder. "
            "Ask for a File Access policy change when access is denied."
        ),
        (
            "- Folders whose policy declares write_approval_roles/"
            "write_approval_users block conditional writers without changing "
            "or staging the file. Plan the edit and involve an eligible writer "
            "in the same shared thread; their later tool call is checked under "
            "their own authenticated identity."
        ),
        (
            "- Terminal and code execution can be restricted by "
            "governance.terminal.allowed_roles/allowed_users, and flagged "
            "commands may require an approver decision "
            "(governance.terminal.approver_roles/approver_users) — the "
            "requesting user cannot self-approve those."
        ),
        f"- Delegated team file roots this actor can manage: {managed_roots_text}",
        (
            "- Can approve cron jobs that omit explicit authorizers: "
            f"{_yes_no(can_authorize_default_cron)} "
            f"(default authorizer roles: {cron_authorizer_roles})"
        ),
        "",
        "### Self-Configuration Rule For This Actor",
    ]

    if config_error:
        lines.extend(
            [
                (
                    "- Governance configuration could not be loaded, so "
                    "server-side file and cron authorization checks fail "
                    "closed until the config is fixed."
                ),
                f"- Config error: {config_error}",
                (
                    "- Treat all broader access, self-configuration, and "
                    "shared automation actions as blocked until an authorized "
                    "administrator repairs config.yaml."
                ),
            ]
        )
    elif not governance_enabled:
        lines.extend(
            [
                (
                    "- Governance is disabled, so this actor snapshot is not "
                    "a sufficient enterprise authorization decision."
                ),
                (
                    "- Treat global configuration, secrets, models, toolsets, "
                    "MCP servers, gateway settings, dashboard auth, user "
                    "authorization, roles, and folder policies "
                    "as server-operator or administrator work."
                ),
            ]
        )
    elif can_dashboard_admin:
        lines.extend(
            [
                (
                    "- Admin-scope self-configuration is in scope when "
                    "requested by the user and done through audited "
                    "config/dashboard/CLI paths."
                ),
                (
                    "- Preserve existing governance, approval, dashboard auth, "
                    "audit, and default-deny file settings unless the user "
                    "explicitly asks for a reviewed change."
                ),
            ]
        )
    elif can_dashboard_manage:
        lines.extend(
            [
                (
                    "- Management-scope actions are limited to approval "
                    "decisions and delegated File Access roots listed above."
                ),
                (
                    "- Do not change global config, secrets, models, plugins, "
                    "gateway settings, user authorization, role hierarchy, "
                    "dashboard auth, or tenant-wide folder policy."
                ),
            ]
        )
    else:
        lines.extend(
            [
                (
                    "- Operator/viewer-scope actors may do assigned work only "
                    "inside enabled tools and allowed folders."
                ),
                (
                    "- Do not self-configure global settings, secrets, models, "
                    "toolsets, MCP servers, gateway settings, user "
                    "authorization, roles, dashboard auth, or folder policy."
                ),
                (
                    "- For broader access, stage a knowledge proposal if "
                    "appropriate or ask an authorized manager/admin to approve "
                    "the change."
                ),
            ]
        )

    return "\n".join(lines)

"""Shared governed administration for Maia's dashboard and messaging agent.

The model-facing tool never edits ``config.yaml`` directly.  It calls this
module with the authenticated gateway actor, and every mutation is authorized
again at execution time.  Pure policy helpers are also used by the dashboard so
both surfaces validate and persist the same shapes.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from agent.governance import Actor, role_satisfies


DEFAULT_ROLES = ["viewer", "operator", "manager", "admin"]

# Mirrors the human allowlists consumed by gateway.run.  Plugin platforms are
# resolved from the platform registry at runtime.
GATEWAY_ALLOWLIST_ENV: dict[str, str] = {
    "telegram": "TELEGRAM_ALLOWED_USERS",
    "discord": "DISCORD_ALLOWED_USERS",
    "whatsapp": "WHATSAPP_ALLOWED_USERS",
    "slack": "SLACK_ALLOWED_USERS",
    "signal": "SIGNAL_ALLOWED_USERS",
    "email": "EMAIL_ALLOWED_USERS",
    "sms": "SMS_ALLOWED_USERS",
    "mattermost": "MATTERMOST_ALLOWED_USERS",
    "matrix": "MATRIX_ALLOWED_USERS",
    "dingtalk": "DINGTALK_ALLOWED_USERS",
    "feishu": "FEISHU_ALLOWED_USERS",
    "wecom": "WECOM_ALLOWED_USERS",
    "wecom_callback": "WECOM_CALLBACK_ALLOWED_USERS",
    "weixin": "WEIXIN_ALLOWED_USERS",
    "bluebubbles": "BLUEBUBBLES_ALLOWED_USERS",
    "qqbot": "QQ_ALLOWED_USERS",
    "yuanbao": "YUANBAO_ALLOWED_USERS",
}

_FOLDER_POLICY_LIST_KEYS = (
    "roles",
    "read_roles",
    "write_roles",
    "teams",
    "read_teams",
    "write_teams",
    "deny_teams",
    "users",
    "read_users",
    "write_users",
    "deny_users",
    "write_approval_roles",
    "write_approval_users",
)
_FOLDER_POLICY_KEEP_EMPTY_KEYS = frozenset(
    ("write_approval_roles", "write_approval_users")
)
_CONFIG_WRITE_LOCK = threading.RLock()


class GovernanceAdminError(ValueError):
    """Safe, user-facing rejection from a governed administration action."""

    def __init__(self, message: str, *, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.code = code


def coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def normalize_folder_policy(raw: dict[str, Any]) -> dict[str, Any]:
    """Allowlist and normalize the fields accepted for a folder policy."""

    policy: dict[str, Any] = {}
    path = str(raw.get("path") or "").strip()
    if path:
        policy["path"] = path
    if "recursive" in raw:
        policy["recursive"] = bool(raw.get("recursive"))
    if raw.get("label"):
        policy["label"] = str(raw.get("label")).strip()
    if raw.get("description"):
        policy["description"] = str(raw.get("description")).strip()
    for key in _FOLDER_POLICY_LIST_KEYS:
        values = coerce_list(raw.get(key))
        if values:
            policy[key] = values
        elif key in _FOLDER_POLICY_KEEP_EMPTY_KEYS and isinstance(
            raw.get(key), (list, tuple)
        ):
            policy[key] = []
    return policy


def team_root_entries(governance: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = governance.get("team_file_roots", {})
    if not isinstance(raw, dict):
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for team, value in raw.items():
        if isinstance(value, str):
            entries[str(team)] = {"path": value}
        elif isinstance(value, dict):
            entries[str(team)] = dict(value)
    return entries


def governance_team_registry(
    governance: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return first-class teams plus legacy references, preserving spelling."""

    registry: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    def add(raw_name: Any, metadata: Any = None) -> None:
        name = str(raw_name or "").strip()
        folded = name.casefold()
        if not name or folded in seen:
            return
        seen.add(folded)
        registry[name] = dict(metadata) if isinstance(metadata, dict) else {}

    raw_registry = governance.get("teams")
    if isinstance(raw_registry, dict):
        for name, metadata in raw_registry.items():
            add(name, metadata)
    elif isinstance(raw_registry, list):
        for name in raw_registry:
            add(name)

    for name in team_root_entries(governance):
        add(name)

    users = governance.get("users")
    if isinstance(users, dict):
        for record in users.values():
            if isinstance(record, dict):
                for name in coerce_list(record.get("teams") or record.get("team")):
                    add(name)

    policies = governance.get("folder_policies")
    if isinstance(policies, list):
        for policy in policies:
            if not isinstance(policy, dict):
                continue
            for key in ("teams", "read_teams", "write_teams", "deny_teams"):
                for name in coerce_list(policy.get(key)):
                    add(name)
    return registry


def subject_file_grants(
    governance: dict[str, Any], *, subject: str, subject_kind: str
) -> list[dict[str, Any]]:
    generic_key = "users" if subject_kind == "user" else "teams"
    read_key = "read_users" if subject_kind == "user" else "read_teams"
    write_key = "write_users" if subject_kind == "user" else "write_teams"
    result: list[dict[str, Any]] = []
    for raw_policy in governance.get("folder_policies", []) or []:
        if not isinstance(raw_policy, dict):
            continue
        policy = normalize_folder_policy(raw_policy)
        path = str(policy.get("path") or "").strip()
        if not path:
            continue
        generic = subject in coerce_list(policy.get(generic_key))
        can_read = generic or subject in coerce_list(policy.get(read_key))
        can_write = generic or subject in coerce_list(policy.get(write_key))
        if can_read or can_write:
            result.append(
                {
                    "path": path,
                    "recursive": bool(policy.get("recursive", True)),
                    "read": can_read,
                    "write": can_write,
                }
            )
    return result


def _grant_value(grant: Any, key: str, default: Any = None) -> Any:
    if isinstance(grant, dict):
        return grant.get(key, default)
    return getattr(grant, key, default)


def replace_subject_file_grants(
    governance: dict[str, Any],
    *,
    subject: str,
    subject_kind: str,
    grants: Iterable[Any],
) -> None:
    """Replace one user/team's direct grants without disturbing other fields."""

    generic_key = "users" if subject_kind == "user" else "teams"
    read_key = "read_users" if subject_kind == "user" else "read_teams"
    write_key = "write_users" if subject_kind == "user" else "write_teams"
    policies = [
        normalize_folder_policy(policy)
        for policy in governance.get("folder_policies", []) or []
        if isinstance(policy, dict)
    ]

    for policy in policies:
        for key in (generic_key, read_key, write_key):
            values = [value for value in coerce_list(policy.get(key)) if value != subject]
            if values:
                policy[key] = values
            else:
                policy.pop(key, None)

    policy_indexes: dict[tuple[str, bool], int] = {}
    for index, policy in enumerate(policies):
        key = (
            str(policy.get("path") or "").strip(),
            bool(policy.get("recursive", True)),
        )
        policy_indexes.setdefault(key, index)

    seen_grants: set[tuple[str, bool]] = set()
    for grant in grants:
        path = str(_grant_value(grant, "path", "") or "").strip()
        recursive = bool(_grant_value(grant, "recursive", True))
        read = bool(_grant_value(grant, "read", False))
        write = bool(_grant_value(grant, "write", False))
        if not path:
            raise GovernanceAdminError("Every file access grant needs a path")
        if not read and not write:
            raise GovernanceAdminError(
                f"File access for {path} must grant read, write, or both"
            )
        key = (path, recursive)
        if key in seen_grants:
            raise GovernanceAdminError(f"Duplicate file access path: {path}")
        seen_grants.add(key)
        index = policy_indexes.get(key)
        if index is None:
            policies.append({"path": path, "recursive": recursive})
            index = len(policies) - 1
            policy_indexes[key] = index
        policy = policies[index]
        if read:
            policy[read_key] = sorted(set(coerce_list(policy.get(read_key))) | {subject})
        if write:
            policy[write_key] = sorted(
                set(coerce_list(policy.get(write_key))) | {subject}
            )

    governance["folder_policies"] = policies


def governance_team_payload(
    governance: dict[str, Any], name: str
) -> dict[str, Any]:
    users = governance.get("users")
    users = users if isinstance(users, dict) else {}
    members = [
        str(actor_key)
        for actor_key, record in users.items()
        if isinstance(record, dict)
        and name in coerce_list(record.get("teams") or record.get("team"))
    ]
    return {
        "name": name,
        "members": sorted(members, key=str.lower),
        "file_access": subject_file_grants(
            governance, subject=name, subject_kind="team"
        ),
        "delegated_root": team_root_entries(governance).get(name),
    }


def _safe_path(raw: Any) -> Optional[Path]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return Path(text).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def _path_is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return path == root


def _stable_actor_key(actor: Actor) -> str:
    platform = str(actor.platform or "").strip().lower()
    user_id = str(actor.user_id or "").strip()
    if not platform or not user_id or platform == "local":
        raise GovernanceAdminError(
            "Maia administration requires an authenticated gateway identity.",
            code="missing_gateway_identity",
        )
    return f"{platform}:{user_id}"


def _explicit_actor_record(governance: dict[str, Any], actor: Actor) -> dict[str, Any]:
    key = _stable_actor_key(actor)
    users = governance.get("users", {})
    if not isinstance(users, dict):
        users = {}
    raw = users.get(key)
    if raw is None:
        raw = users.get(str(actor.user_id or "").strip())
    if isinstance(raw, dict):
        record = dict(raw)
    elif isinstance(raw, (str, list, tuple, set)):
        record = {"roles": coerce_list(raw)}
    else:
        record = {}
    if not coerce_list(record.get("roles")):
        raise GovernanceAdminError(
            f"{key} has no explicit Governance role.", code="not_governed"
        )
    return record


def _role_hierarchy(governance: dict[str, Any]) -> list[str]:
    return coerce_list(governance.get("role_hierarchy")) or list(DEFAULT_ROLES)


def _actor_has_role(
    governance: dict[str, Any], actor_roles: list[str], required_roles: list[str]
) -> bool:
    return any(
        role_satisfies(governance, granted, required)
        for granted in actor_roles
        for required in required_roles
    )


def _admin_roles(full_config: dict[str, Any]) -> list[str]:
    dashboard = full_config.get("dashboard", {})
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    auth = dashboard.get("auth", {})
    auth = auth if isinstance(auth, dict) else {}
    return coerce_list(auth.get("admin_roles")) or ["admin"]


def _is_admin(
    full_config: dict[str, Any], governance: dict[str, Any], roles: list[str]
) -> bool:
    return _actor_has_role(governance, roles, _admin_roles(full_config))


def _actor_managed_roots(
    governance: dict[str, Any], actor: Actor, record: dict[str, Any]
) -> dict[str, Path]:
    actor_key = _stable_actor_key(actor)
    actor_keys = {actor_key, str(actor.user_id or "").strip()}
    actor_teams = set(coerce_list(record.get("teams") or record.get("team")))
    actor_roles = coerce_list(record.get("roles"))
    defaults = coerce_list(governance.get("team_file_manager_roles")) or [
        "manager",
        "admin",
    ]
    result: dict[str, Path] = {}
    for team, entry in team_root_entries(governance).items():
        root = _safe_path(entry.get("path"))
        if root is None:
            continue
        managers = set(coerce_list(entry.get("managers") or entry.get("manager_users")))
        if managers and actor_keys.intersection(managers):
            result[team] = root
            continue
        roles = coerce_list(entry.get("manager_roles")) or defaults
        if team in actor_teams and _actor_has_role(governance, actor_roles, roles):
            result[team] = root
    return result


def _gateway_env_key(platform: str) -> str:
    platform = str(platform or "").strip().lower()
    env_key = GATEWAY_ALLOWLIST_ENV.get(platform)
    if env_key:
        return env_key
    try:
        from gateway.platform_registry import platform_registry

        entry = platform_registry.get(platform)
        env_key = str(getattr(entry, "allowed_users_env", "") or "").strip()
    except Exception:
        env_key = ""
    if not env_key:
        raise GovernanceAdminError(
            f"Platform {platform!r} has no managed user allowlist.",
            code="unsupported_platform",
        )
    return env_key


def normalize_gateway_user_id(platform: str, value: Any) -> str:
    platform = str(platform or "").strip().lower()
    text = str(value or "").strip().strip("\"'").strip()
    prefix = f"{platform}:"
    if text.lower().startswith(prefix):
        text = text.split(":", 1)[1].strip()
    if platform == "discord":
        mention = re.fullmatch(r"<@!?(\d+)>", text)
        if mention:
            text = mention.group(1)
        if not re.fullmatch(r"\d+", text):
            return ""
    if not text or "," in text or any(ch.isspace() for ch in text):
        return ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return ""
    return text


def _set_gateway_admission(platform: str, user_id: str, admitted: bool) -> None:
    from hermes_cli.config import load_env, save_env_value

    env_key = _gateway_env_key(platform)
    current = []
    seen: set[str] = set()
    for raw in str(load_env().get(env_key) or "").split(","):
        normalized = normalize_gateway_user_id(platform, raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            current.append(normalized)
    if admitted and user_id not in seen:
        current.append(user_id)
    elif not admitted:
        current = [value for value in current if value != user_id]
    save_env_value(env_key, ",".join(current))


def _audit(
    event: str,
    *,
    actor: Actor,
    action: str,
    resource: str,
    outcome: str,
    reason: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    try:
        from agent.audit_log import record_audit_event

        record_audit_event(
            event,
            actor=actor,
            action=action,
            resource=resource,
            outcome=outcome,
            reason=reason or None,
            metadata=metadata or {},
        )
    except Exception:
        pass


def _load_full_config() -> dict[str, Any]:
    from hermes_cli.config import load_config

    config = load_config()
    return config if isinstance(config, dict) else {}


def _save_full_config(config: dict[str, Any]) -> None:
    from hermes_cli.config import save_config

    save_config(config)


def _known_admin_keys(
    full_config: dict[str, Any], governance: dict[str, Any]
) -> set[str]:
    result: set[str] = set()
    users = governance.get("users", {})
    users = users if isinstance(users, dict) else {}
    required = _admin_roles(full_config)
    for key, raw in users.items():
        roles = coerce_list(raw.get("roles") if isinstance(raw, dict) else raw)
        if _actor_has_role(governance, roles, required):
            result.add(str(key))
    return result


def _validate_roles(governance: dict[str, Any], raw_roles: Any) -> list[str]:
    roles = coerce_list(raw_roles)
    hierarchy = _role_hierarchy(governance)
    unknown = [role for role in roles if role not in hierarchy]
    if unknown:
        raise GovernanceAdminError(
            f"Unknown governance roles: {', '.join(unknown)}"
        )
    if not roles:
        raise GovernanceAdminError("At least one role is required")
    return roles


def _registered_team_name(governance: dict[str, Any], raw_name: str) -> Optional[str]:
    wanted = str(raw_name or "").strip().casefold()
    for name in governance_team_registry(governance):
        if name.casefold() == wanted:
            return name
    return None


def _validate_team_managed_policy(
    policy: dict[str, Any],
    *,
    managed_roots: dict[str, Path],
    allowed_user_keys: set[str],
) -> None:
    path = _safe_path(policy.get("path"))
    if path is None:
        raise GovernanceAdminError("Every folder policy needs a path")
    matching_teams = [
        team for team, root in managed_roots.items() if _path_is_under(path, root)
    ]
    if not matching_teams:
        raise GovernanceAdminError(
            f"Team managers can only edit policies under their delegated root: {policy.get('path')}",
            code="outside_delegated_root",
        )
    if any(policy.get(key) for key in ("roles", "read_roles", "write_roles")):
        raise GovernanceAdminError(
            "Team managers cannot grant role-wide folder access; use team or user grants.",
            code="role_grant_forbidden",
        )
    allowed_teams = set(matching_teams)
    for key in ("teams", "read_teams", "write_teams", "deny_teams"):
        requested = set(coerce_list(policy.get(key)))
        if requested and not requested.issubset(allowed_teams):
            raise GovernanceAdminError(
                f"{key} must stay inside the managed team root: {sorted(allowed_teams)}.",
                code="cross_team_forbidden",
            )
    for key in (
        "users",
        "read_users",
        "write_users",
        "deny_users",
        "write_approval_users",
    ):
        requested = set(coerce_list(policy.get(key)))
        if requested and not requested.issubset(allowed_user_keys):
            raise GovernanceAdminError(
                f"{key} can only reference users assigned to the managed team.",
                code="cross_team_forbidden",
            )
    if not any(
        coerce_list(policy.get(key))
        for key in (
            "teams",
            "read_teams",
            "write_teams",
            "users",
            "read_users",
            "write_users",
        )
    ):
        raise GovernanceAdminError(
            "Team-managed folder policies must grant at least one team or user."
        )


def _capabilities(
    full_config: dict[str, Any], governance: dict[str, Any], actor: Actor
) -> dict[str, Any]:
    record = _explicit_actor_record(governance, actor)
    roles = coerce_list(record.get("roles"))
    managed_roots = _actor_managed_roots(governance, actor, record)
    admin = _is_admin(full_config, governance, roles)
    return {
        "actor_key": _stable_actor_key(actor),
        "roles": roles,
        "teams": coerce_list(record.get("teams") or record.get("team")),
        "can_admin": admin,
        "managed_teams": sorted(managed_roots),
        "can_manage_delegated_files": bool(managed_roots),
    }


def _require_admin(
    full_config: dict[str, Any], governance: dict[str, Any], actor: Actor
) -> dict[str, Any]:
    record = _explicit_actor_record(governance, actor)
    if not _is_admin(full_config, governance, coerce_list(record.get("roles"))):
        raise GovernanceAdminError(
            "This action requires a system administrator role.",
            code="admin_required",
        )
    return record


def _visible_snapshot(
    full_config: dict[str, Any], governance: dict[str, Any], actor: Actor
) -> dict[str, Any]:
    caps = _capabilities(full_config, governance, actor)
    users = governance.get("users", {})
    users = users if isinstance(users, dict) else {}
    policies = [
        normalize_folder_policy(policy)
        for policy in governance.get("folder_policies", []) or []
        if isinstance(policy, dict)
    ]
    if caps["can_admin"]:
        visible_users = users
        visible_policies = policies
        teams = sorted(governance_team_registry(governance), key=str.lower)
    elif caps["managed_teams"]:
        managed = set(caps["managed_teams"])
        visible_users = {
            str(key): value
            for key, value in users.items()
            if isinstance(value, dict)
            and managed.intersection(
                coerce_list(value.get("teams") or value.get("team"))
            )
        }
        record = _explicit_actor_record(governance, actor)
        roots = _actor_managed_roots(governance, actor, record)
        visible_policies = [
            policy
            for policy in policies
            if (path := _safe_path(policy.get("path"))) is not None
            and any(_path_is_under(path, root) for root in roots.values())
        ]
        teams = sorted(managed, key=str.lower)
    else:
        key = caps["actor_key"]
        visible_users = {key: users.get(key, {})}
        visible_policies = []
        teams = list(caps["teams"])
    return {
        "capabilities": caps,
        "users": visible_users,
        "teams": teams,
        "folder_policies": visible_policies,
    }


def execute_governance_admin_action(
    action: str,
    payload: Optional[dict[str, Any]],
    *,
    actor: Actor,
) -> dict[str, Any]:
    """Execute one structured administration action for an authenticated actor."""

    action = str(action or "").strip().lower()
    data = dict(payload or {})
    resource = str(data.get("actor_key") or data.get("team") or data.get("path") or "governance")
    try:
        with _CONFIG_WRITE_LOCK:
            full_config = _load_full_config()
            governance = full_config.get("governance", {})
            governance = dict(governance) if isinstance(governance, dict) else {}
            if not bool(governance.get("enabled")):
                raise GovernanceAdminError(
                    "Governance must be enabled before Maia can administer itself through messages.",
                    code="governance_disabled",
                )

            # Every action, including read-only inspection, requires explicit
            # stable-ID membership.  A configured default_role is not authority.
            _explicit_actor_record(governance, actor)

            if action in {"inspect", "list"}:
                result = _visible_snapshot(full_config, governance, actor)
            elif action == "upsert_user":
                _require_admin(full_config, governance, actor)
                raw_key = str(data.get("actor_key") or "").strip()
                if ":" not in raw_key:
                    raise GovernanceAdminError(
                        "actor_key must use the stable platform:user_id form"
                    )
                platform, raw_user_id = raw_key.split(":", 1)
                platform = platform.strip().lower()
                user_id = normalize_gateway_user_id(platform, raw_user_id)
                if not user_id:
                    raise GovernanceAdminError("Invalid gateway user ID")
                key = f"{platform}:{user_id}"
                roles = _validate_roles(governance, data.get("roles"))
                teams = coerce_list(data.get("teams"))
                registry = governance_team_registry(governance)
                unknown = [team for team in teams if team not in registry]
                if unknown:
                    raise GovernanceAdminError(
                        f"Unknown governance teams: {', '.join(unknown)}"
                    )
                users = governance.get("users", {})
                users = dict(users) if isinstance(users, dict) else {}
                admins = _known_admin_keys(full_config, governance)
                if key in admins and len(admins) == 1 and not _actor_has_role(
                    governance, roles, _admin_roles(full_config)
                ):
                    raise GovernanceAdminError(
                        "Grant another administrator before removing the last admin role.",
                        code="last_admin",
                    )
                existing = users.get(key)
                record = dict(existing) if isinstance(existing, dict) else {}
                record["name"] = str(data.get("name") or record.get("name") or key).strip()
                record["roles"] = roles
                if teams:
                    record["teams"] = teams
                else:
                    record.pop("teams", None)
                    record.pop("team", None)
                users[key] = record
                governance["users"] = users
                if data.get("file_access") is not None:
                    replace_subject_file_grants(
                        governance,
                        subject=key,
                        subject_kind="user",
                        grants=data.get("file_access") or [],
                    )
                full_config["governance"] = governance
                _save_full_config(full_config)
                if bool(data.get("gateway_admission")):
                    _set_gateway_admission(platform, user_id, True)
                resource = key
                result = {
                    "actor_key": key,
                    "user": record,
                    "gateway_admitted": bool(data.get("gateway_admission")),
                    "file_access": subject_file_grants(
                        governance, subject=key, subject_kind="user"
                    ),
                }
            elif action == "remove_user":
                _require_admin(full_config, governance, actor)
                key = str(data.get("actor_key") or "").strip()
                users = governance.get("users", {})
                users = dict(users) if isinstance(users, dict) else {}
                admins = _known_admin_keys(full_config, governance)
                if key in admins and len(admins) == 1:
                    raise GovernanceAdminError(
                        "Grant another administrator before removing the last admin.",
                        code="last_admin",
                    )
                existed = key in users
                users.pop(key, None)
                governance["users"] = users
                replace_subject_file_grants(
                    governance, subject=key, subject_kind="user", grants=[]
                )
                full_config["governance"] = governance
                _save_full_config(full_config)
                gateway_removed = False
                if bool(data.get("gateway_admission")) and ":" in key:
                    platform, raw_user_id = key.split(":", 1)
                    user_id = normalize_gateway_user_id(platform, raw_user_id)
                    if user_id:
                        _set_gateway_admission(platform, user_id, False)
                        gateway_removed = True
                resource = key
                result = {
                    "actor_key": key,
                    "removed": existed,
                    "gateway_removed": gateway_removed,
                }
            elif action == "create_team":
                _require_admin(full_config, governance, actor)
                name = str(data.get("team") or data.get("name") or "").strip()
                if not re.fullmatch(r"[^\s,][^,\r\n]{0,63}", name):
                    raise GovernanceAdminError(
                        "Team names must be 1-64 characters and cannot contain commas or line breaks"
                    )
                if _registered_team_name(governance, name):
                    raise GovernanceAdminError(
                        f"Team already exists: {name}", code="already_exists"
                    )
                registry = governance_team_registry(governance)
                registry[name] = {}
                governance["teams"] = registry
                full_config["governance"] = governance
                _save_full_config(full_config)
                resource = name
                result = {"team": governance_team_payload(governance, name)}
            elif action == "update_team":
                _require_admin(full_config, governance, actor)
                requested_name = str(data.get("team") or "").strip()
                name = _registered_team_name(governance, requested_name)
                if not name:
                    raise GovernanceAdminError(
                        f"Unknown governance team: {requested_name}", code="not_found"
                    )
                users = governance.get("users", {})
                users = dict(users) if isinstance(users, dict) else {}
                if "members" in data:
                    requested_members = set(coerce_list(data.get("members")))
                    unknown_members = sorted(requested_members - set(map(str, users)))
                    if unknown_members:
                        raise GovernanceAdminError(
                            "Team members must already be governed identities: "
                            + ", ".join(unknown_members)
                        )
                    for actor_key, raw_record in list(users.items()):
                        record = (
                            dict(raw_record)
                            if isinstance(raw_record, dict)
                            else {"roles": raw_record}
                        )
                        teams = [
                            team
                            for team in coerce_list(
                                record.get("teams") or record.get("team")
                            )
                            if team.casefold() != name.casefold()
                        ]
                        if str(actor_key) in requested_members:
                            teams.append(name)
                        if teams:
                            record["teams"] = teams
                        else:
                            record.pop("teams", None)
                            record.pop("team", None)
                        users[actor_key] = record
                    governance["users"] = users
                if data.get("file_access") is not None:
                    replace_subject_file_grants(
                        governance,
                        subject=name,
                        subject_kind="team",
                        grants=data.get("file_access") or [],
                    )
                if "delegated_root" in data:
                    roots = team_root_entries(governance)
                    delegated = data.get("delegated_root")
                    if delegated is None:
                        roots.pop(name, None)
                    elif isinstance(delegated, dict):
                        path = str(delegated.get("path") or "").strip()
                        if not path:
                            raise GovernanceAdminError(
                                "A delegated team root needs a server path"
                            )
                        entry: dict[str, Any] = {"path": path}
                        manager_roles = coerce_list(delegated.get("manager_roles"))
                        if manager_roles:
                            unknown_roles = [
                                role
                                for role in manager_roles
                                if role not in _role_hierarchy(governance)
                            ]
                            if unknown_roles:
                                raise GovernanceAdminError(
                                    "Unknown manager roles: " + ", ".join(unknown_roles)
                                )
                            entry["manager_roles"] = manager_roles
                        managers = coerce_list(
                            delegated.get("managers")
                            or delegated.get("manager_users")
                        )
                        unknown_managers = sorted(set(managers) - set(map(str, users)))
                        if unknown_managers:
                            raise GovernanceAdminError(
                                "Root managers must be governed identities: "
                                + ", ".join(unknown_managers)
                            )
                        if managers:
                            entry["managers"] = managers
                        roots[name] = entry
                    else:
                        raise GovernanceAdminError("delegated_root must be an object or null")
                    governance["team_file_roots"] = roots
                governance["teams"] = governance_team_registry(governance)
                full_config["governance"] = governance
                _save_full_config(full_config)
                resource = name
                result = {"team": governance_team_payload(governance, name)}
            elif action == "delete_team":
                _require_admin(full_config, governance, actor)
                requested_name = str(data.get("team") or "").strip()
                name = _registered_team_name(governance, requested_name)
                if not name:
                    raise GovernanceAdminError(
                        f"Unknown governance team: {requested_name}", code="not_found"
                    )
                team = governance_team_payload(governance, name)
                references = []
                if team["members"]:
                    references.append(f"{len(team['members'])} member(s)")
                if team["file_access"]:
                    references.append(f"{len(team['file_access'])} file grant(s)")
                if team["delegated_root"]:
                    references.append("a delegated root")
                referenced_policies = sum(
                    1
                    for policy in governance.get("folder_policies", []) or []
                    if isinstance(policy, dict)
                    and any(
                        name in coerce_list(policy.get(key))
                        for key in (
                            "teams",
                            "read_teams",
                            "write_teams",
                            "deny_teams",
                        )
                    )
                )
                if referenced_policies and not team["file_access"]:
                    references.append(f"{referenced_policies} policy reference(s)")
                if references:
                    raise GovernanceAdminError(
                        f"Remove {', '.join(references)} before deleting team {name}",
                        code="still_referenced",
                    )
                registry = governance_team_registry(governance)
                registry.pop(name, None)
                governance["teams"] = registry
                full_config["governance"] = governance
                _save_full_config(full_config)
                resource = name
                result = {"removed": name}
            elif action in {"set_file_policy", "remove_file_policy"}:
                record = _explicit_actor_record(governance, actor)
                roles = coerce_list(record.get("roles"))
                admin = _is_admin(full_config, governance, roles)
                roots = _actor_managed_roots(governance, actor, record)
                if not admin and not roots:
                    raise GovernanceAdminError(
                        "No delegated team file root is available to this actor.",
                        code="file_manager_required",
                    )
                path = str(data.get("path") or "").strip()
                recursive = bool(data.get("recursive", True))
                if not path:
                    raise GovernanceAdminError("A folder policy path is required")
                policies = [
                    normalize_folder_policy(policy)
                    for policy in governance.get("folder_policies", []) or []
                    if isinstance(policy, dict)
                ]
                match_key = (path, recursive)
                if action == "remove_file_policy":
                    existing = next(
                        (
                            policy
                            for policy in policies
                            if (
                                str(policy.get("path") or "").strip(),
                                bool(policy.get("recursive", True)),
                            )
                            == match_key
                        ),
                        None,
                    )
                    if existing is None:
                        raise GovernanceAdminError(
                            f"Folder policy not found: {path}", code="not_found"
                        )
                    if not admin:
                        actor_team_users = {
                            str(key)
                            for key, raw in (governance.get("users", {}) or {}).items()
                            if isinstance(raw, dict)
                            and set(roots).intersection(
                                coerce_list(raw.get("teams") or raw.get("team"))
                            )
                        }
                        _validate_team_managed_policy(
                            existing,
                            managed_roots=roots,
                            allowed_user_keys=actor_team_users,
                        )
                    policies.remove(existing)
                    result = {"removed": path}
                else:
                    policy = normalize_folder_policy(
                        dict(data.get("policy") or {}, path=path, recursive=recursive)
                    )
                    registered_teams = set(governance_team_registry(governance))
                    for key in ("teams", "read_teams", "write_teams", "deny_teams"):
                        unknown = sorted(
                            set(coerce_list(policy.get(key))) - registered_teams
                        )
                        if unknown:
                            raise GovernanceAdminError(
                                f"Unknown governance teams in {key}: {', '.join(unknown)}"
                            )
                    hierarchy = set(_role_hierarchy(governance))
                    for key in (
                        "roles",
                        "read_roles",
                        "write_roles",
                        "write_approval_roles",
                    ):
                        unknown = sorted(set(coerce_list(policy.get(key))) - hierarchy)
                        if unknown:
                            raise GovernanceAdminError(
                                f"Unknown governance roles in {key}: {', '.join(unknown)}"
                            )
                    governed_users = set(map(str, (governance.get("users", {}) or {})))
                    for key in (
                        "users",
                        "read_users",
                        "write_users",
                        "deny_users",
                        "write_approval_users",
                    ):
                        unknown = sorted(
                            set(coerce_list(policy.get(key))) - governed_users
                        )
                        if unknown:
                            raise GovernanceAdminError(
                                f"Unknown governed users in {key}: {', '.join(unknown)}"
                            )
                    if not admin:
                        actor_team_users = {
                            str(key)
                            for key, raw in (governance.get("users", {}) or {}).items()
                            if isinstance(raw, dict)
                            and set(roots).intersection(
                                coerce_list(raw.get("teams") or raw.get("team"))
                            )
                        }
                        _validate_team_managed_policy(
                            policy,
                            managed_roots=roots,
                            allowed_user_keys=actor_team_users,
                        )
                    replaced = False
                    for index, existing in enumerate(policies):
                        if (
                            str(existing.get("path") or "").strip(),
                            bool(existing.get("recursive", True)),
                        ) == match_key:
                            policies[index] = policy
                            replaced = True
                            break
                    if not replaced:
                        policies.append(policy)
                    result = {"policy": policy, "replaced": replaced}
                governance["folder_policies"] = policies
                full_config["governance"] = governance
                _save_full_config(full_config)
                resource = path
            else:
                raise GovernanceAdminError(
                    f"Unknown Maia administration action: {action}",
                    code="unknown_action",
                )

        _audit(
            "governance.agent_admin",
            actor=actor,
            action=f"maia_admin.{action}",
            resource=resource,
            outcome="success",
            metadata={"surface": "gateway"},
        )
        return {"success": True, "action": action, **result}
    except GovernanceAdminError as exc:
        _audit(
            "governance.agent_admin",
            actor=actor,
            action=f"maia_admin.{action or 'unknown'}",
            resource=resource,
            outcome="denied",
            reason=str(exc),
            metadata={"surface": "gateway", "code": exc.code},
        )
        raise

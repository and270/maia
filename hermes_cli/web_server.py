"""
Maia web UI server.

Provides a FastAPI backend serving the Vite/React frontend and REST API
endpoints for managing configuration, environment variables, and sessions.

Usage:
    python -m hermes_cli.main web          # Start on http://127.0.0.1:9119
    python -m hermes_cli.main web --port 8080
"""

import asyncio
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hermes_cli import __version__, __release_date__
from hermes_cli.config import (
    cfg_get,
    DEFAULT_CONFIG,
    OPTIONAL_ENV_VARS,
    get_config_path,
    get_env_path,
    get_hermes_home,
    load_config,
    load_env,
    save_config,
    save_env_value,
    remove_env_value,
    check_config_version,
    redact_key,
)
from gateway.status import get_running_pid, read_runtime_status

try:
    from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError:
    raise SystemExit(
        "Web UI requires fastapi and uvicorn.\n"
        f"Install with: {sys.executable} -m pip install 'fastapi' 'uvicorn[standard]'"
    )

WEB_DIST = Path(os.environ["HERMES_WEB_DIST"]) if "HERMES_WEB_DIST" in os.environ else Path(__file__).parent / "web_dist"
_log = logging.getLogger(__name__)

app = FastAPI(title="Maia", version=__version__)

# ---------------------------------------------------------------------------
# Dashboard authentication.
#
# Default local mode stays backward compatible: a per-process token is injected
# into localhost-served HTML. Corporate/protected mode is enabled through
# dashboard.auth in config.yaml and issues per-user dashboard sessions from an
# admin token or trusted reverse-proxy identity headers.
# ---------------------------------------------------------------------------
_SESSION_TOKEN = secrets.token_urlsafe(32)
_SESSION_HEADER_NAME = "X-Hermes-Session-Token"
_DASHBOARD_SESSION_STORAGE_KEY = "maiaHermes.dashboardSessionToken"


@dataclass(frozen=True)
class DashboardSession:
    token: str
    actor: Any
    roles: List[str]
    expires_at: float
    source: str


_DASHBOARD_AUTH_SESSIONS: Dict[str, DashboardSession] = {}

# In-browser Chat tab (/chat, /api/pty, …).  Off unless ``hermes dashboard --tui``
# or HERMES_DASHBOARD_TUI=1.  Set from :func:`start_server`.
_DASHBOARD_EMBEDDED_CHAT_ENABLED = False

# Simple rate limiter for the reveal endpoint
_reveal_timestamps: List[float] = []
_REVEAL_MAX_PER_WINDOW = 5
_REVEAL_WINDOW_SECONDS = 30

# CORS: restrict to localhost origins only.  The web UI is intended to run
# locally; binding to 0.0.0.0 with allow_origins=["*"] would let any website
# read/modify config and secrets.

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Endpoints that do NOT require the session token.  Everything else under
# /api/ is gated by the auth middleware below.  Keep this list minimal —
# only truly non-sensitive, read-only endpoints belong here.
# ---------------------------------------------------------------------------
_PUBLIC_API_PATHS: frozenset = frozenset({
    "/api/status",
    "/api/config/defaults",
    "/api/config/schema",
    "/api/model/info",
    "/api/dashboard/themes",
    "/api/dashboard/plugins",
    "/api/dashboard/plugins/rescan",
    "/api/dashboard/auth/status",
    "/api/dashboard/auth/login",
})


def _is_public_api_path(path: str) -> bool:
    if path in {"/api/dashboard/auth/status", "/api/dashboard/auth/login"}:
        return True
    if _dashboard_auth_enabled():
        return path == "/api/status"
    return path in _PUBLIC_API_PATHS or path.startswith("/api/plugins/")


def _coerce_role_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _dashboard_auth_config() -> Dict[str, Any]:
    defaults = (
        DEFAULT_CONFIG.get("dashboard", {})
        .get("auth", {})
        if isinstance(DEFAULT_CONFIG.get("dashboard"), dict)
        else {}
    )
    merged: Dict[str, Any] = dict(defaults) if isinstance(defaults, dict) else {}
    try:
        cfg = load_config()
    except Exception:
        cfg = {}
    dashboard = cfg.get("dashboard", {}) if isinstance(cfg, dict) else {}
    auth = dashboard.get("auth", {}) if isinstance(dashboard, dict) else {}
    if isinstance(auth, dict):
        merged.update(auth)
    return merged


def _dashboard_auth_enabled(auth_config: Optional[Dict[str, Any]] = None) -> bool:
    cfg = _dashboard_auth_config() if auth_config is None else auth_config
    return bool(cfg.get("enabled"))


def _dashboard_env_token(auth_config: Optional[Dict[str, Any]] = None) -> str:
    cfg = _dashboard_auth_config() if auth_config is None else auth_config
    token_env = str(cfg.get("token_env") or "MAIA_DASHBOARD_TOKEN").strip()
    return os.getenv(token_env, "").strip() if token_env else ""


def _dashboard_has_token_secret(auth_config: Optional[Dict[str, Any]] = None) -> bool:
    cfg = _dashboard_auth_config() if auth_config is None else auth_config
    env_token = _dashboard_env_token(cfg)
    return bool((env_token and len(env_token) >= 16) or str(cfg.get("token_hash") or "").strip())


def _dashboard_has_trusted_headers(auth_config: Optional[Dict[str, Any]] = None) -> bool:
    cfg = _dashboard_auth_config() if auth_config is None else auth_config
    return bool(str(cfg.get("trusted_user_header") or "").strip())


def _dashboard_channel_tokens_config(auth_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = _dashboard_auth_config() if auth_config is None else auth_config
    raw = cfg.get("channel_tokens", {}) if isinstance(cfg, dict) else {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bool):
        return {"enabled": raw}
    return {}


def _dashboard_channel_tokens_enabled(auth_config: Optional[Dict[str, Any]] = None) -> bool:
    cfg = _dashboard_channel_tokens_config(auth_config)
    return bool(cfg.get("enabled", True))


def _dashboard_trusted_headers_allowed(
    auth_config: Optional[Dict[str, Any]] = None,
) -> bool:
    cfg = _dashboard_auth_config() if auth_config is None else auth_config
    if not _dashboard_has_trusted_headers(cfg):
        return False
    bound_host = getattr(app.state, "bound_host", "127.0.0.1")
    if bound_host in ("127.0.0.1", "localhost", "::1"):
        return True
    return bool(cfg.get("allow_trusted_headers_on_public_bind"))


def _dashboard_auth_configured_for_bind(
    host: str,
    auth_config: Optional[Dict[str, Any]] = None,
) -> bool:
    cfg = _dashboard_auth_config() if auth_config is None else auth_config
    if not _dashboard_auth_enabled(cfg):
        return False
    if _dashboard_has_token_secret(cfg):
        return True
    if _dashboard_channel_tokens_enabled(cfg):
        return True
    if not _dashboard_has_trusted_headers(cfg):
        return False
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    return bool(cfg.get("allow_trusted_headers_on_public_bind"))


def _verify_dashboard_token_hash(raw_token: str, token_hash: str) -> bool:
    value = str(token_hash or "").strip()
    if not raw_token or not value:
        return False
    if value.startswith("sha256:"):
        value = value.split(":", 1)[1].strip()
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest.encode(), value.encode())


def _verify_local_dashboard_login(raw_token: str, auth_config: Dict[str, Any]) -> bool:
    if not raw_token:
        return False
    env_token = _dashboard_env_token(auth_config)
    if env_token:
        if len(env_token) < 16:
            _log.warning("Ignoring dashboard token from env because it is shorter than 16 characters.")
        elif hmac.compare_digest(raw_token.encode(), env_token.encode()):
            return True
    return _verify_dashboard_token_hash(raw_token, str(auth_config.get("token_hash") or ""))


def _consume_channel_dashboard_login(raw_token: str, auth_config: Dict[str, Any]) -> Optional[DashboardSession]:
    if not _dashboard_channel_tokens_enabled(auth_config):
        return None
    try:
        from hermes_cli.dashboard_tokens import (
            actor_from_payload,
            consume_channel_dashboard_token,
            is_dashboard_actor_revoked,
        )
    except Exception:
        return None

    record = consume_channel_dashboard_token(raw_token)
    if not record:
        return None
    actor_payload = record.get("actor", {})
    if not isinstance(actor_payload, dict):
        return None
    actor = actor_from_payload(actor_payload)
    if is_dashboard_actor_revoked(actor):
        return None
    roles = _dashboard_roles_for_actor(
        actor,
        fallback_roles=_coerce_role_list(record.get("roles")),
    )
    if not _dashboard_roles_allow(roles, _coerce_role_list(auth_config.get("read_roles"))):
        return None
    return _issue_dashboard_session(actor, roles, "channel_token")


def _dashboard_governance_config() -> Dict[str, Any]:
    try:
        from agent.governance import load_governance_config

        cfg = load_governance_config()
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    if not cfg.get("role_hierarchy"):
        cfg = dict(cfg)
        cfg["role_hierarchy"] = DEFAULT_CONFIG.get("governance", {}).get(
            "role_hierarchy",
            ["viewer", "operator", "manager", "admin"],
        )
    return cfg


def _governance_has_user_record(actor: Any, governance_config: Dict[str, Any]) -> bool:
    users = governance_config.get("users", {})
    if not isinstance(users, dict):
        return False
    for key in getattr(actor, "keys", ()):
        if key in users:
            return True
    return False


def _dashboard_roles_for_actor(
    actor: Any,
    *,
    explicit_roles: Optional[List[str]] = None,
    fallback_roles: Optional[List[str]] = None,
) -> List[str]:
    explicit = _coerce_role_list(explicit_roles)
    fallback = _coerce_role_list(fallback_roles)
    governance_cfg = _dashboard_governance_config()
    roles: List[str] = []
    try:
        from agent.governance import actor_roles

        if _governance_has_user_record(actor, governance_cfg):
            roles.extend(actor_roles(actor, governance_cfg))
    except Exception:
        pass
    roles.extend(explicit)
    if not roles:
        roles.extend(fallback)
    return list(dict.fromkeys(role for role in roles if role))


def _dashboard_roles_allow(
    granted_roles: List[str],
    required_roles: List[str],
    governance_config: Optional[Dict[str, Any]] = None,
) -> bool:
    required = _coerce_role_list(required_roles)
    if not required:
        return True
    granted = _coerce_role_list(granted_roles)
    if not granted:
        return False
    cfg = _dashboard_governance_config() if governance_config is None else governance_config
    try:
        from agent.governance import role_satisfies
    except Exception:
        role_satisfies = None

    for granted_role in granted:
        for required_role in required:
            if granted_role == required_role:
                return True
            if role_satisfies and role_satisfies(cfg, granted_role, required_role):
                return True
    return False


def _dashboard_session_ttl(auth_config: Dict[str, Any]) -> float:
    try:
        minutes = float(auth_config.get("session_ttl_minutes") or 480)
    except (TypeError, ValueError):
        minutes = 480
    return max(1.0, minutes) * 60.0


def _prune_dashboard_sessions(now: Optional[float] = None) -> None:
    current = time.time() if now is None else now
    expired = [
        token
        for token, session in _DASHBOARD_AUTH_SESSIONS.items()
        if session.expires_at <= current
    ]
    for token in expired:
        _DASHBOARD_AUTH_SESSIONS.pop(token, None)


def _dashboard_actor_key(actor: Any) -> str:
    try:
        from hermes_cli.dashboard_tokens import actor_key

        return actor_key(actor)
    except Exception:
        pass
    keys = list(getattr(actor, "keys", ()) or [])
    if keys:
        return str(keys[0])
    return str(actor)


def _dashboard_actor_is_revoked(actor: Any) -> bool:
    try:
        from hermes_cli.dashboard_tokens import is_dashboard_actor_revoked

        return is_dashboard_actor_revoked(actor)
    except Exception:
        return False


def _drop_dashboard_sessions_for_actor_key(actor_key: str) -> int:
    key = str(actor_key or "").strip()
    if not key:
        return 0
    dropped = 0
    for token, session in list(_DASHBOARD_AUTH_SESSIONS.items()):
        keys = set(getattr(session.actor, "keys", ()) or [])
        keys.add(_dashboard_actor_key(session.actor))
        if key in keys:
            _DASHBOARD_AUTH_SESSIONS.pop(token, None)
            dropped += 1
    return dropped


def _issue_dashboard_session(actor: Any, roles: List[str], source: str) -> DashboardSession:
    auth_config = _dashboard_auth_config()
    token = secrets.token_urlsafe(32)
    session_roles = list(dict.fromkeys(roles))
    try:
        from agent.governance import Actor

        if isinstance(actor, Actor):
            actor = Actor(
                platform=actor.platform,
                user_id=actor.user_id,
                user_name=actor.user_name,
                roles=tuple(session_roles),
            )
    except Exception:
        pass
    session = DashboardSession(
        token=token,
        actor=actor,
        roles=session_roles,
        expires_at=time.time() + _dashboard_session_ttl(auth_config),
        source=source,
    )
    _DASHBOARD_AUTH_SESSIONS[token] = session
    return session


def _session_from_dashboard_token(token: str) -> Optional[DashboardSession]:
    if not token:
        return None
    _prune_dashboard_sessions()
    session = _DASHBOARD_AUTH_SESSIONS.get(token)
    if session:
        if _dashboard_actor_is_revoked(session.actor):
            _DASHBOARD_AUTH_SESSIONS.pop(token, None)
            return None
        return session
    if not _dashboard_auth_enabled() and hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        try:
            from agent.governance import current_actor

            actor = current_actor()
        except Exception:
            actor = "local"
        return DashboardSession(
            token=_SESSION_TOKEN,
            actor=actor,
            roles=["admin"],
            expires_at=time.time() + 60,
            source="local_ephemeral",
        )
    return None


def _dashboard_session_from_request(request: Request) -> Optional[DashboardSession]:
    session_header = request.headers.get(_SESSION_HEADER_NAME, "").strip()
    if session_header:
        session = _session_from_dashboard_token(session_header)
        if session:
            request.state.dashboard_session = session
            return session

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        session = _session_from_dashboard_token(token)
        if session:
            request.state.dashboard_session = session
            return session
    return None


def _request_dashboard_session(request: Request) -> Optional[DashboardSession]:
    existing = getattr(request.state, "dashboard_session", None)
    if existing:
        return existing
    return _dashboard_session_from_request(request)


def _request_dashboard_actor(request: Request) -> Any:
    session = _request_dashboard_session(request)
    if session:
        return session.actor
    try:
        from agent.governance import current_actor

        return current_actor()
    except Exception:
        return "local"


def _dashboard_governance_config_for_request(request: Request) -> Dict[str, Any]:
    cfg = _dashboard_governance_config()
    session = _request_dashboard_session(request)
    if not session:
        return cfg
    actor = session.actor
    users = dict(cfg.get("users", {}) if isinstance(cfg.get("users"), dict) else {})
    actor_keys = list(getattr(actor, "keys", ()) or [])
    if actor_keys:
        users[actor_keys[0]] = {
            "roles": session.roles,
            "name": getattr(actor, "user_name", None) or actor_keys[0],
        }
    cfg = dict(cfg)
    cfg["users"] = users
    return cfg


def _dashboard_session_payload(session: DashboardSession) -> Dict[str, Any]:
    try:
        from agent.governance import actor_display

        actor_id = actor_display(session.actor)
    except Exception:
        actor_id = str(session.actor)
    return {
        "token": session.token,
        "actor": {
            "id": actor_id,
            "platform": getattr(session.actor, "platform", None),
            "user_id": getattr(session.actor, "user_id", None),
            "user_name": getattr(session.actor, "user_name", None),
        },
        "roles": session.roles,
        "source": session.source,
        "expires_at": session.expires_at,
        "capabilities": _dashboard_capabilities(session.roles),
    }


def _dashboard_capabilities(roles: List[str]) -> Dict[str, bool]:
    auth_config = _dashboard_auth_config()
    return {
        "read": _dashboard_roles_allow(roles, _coerce_role_list(auth_config.get("read_roles"))),
        "manage": _dashboard_roles_allow(roles, _coerce_role_list(auth_config.get("manage_roles"))),
        "admin": _dashboard_roles_allow(roles, _coerce_role_list(auth_config.get("admin_roles"))),
    }


def _dashboard_actor_is_admin(request: Request) -> bool:
    session = _request_dashboard_session(request)
    if not session:
        return False
    auth_config = _dashboard_auth_config()
    return _dashboard_roles_allow(session.roles, _coerce_role_list(auth_config.get("admin_roles")))


def _safe_policy_path(raw: Any) -> Optional[Path]:
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


def _dashboard_actor_teams(request: Request, config: Dict[str, Any]) -> List[str]:
    try:
        from agent.governance import actor_teams

        return actor_teams(_request_dashboard_actor(request), config)
    except Exception:
        return []


def _governance_user_keys_by_team(config: Dict[str, Any], teams: List[str]) -> set[str]:
    wanted = set(_coerce_role_list(teams))
    if not wanted:
        return set()
    users = config.get("users", {})
    if not isinstance(users, dict):
        return set()
    allowed: set[str] = set()
    for key, record in users.items():
        if not isinstance(record, dict):
            continue
        user_teams = set(_coerce_role_list(record.get("teams") or record.get("team")))
        if user_teams.intersection(wanted):
            allowed.add(str(key))
    return allowed


def _team_root_entries(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = config.get("team_file_roots", {})
    if not isinstance(raw, dict):
        return {}
    entries: Dict[str, Dict[str, Any]] = {}
    for team, value in raw.items():
        if isinstance(value, str):
            entries[str(team)] = {"path": value}
        elif isinstance(value, dict):
            entries[str(team)] = dict(value)
    return entries


def _manageable_team_roots(request: Request, config: Dict[str, Any]) -> Dict[str, Path]:
    actor = _request_dashboard_actor(request)
    actor_keys = set(getattr(actor, "keys", ()) or [])
    actor_team_set = set(_dashboard_actor_teams(request, config))
    result: Dict[str, Path] = {}
    try:
        from agent.governance import actor_has_any_role
    except Exception:
        actor_has_any_role = None

    default_roles = _coerce_role_list(config.get("team_file_manager_roles")) or ["manager", "admin"]
    for team, entry in _team_root_entries(config).items():
        root = _safe_policy_path(entry.get("path"))
        if root is None:
            continue
        managers = set(_coerce_role_list(entry.get("managers") or entry.get("manager_users")))
        if managers and actor_keys.intersection(managers):
            result[team] = root
            continue
        roles = _coerce_role_list(entry.get("manager_roles")) or default_roles
        if team in actor_team_set and actor_has_any_role and actor_has_any_role(
            roles,
            actor=actor,
            config=config,
        ):
            result[team] = root
    return result


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

# Keys where a PRESENT-but-empty list is meaningful and must survive
# normalisation: an explicit empty write-approval list on a child policy opts
# its subtree out of an ancestor's staged-approval requirement (see
# agent.governance.file_write_approval_requirement).
_FOLDER_POLICY_KEEP_EMPTY_KEYS = frozenset(
    ("write_approval_roles", "write_approval_users")
)


def _normalise_folder_policy(raw: Dict[str, Any]) -> Dict[str, Any]:
    policy: Dict[str, Any] = {}
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
        values = _coerce_role_list(raw.get(key))
        if values:
            policy[key] = values
        elif (
            key in _FOLDER_POLICY_KEEP_EMPTY_KEYS
            and isinstance(raw.get(key), (list, tuple))
        ):
            policy[key] = []
    return policy


def _policy_matches_any_team_root(policy: Dict[str, Any], roots: Dict[str, Path]) -> bool:
    path = _safe_policy_path(policy.get("path"))
    if path is None:
        return False
    return any(_path_is_under(path, root) for root in roots.values())


def _validate_team_managed_policy(
    policy: Dict[str, Any],
    *,
    managed_roots: Dict[str, Path],
    allowed_user_keys: set[str],
) -> None:
    path = _safe_policy_path(policy.get("path"))
    if path is None:
        raise HTTPException(status_code=400, detail="Every folder policy needs a path.")
    matching_teams = [
        team for team, root in managed_roots.items()
        if _path_is_under(path, root)
    ]
    if not matching_teams:
        raise HTTPException(
            status_code=403,
            detail=f"Team managers can only edit policies under their configured team root. Rejected: {policy.get('path')}",
        )

    role_keys = {"roles", "read_roles", "write_roles"}
    if any(policy.get(key) for key in role_keys):
        raise HTTPException(
            status_code=403,
            detail="Team managers cannot grant role-wide folder access; use team or user grants.",
        )

    allowed_teams = set(matching_teams)
    for key in ("teams", "read_teams", "write_teams", "deny_teams"):
        requested = set(_coerce_role_list(policy.get(key)))
        if requested and not requested.issubset(allowed_teams):
            raise HTTPException(
                status_code=403,
                detail=f"{key} must stay inside the managed team root: {sorted(allowed_teams)}.",
            )

    for key in ("users", "read_users", "write_users", "deny_users", "write_approval_users"):
        requested_users = set(_coerce_role_list(policy.get(key)))
        if requested_users and not requested_users.issubset(allowed_user_keys):
            raise HTTPException(
                status_code=403,
                detail=f"{key} can only reference users assigned to the managed team.",
            )

    has_grant = any(
        _coerce_role_list(policy.get(key))
        for key in ("teams", "read_teams", "write_teams", "users", "read_users", "write_users")
    )
    if not has_grant:
        raise HTTPException(
            status_code=400,
            detail="Team-managed folder policies must grant at least one team or user.",
        )


def _trusted_dashboard_session_from_request(request: Request) -> Optional[DashboardSession]:
    auth_config = _dashboard_auth_config()
    if not _dashboard_auth_enabled(auth_config):
        return None
    if not _dashboard_trusted_headers_allowed(auth_config):
        return None
    user_header = str(auth_config.get("trusted_user_header") or "").strip()
    user_id = request.headers.get(user_header, "").strip() if user_header else ""
    if not user_id:
        return None
    name_header = str(auth_config.get("trusted_name_header") or "").strip()
    roles_header = str(auth_config.get("trusted_roles_header") or "").strip()
    user_name = request.headers.get(name_header, "").strip() if name_header else user_id
    explicit_roles = _coerce_role_list(request.headers.get(roles_header, "")) if roles_header else []
    try:
        from agent.governance import Actor

        actor = Actor(
            platform=str(auth_config.get("trusted_platform") or "sso").strip() or "sso",
            user_id=user_id,
            user_name=user_name,
        )
    except Exception:
        actor = user_id
    if _dashboard_actor_is_revoked(actor):
        return None
    roles = _dashboard_roles_for_actor(actor, explicit_roles=explicit_roles)
    if not _dashboard_roles_allow(roles, _coerce_role_list(auth_config.get("read_roles"))):
        return None
    return _issue_dashboard_session(actor, roles, "trusted_header")


def _dashboard_required_roles(path: str, method: str) -> List[str]:
    auth_config = _dashboard_auth_config()
    admin_roles = _coerce_role_list(auth_config.get("admin_roles"))
    manage_roles = _coerce_role_list(auth_config.get("manage_roles")) or admin_roles
    read_roles = _coerce_role_list(auth_config.get("read_roles")) or manage_roles
    verb = method.upper()

    if path == "/api/dashboard/auth/logout":
        return []
    if path.startswith("/api/dashboard/access"):
        return admin_roles
    if path.startswith("/api/governance/folder-policies"):
        return manage_roles
    if path.startswith("/api/knowledge/approvals/") and path.endswith("/decide"):
        return manage_roles
    if path.startswith("/api/files/approvals/") and path.endswith("/decide"):
        return manage_roles
    if path.startswith("/api/cron/jobs/") and path.endswith("/authorize"):
        return manage_roles
    if verb in {"GET", "HEAD", "OPTIONS"}:
        if path == "/api/config":
            return read_roles
        read_prefixes = (
            "/api/status",
            "/api/sessions",
            "/api/logs",
            "/api/analytics",
            "/api/model",
            "/api/knowledge",
            "/api/files/approvals",
            "/api/cron/jobs",
            "/api/dashboard/themes",
            "/api/dashboard/plugins",
            "/api/plugins",
        )
        if path.startswith(read_prefixes):
            return read_roles
    return admin_roles


def _audit_dashboard_event(
    event_type: str,
    *,
    request: Optional[Request] = None,
    actor: Optional[Any] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    outcome: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        from agent.audit_log import record_audit_event

        who = actor if actor is not None else (_request_dashboard_actor(request) if request else None)
        meta = dict(metadata or {})
        if request is not None:
            meta.setdefault("client", request.client.host if request.client else None)
            meta.setdefault("path", request.url.path)
            meta.setdefault("method", request.method)
        record_audit_event(
            event_type,
            actor=who,
            action=action,
            resource=resource,
            outcome=outcome,
            reason=reason,
            metadata=meta,
        )
    except Exception:
        pass


def _has_valid_session_token(request: Request) -> bool:
    """True if the request carries a valid dashboard session token.

    The dedicated session header avoids collisions with reverse proxies that
    already use ``Authorization`` (for example Caddy ``basic_auth``). We still
    accept the legacy Bearer path for backward compatibility with older
    dashboard bundles.
    """
    return _dashboard_session_from_request(request) is not None


def _require_token(request: Request) -> None:
    """Validate the ephemeral session token.  Raises 401 on mismatch."""
    if not _has_valid_session_token(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


# Accepted Host header values for loopback binds. DNS rebinding attacks
# point a victim browser at an attacker-controlled hostname (evil.test)
# which resolves to 127.0.0.1 after a TTL flip — bypassing same-origin
# checks because the browser now considers evil.test and our dashboard
# "same origin". Validating the Host header at the app layer rejects any
# request whose Host isn't one we bound for. See GHSA-ppp5-vxwm-4cf7.
_LOOPBACK_HOST_VALUES: frozenset = frozenset({
    "localhost", "127.0.0.1", "::1",
})


def _is_accepted_host(host_header: str, bound_host: str) -> bool:
    """True if the Host header targets the interface we bound to.

    Accepts:
    - Exact bound host (with or without port suffix)
    - Loopback aliases when bound to loopback
    - Any host when bound to 0.0.0.0 (explicit opt-in to non-loopback,
      no protection possible at this layer)
    """
    if not host_header:
        return False
    # Strip port suffix. IPv6 addresses use bracket notation:
    #   [::1]         — no port
    #   [::1]:9119    — with port
    # Plain hosts/v4:
    #   localhost:9119
    #   127.0.0.1:9119
    h = host_header.strip()
    if h.startswith("["):
        # IPv6 bracketed — port (if any) follows "]:"
        close = h.find("]")
        if close != -1:
            host_only = h[1:close]  # strip brackets
        else:
            host_only = h.strip("[]")
    else:
        host_only = h.rsplit(":", 1)[0] if ":" in h else h
    host_only = host_only.lower()

    # 0.0.0.0 bind means operator explicitly opted into all-interfaces
    # (requires --insecure per web_server.start_server). No Host-layer
    # defence can protect that mode; rely on operator network controls.
    if bound_host in ("0.0.0.0", "::"):
        return True

    # Loopback bind: accept the loopback names
    bound_lc = bound_host.lower()
    if bound_lc in _LOOPBACK_HOST_VALUES:
        return host_only in _LOOPBACK_HOST_VALUES

    # Explicit non-loopback bind: require exact host match
    return host_only == bound_lc


@app.middleware("http")
async def host_header_middleware(request: Request, call_next):
    """Reject requests whose Host header doesn't match the bound interface.

    Defends against DNS rebinding: a victim browser on a localhost
    dashboard is tricked into fetching from an attacker hostname that
    TTL-flips to 127.0.0.1. CORS and same-origin checks don't help —
    the browser now treats the attacker origin as same-origin with the
    dashboard. Host-header validation at the app layer catches it.

    See GHSA-ppp5-vxwm-4cf7.
    """
    # Store the bound host on app.state so this middleware can read it —
    # set by start_server() at listen time.
    bound_host = getattr(app.state, "bound_host", None)
    if bound_host:
        host_header = request.headers.get("host", "")
        if not _is_accepted_host(host_header, bound_host):
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        "Invalid Host header. Dashboard requests must use "
                        "the hostname the server was bound to."
                    ),
                },
            )
    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require dashboard auth on API routes and apply role gates when enabled."""
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    if _is_public_api_path(path):
        return await call_next(request)

    auth_enabled = _dashboard_auth_enabled()
    session = _dashboard_session_from_request(request)
    if not session and auth_enabled:
        session = _trusted_dashboard_session_from_request(request)
        if session:
            request.state.dashboard_session = session

    if not session:
        if auth_enabled or not path.startswith("/api/plugins/"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
        return await call_next(request)

    if auth_enabled:
        required_roles = _dashboard_required_roles(path, request.method)
        if not _dashboard_roles_allow(session.roles, required_roles):
            _audit_dashboard_event(
                "dashboard.authorization",
                request=request,
                actor=session.actor,
                action=request.method.upper(),
                resource=path,
                outcome="denied",
                reason=f"required_roles={required_roles}",
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Dashboard role denied. "
                        f"Required roles: {required_roles}; session roles: {session.roles}"
                    ),
                },
            )

    response = await call_next(request)

    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and path not in {
        "/api/dashboard/auth/login",
    }:
        _audit_dashboard_event(
            "dashboard.api_action",
            request=request,
            actor=session.actor,
            action=request.method.upper(),
            resource=path,
            outcome=str(response.status_code),
        )
    return response


# ---------------------------------------------------------------------------
# Config schema — auto-generated from DEFAULT_CONFIG
# ---------------------------------------------------------------------------

# Manual overrides for fields that need select options or custom types
_SCHEMA_OVERRIDES: Dict[str, Dict[str, Any]] = {
    "model": {
        "type": "string",
        "description": "Default model (e.g. anthropic/claude-sonnet-4.6)",
        "category": "general",
    },
    "model_context_length": {
        "type": "number",
        "description": "Context window override (0 = auto-detect from model metadata)",
        "category": "general",
    },
    "terminal.backend": {
        "type": "select",
        "description": "Terminal execution backend",
        "options": ["local", "docker", "ssh", "modal", "daytona", "vercel_sandbox", "singularity"],
    },
    "terminal.vercel_runtime": {
        "type": "select",
        "description": "Vercel Sandbox runtime",
        "options": ["node24", "node22", "python3.13"],  # sync with _SUPPORTED_VERCEL_RUNTIMES in terminal_tool.py
    },
    "terminal.modal_mode": {
        "type": "select",
        "description": "Modal sandbox mode",
        "options": ["sandbox", "function"],
    },
    "tts.provider": {
        "type": "select",
        "description": "Text-to-speech provider",
        "options": ["edge", "elevenlabs", "openai", "neutts"],
    },
    "stt.provider": {
        "type": "select",
        "description": "Speech-to-text provider",
        "options": ["local", "openai", "mistral"],
    },
    "display.skin": {
        "type": "select",
        "description": "CLI visual theme",
        "options": ["default", "ares", "mono", "slate"],
    },
    "dashboard.theme": {
        "type": "select",
        "description": "Web dashboard visual theme",
        "options": ["default", "midnight", "ember", "mono", "cyberpunk", "rose"],
    },
    "dashboard.auth.enabled": {
        "type": "boolean",
        "description": "Require login for dashboard API access",
        "category": "security",
    },
    "dashboard.auth.token_env": {
        "type": "string",
        "description": "Environment variable containing the dashboard admin token",
        "category": "security",
    },
    "dashboard.auth.token_hash": {
        "type": "string",
        "description": "Optional sha256 hash of the dashboard admin token",
        "category": "security",
    },
    "dashboard.auth.trusted_user_header": {
        "type": "string",
        "description": "Reverse-proxy header containing the authenticated dashboard user",
        "category": "security",
    },
    "dashboard.auth.local_token_roles": {
        "type": "list",
        "description": "Roles granted to successful local-token dashboard logins",
        "category": "security",
    },
    "dashboard.auth.channel_tokens.enabled": {
        "type": "boolean",
        "description": "Allow /dashboard to issue one-time login tokens to authenticated channel users",
        "category": "security",
    },
    "dashboard.auth.channel_tokens.ttl_minutes": {
        "type": "number",
        "description": "Minutes before channel-issued dashboard login tokens expire",
        "category": "security",
    },
    "dashboard.auth.channel_tokens.dashboard_url": {
        "type": "string",
        "description": "Dashboard URL shown to users who request /dashboard from a channel",
        "category": "security",
    },
    "dashboard.auth.channel_tokens.require_dm": {
        "type": "boolean",
        "description": "Require channel-issued dashboard tokens to be requested from private/direct chats",
        "category": "security",
    },
    "dashboard.auth.channel_tokens.approval_required": {
        "type": "boolean",
        "description": "Require an admin-approved Dashboard Access request before /dashboard issues a login token",
        "category": "security",
    },
    "dashboard.auth.read_roles": {
        "type": "list",
        "description": "Roles allowed to read dashboard data",
        "category": "security",
    },
    "dashboard.auth.manage_roles": {
        "type": "list",
        "description": "Roles allowed to approve team knowledge and cron checkpoints",
        "category": "security",
    },
    "dashboard.auth.admin_roles": {
        "type": "list",
        "description": "Roles allowed to change dashboard, governance, secrets, and server policies",
        "category": "security",
    },
    "display.resume_display": {
        "type": "select",
        "description": "How resumed sessions display history",
        "options": ["minimal", "full", "off"],
    },
    "display.busy_input_mode": {
        "type": "select",
        "description": "Input behavior while agent is running",
        "options": ["interrupt", "queue", "steer"],
    },
    "memory.provider": {
        "type": "select",
        "description": "Memory provider plugin",
        "options": ["builtin", "honcho"],
    },
    "approvals.mode": {
        "type": "select",
        "description": "Dangerous command approval mode",
        "options": ["ask", "yolo", "deny"],
    },
    "context.engine": {
        "type": "select",
        "description": "Context management engine",
        "options": ["default", "custom"],
    },
    "human_delay.mode": {
        "type": "select",
        "description": "Simulated typing delay mode",
        "options": ["off", "typing", "fixed"],
    },
    "logging.level": {
        "type": "select",
        "description": "Log level for agent.log",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR"],
    },
    "agent.service_tier": {
        "type": "select",
        "description": "API service tier (OpenAI/Anthropic)",
        "options": ["", "auto", "default", "flex"],
    },
    "delegation.reasoning_effort": {
        "type": "select",
        "description": "Reasoning effort for delegated subagents",
        "options": ["", "low", "medium", "high"],
    },
}

# Categories with fewer fields get merged into "general" to avoid tab sprawl.
_CATEGORY_MERGE: Dict[str, str] = {
    "privacy": "security",
    "context": "agent",
    "skills": "agent",
    "cron": "agent",
    "network": "agent",
    "checkpoints": "agent",
    "approvals": "security",
    "human_delay": "display",
    "dashboard": "display",
    "code_execution": "agent",
    "prompt_caching": "agent",
    "goals": "agent",
    "observability": "logging",
    # Only `telegram.reactions` currently lives under telegram — fold it in
    # with the other messaging-platform config (discord) so it isn't an
    # orphan tab of one field.
    "telegram": "discord",
}

# Display order for tabs — unlisted categories sort alphabetically after these.
_CATEGORY_ORDER = [
    "general", "agent", "terminal", "display", "delegation",
    "memory", "compression", "security", "browser", "voice",
    "tts", "stt", "logging", "discord", "auxiliary",
]


def _infer_type(value: Any) -> str:
    """Infer a UI field type from a Python value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "string"


def _build_schema_from_config(
    config: Dict[str, Any],
    prefix: str = "",
) -> Dict[str, Dict[str, Any]]:
    """Walk DEFAULT_CONFIG and produce a flat dot-path → field schema dict."""
    schema: Dict[str, Dict[str, Any]] = {}
    for key, value in config.items():
        full_key = f"{prefix}.{key}" if prefix else key

        # Skip internal / version keys
        if full_key in ("_config_version",):
            continue

        # Category is the first path component for nested keys, or "general"
        # for top-level scalar fields (model, toolsets, timezone, etc.).
        if prefix:
            category = prefix.split(".")[0]
        elif isinstance(value, dict):
            category = key
        else:
            category = "general"

        if isinstance(value, dict):
            # Recurse into nested dicts
            schema.update(_build_schema_from_config(value, full_key))
        else:
            entry: Dict[str, Any] = {
                "type": _infer_type(value),
                "description": full_key.replace(".", " → ").replace("_", " ").title(),
                "category": category,
            }
            # Apply manual overrides
            if full_key in _SCHEMA_OVERRIDES:
                entry.update(_SCHEMA_OVERRIDES[full_key])
            # Merge small categories
            entry["category"] = _CATEGORY_MERGE.get(entry["category"], entry["category"])
            schema[full_key] = entry
    return schema


CONFIG_SCHEMA = _build_schema_from_config(DEFAULT_CONFIG)

# Inject virtual fields that don't live in DEFAULT_CONFIG but are surfaced
# by the normalize/denormalize cycle.  Insert model_context_length right after
# the "model" key so it renders adjacent in the frontend.
_mcl_entry = _SCHEMA_OVERRIDES["model_context_length"]
_ordered_schema: Dict[str, Dict[str, Any]] = {}
for _k, _v in CONFIG_SCHEMA.items():
    _ordered_schema[_k] = _v
    if _k == "model":
        _ordered_schema["model_context_length"] = _mcl_entry
CONFIG_SCHEMA = _ordered_schema


class ConfigUpdate(BaseModel):
    config: dict


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


class DiscordGatewayAccessUser(BaseModel):
    user_id: str
    name: str = ""
    roles: Optional[List[str]] = None
    teams: Optional[List[str]] = None


class DiscordGatewayAccessUsersUpdate(BaseModel):
    users: List[DiscordGatewayAccessUser] = Field(default_factory=list)


class ModelAssignment(BaseModel):
    """Payload for POST /api/model/set — assign a provider/model to a slot.

    scope="main"        → writes model.provider + model.default
    scope="auxiliary"   → writes auxiliary.<task>.provider + auxiliary.<task>.model
    scope="auxiliary" with task=""  → applied to every auxiliary.* slot
    scope="auxiliary" with task="__reset__"  → resets every slot to provider="auto"
    """
    scope: str
    provider: str
    model: str
    task: str = ""


class DashboardLoginBody(BaseModel):
    token: str = ""


class DashboardAccessApproveBody(BaseModel):
    roles: Optional[List[str]] = None
    teams: Optional[List[str]] = None
    name: str = ""
    note: str = ""


class DashboardAccessDenyBody(BaseModel):
    reason: str = ""


class DashboardAccessRevokeBody(BaseModel):
    actor_key: str
    reason: str = ""


class FolderPoliciesUpdate(BaseModel):
    default_file_policy: Optional[str] = None
    folder_policies: List[dict] = []
    team_file_roots: Optional[dict] = None


def _normalize_discord_user_id(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("discord:"):
        text = text.split(":", 1)[1].strip()
    mention = re.fullmatch(r"<@!?(\d+)>", text)
    if mention:
        return mention.group(1)
    return text if re.fullmatch(r"\d+", text) else ""


# Platforms with a managed access-users editor in the dashboard. Each maps
# to the env allowlist variable the gateway reads and the governance
# identity prefix (`<platform>:<user id>` keys under governance.users).
_GATEWAY_ACCESS_PLATFORMS: Dict[str, str] = {
    "discord": "DISCORD_ALLOWED_USERS",
    "slack": "SLACK_ALLOWED_USERS",
    "mattermost": "MATTERMOST_ALLOWED_USERS",
    "matrix": "MATRIX_ALLOWED_USERS",
}


def _gateway_access_env_key(platform: str) -> str:
    env_key = _GATEWAY_ACCESS_PLATFORMS.get(str(platform or "").lower())
    if not env_key:
        raise HTTPException(
            status_code=404, detail=f"No managed access users for platform: {platform}"
        )
    return env_key


def _normalize_gateway_user_id(platform: str, value: Any) -> str:
    """Normalize one user id for a platform's allowlist.

    Discord keeps its strict numeric/mention handling; other platforms trim
    whitespace/quotes and accept a pasted `<platform>:<id>` governance key.
    Matrix IDs legitimately contain ':' (@user:server), so only the leading
    platform prefix is split off.
    """
    if platform == "discord":
        return _normalize_discord_user_id(value)
    text = str(value or "").strip().strip("\"'").strip()
    prefix = f"{platform}:"
    if text.lower().startswith(prefix):
        text = text.split(":", 1)[1].strip()
    if not text or "," in text or any(ch.isspace() for ch in text):
        return ""
    return text


def _load_gateway_access_users(platform: str) -> List[Dict[str, Any]]:
    platform = str(platform or "").lower()
    env_key = _gateway_access_env_key(platform)
    env_on_disk = load_env()
    raw_allowed = str(env_on_disk.get(env_key) or "")
    ordered_ids: List[str] = []
    seen: set[str] = set()
    for part in raw_allowed.split(","):
        user_id = _normalize_gateway_user_id(platform, part)
        if user_id and user_id not in seen:
            ordered_ids.append(user_id)
            seen.add(user_id)

    cfg = load_config()
    governance = cfg.get("governance", {}) if isinstance(cfg, dict) else {}
    users = governance.get("users", {}) if isinstance(governance, dict) else {}
    users = users if isinstance(users, dict) else {}

    result: List[Dict[str, Any]] = []
    for user_id in ordered_ids:
        record = users.get(f"{platform}:{user_id}") or users.get(user_id) or {}
        if not isinstance(record, dict):
            record = {"roles": _coerce_role_list(record)}
        result.append(
            {
                "user_id": user_id,
                "name": str(record.get("name") or ""),
                "roles": _coerce_role_list(record.get("roles")),
                "teams": _coerce_role_list(record.get("teams") or record.get("team")),
                "governed": bool(_coerce_role_list(record.get("roles"))),
            }
        )
    return result


def _save_gateway_access_users(
    platform: str, users_payload: List[DiscordGatewayAccessUser]
) -> List[Dict[str, Any]]:
    platform = str(platform or "").lower()
    env_key = _gateway_access_env_key(platform)
    cfg = load_config()
    if not isinstance(cfg, dict):
        cfg = {}
    governance = cfg.get("governance", {})
    if not isinstance(governance, dict):
        governance = {}
    users = governance.get("users", {})
    if not isinstance(users, dict):
        users = {}

    # Only a completely fresh installation receives an automatic bootstrap
    # administrator. Once any explicit user with a role exists, this editor is
    # allowlist-only; Governance is the sole place that can grant access.
    bootstrap_needed = not any(
        _coerce_role_list(
            record.get("roles") if isinstance(record, dict) else record
        )
        for record in users.values()
    )
    bootstrap_created = False

    allowed_ids: List[str] = []
    seen: set[str] = set()
    for item in users_payload:
        user_id = _normalize_gateway_user_id(platform, item.user_id)
        if not user_id:
            continue
        if user_id in seen:
            continue
        seen.add(user_id)
        allowed_ids.append(user_id)

        key = f"{platform}:{user_id}"
        existing = users.get(key)
        existing_roles = _coerce_role_list(
            existing.get("roles") if isinstance(existing, dict) else existing
        )
        if existing_roles:
            # Gateway editing must never rewrite an established Governance
            # identity, role, or team assignment.
            continue

        if bootstrap_needed and not bootstrap_created:
            name = str(item.name or "").strip() or key
            users[key] = {"name": name, "roles": ["admin"]}
            bootstrap_created = True

    save_env_value(env_key, ",".join(allowed_ids))
    governance["users"] = users
    cfg["governance"] = governance
    save_config(cfg)
    return _load_gateway_access_users(platform)


def _load_discord_gateway_access_users() -> List[Dict[str, Any]]:
    return _load_gateway_access_users("discord")


def _save_discord_gateway_access_users(users_payload: List[DiscordGatewayAccessUser]) -> List[Dict[str, Any]]:
    return _save_gateway_access_users("discord", users_payload)


def _save_governance_user_from_dashboard_access(
    *,
    actor_key: str,
    name: str,
    roles: List[str],
    teams: List[str],
) -> Dict[str, Any]:
    key = str(actor_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="actor_key is required")
    if not roles:
        raise HTTPException(status_code=400, detail="At least one role is required")

    cfg = load_config()
    if not isinstance(cfg, dict):
        cfg = {}
    governance = cfg.get("governance", {})
    if not isinstance(governance, dict):
        governance = {}
    users = governance.get("users", {})
    if not isinstance(users, dict):
        users = {}

    existing = users.get(key)
    record = dict(existing) if isinstance(existing, dict) else {}
    record["name"] = str(name or record.get("name") or key).strip()
    record["roles"] = roles
    if teams:
        record["teams"] = teams
    else:
        record.pop("teams", None)
        record.pop("team", None)
    users[key] = record
    governance["users"] = users
    cfg["governance"] = governance
    save_config(cfg)
    return record


@app.get("/api/dashboard/auth/status")
async def dashboard_auth_status(request: Request):
    auth_config = _dashboard_auth_config()
    if not _dashboard_auth_enabled(auth_config):
        return {
            "auth_required": False,
            "authenticated": True,
            "token": _SESSION_TOKEN,
            "actor": {"id": "local"},
            "roles": ["admin"],
            "capabilities": _dashboard_capabilities(["admin"]),
        }

    session = _dashboard_session_from_request(request)
    if not session:
        session = _trusted_dashboard_session_from_request(request)
    if session:
        return {
            "auth_required": True,
            "authenticated": True,
            **_dashboard_session_payload(session),
        }
    return {
        "auth_required": True,
        "authenticated": False,
        "modes": {
            "local_token": _dashboard_has_token_secret(auth_config),
            "trusted_header": _dashboard_trusted_headers_allowed(auth_config),
            "channel_token": _dashboard_channel_tokens_enabled(auth_config),
        },
    }


@app.post("/api/dashboard/auth/login")
async def dashboard_auth_login(request: Request, body: DashboardLoginBody):
    auth_config = _dashboard_auth_config()
    if not _dashboard_auth_enabled(auth_config):
        return {
            "auth_required": False,
            "authenticated": True,
            "token": _SESSION_TOKEN,
            "actor": {"id": "local"},
            "roles": ["admin"],
            "capabilities": _dashboard_capabilities(["admin"]),
        }

    session = _trusted_dashboard_session_from_request(request)
    if session:
        _audit_dashboard_event(
            "dashboard.auth",
            request=request,
            actor=session.actor,
            action="login",
            resource="dashboard",
            outcome="success",
            metadata={"source": session.source, "roles": session.roles},
        )
        return {
            "auth_required": True,
            "authenticated": True,
            **_dashboard_session_payload(session),
        }

    raw_token = str(body.token or "")
    session = _consume_channel_dashboard_login(raw_token, auth_config)
    if session:
        _audit_dashboard_event(
            "dashboard.auth",
            request=request,
            actor=session.actor,
            action="login",
            resource="dashboard",
            outcome="success",
            metadata={"source": session.source, "roles": session.roles},
        )
        return {
            "auth_required": True,
            "authenticated": True,
            **_dashboard_session_payload(session),
        }

    if not _verify_local_dashboard_login(raw_token, auth_config):
        _audit_dashboard_event(
            "dashboard.auth",
            request=request,
            action="login",
            resource="dashboard",
            outcome="denied",
            reason="invalid_token",
        )
        raise HTTPException(status_code=401, detail="Invalid dashboard token")

    try:
        from agent.governance import Actor

        actor = Actor(platform="dashboard", user_id="local-admin", user_name="Local Dashboard Admin")
    except Exception:
        actor = "dashboard:local-admin"

    roles = _dashboard_roles_for_actor(
        actor,
        fallback_roles=_coerce_role_list(auth_config.get("local_token_roles")) or ["admin"],
    )
    if not _dashboard_roles_allow(roles, _coerce_role_list(auth_config.get("read_roles"))):
        _audit_dashboard_event(
            "dashboard.auth",
            request=request,
            actor=actor,
            action="login",
            resource="dashboard",
            outcome="denied",
            reason="role_denied",
            metadata={"roles": roles},
        )
        raise HTTPException(status_code=403, detail="Dashboard token is valid, but roles are not allowed.")

    session = _issue_dashboard_session(actor, roles, "local_token")
    _audit_dashboard_event(
        "dashboard.auth",
        request=request,
        actor=session.actor,
        action="login",
        resource="dashboard",
        outcome="success",
        metadata={"source": session.source, "roles": session.roles},
    )
    return {
        "auth_required": True,
        "authenticated": True,
        **_dashboard_session_payload(session),
    }


@app.post("/api/dashboard/auth/logout")
async def dashboard_auth_logout(request: Request):
    session = _request_dashboard_session(request)
    if session:
        _DASHBOARD_AUTH_SESSIONS.pop(session.token, None)
        _audit_dashboard_event(
            "dashboard.auth",
            request=request,
            actor=session.actor,
            action="logout",
            resource="dashboard",
            outcome="success",
            metadata={"source": session.source},
        )
    return {"ok": True}


@app.get("/api/dashboard/access/requests")
async def dashboard_access_requests(request: Request):
    try:
        from hermes_cli.dashboard_tokens import (
            list_dashboard_access_requests,
            list_dashboard_access_revocations,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dashboard access store unavailable: {exc}") from exc
    return {
        "requests": list_dashboard_access_requests(),
        "revoked_users": list_dashboard_access_revocations(),
    }


@app.post("/api/dashboard/access/requests/{request_id}/approve")
async def dashboard_access_request_approve(
    request: Request,
    request_id: str,
    body: DashboardAccessApproveBody,
):
    try:
        from hermes_cli.dashboard_tokens import (
            decide_dashboard_access_request,
            get_dashboard_access_request,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dashboard access store unavailable: {exc}") from exc

    pending = get_dashboard_access_request(request_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Dashboard access request not found")
    actor_key_value = str(pending.get("actor_key") or "").strip()
    actor_payload = pending.get("actor", {}) if isinstance(pending.get("actor"), dict) else {}
    roles = _coerce_role_list(body.roles)
    teams = _coerce_role_list(body.teams)
    display_name = (
        str(body.name or "").strip()
        or str(actor_payload.get("user_name") or "").strip()
        or actor_key_value
    )
    user_record = _save_governance_user_from_dashboard_access(
        actor_key=actor_key_value,
        name=display_name,
        roles=roles,
        teams=teams,
    )
    decision = decide_dashboard_access_request(
        request_id=request_id,
        approve=True,
        reviewer=_request_dashboard_actor(request),
        roles=roles,
        teams=teams,
        note=body.note,
    )
    _audit_dashboard_event(
        "dashboard.access_request",
        request=request,
        actor=_request_dashboard_actor(request),
        action="approve",
        resource=actor_key_value,
        outcome="success",
        metadata={"roles": roles, "teams": teams},
    )
    return {"ok": True, "request": decision, "user": user_record}


@app.post("/api/dashboard/access/requests/{request_id}/deny")
async def dashboard_access_request_deny(
    request: Request,
    request_id: str,
    body: DashboardAccessDenyBody,
):
    try:
        from hermes_cli.dashboard_tokens import decide_dashboard_access_request
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dashboard access store unavailable: {exc}") from exc
    try:
        decision = decide_dashboard_access_request(
            request_id=request_id,
            approve=False,
            reviewer=_request_dashboard_actor(request),
            note=body.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dashboard access request not found") from exc
    _audit_dashboard_event(
        "dashboard.access_request",
        request=request,
        actor=_request_dashboard_actor(request),
        action="deny",
        resource=str(decision.get("actor_key") or request_id),
        outcome="success",
        reason=body.reason,
    )
    return {"ok": True, "request": decision}


@app.post("/api/dashboard/access/revoke")
async def dashboard_access_revoke(request: Request, body: DashboardAccessRevokeBody):
    try:
        from hermes_cli.dashboard_tokens import revoke_dashboard_access
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dashboard access store unavailable: {exc}") from exc
    try:
        record = revoke_dashboard_access(
            actor_key_value=body.actor_key,
            reviewer=_request_dashboard_actor(request),
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dropped_sessions = _drop_dashboard_sessions_for_actor_key(body.actor_key)
    _audit_dashboard_event(
        "dashboard.access_revocation",
        request=request,
        actor=_request_dashboard_actor(request),
        action="revoke",
        resource=body.actor_key,
        outcome="success",
        reason=body.reason,
        metadata={"dropped_sessions": dropped_sessions},
    )
    return {"ok": True, "revocation": record, "dropped_sessions": dropped_sessions}


@app.post("/api/dashboard/access/restore")
async def dashboard_access_restore(request: Request, body: DashboardAccessRevokeBody):
    try:
        from hermes_cli.dashboard_tokens import restore_dashboard_access
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Dashboard access store unavailable: {exc}") from exc
    try:
        record = restore_dashboard_access(
            actor_key_value=body.actor_key,
            reviewer=_request_dashboard_actor(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_dashboard_event(
        "dashboard.access_revocation",
        request=request,
        actor=_request_dashboard_actor(request),
        action="restore",
        resource=body.actor_key,
        outcome="success",
    )
    return {"ok": True, "restore": record}


_GATEWAY_HEALTH_URL = os.getenv("GATEWAY_HEALTH_URL")
try:
    _GATEWAY_HEALTH_TIMEOUT = float(os.getenv("GATEWAY_HEALTH_TIMEOUT", "3"))
except (ValueError, TypeError):
    _log.warning(
        "Invalid GATEWAY_HEALTH_TIMEOUT value %r — using default 3.0s",
        os.getenv("GATEWAY_HEALTH_TIMEOUT"),
    )
    _GATEWAY_HEALTH_TIMEOUT = 3.0

# DEPRECATED (scheduled for removal): GATEWAY_HEALTH_URL / GATEWAY_HEALTH_TIMEOUT.
# Cross-container / cross-host gateway liveness detection will be folded into a
# first-class dashboard config key so it's no longer Docker-adjacent lore buried
# in env vars.  The env vars still work for now so existing Compose deployments
# don't break.  Do not add new callers — wire new uses through the planned
# config surface.


def _probe_gateway_health() -> tuple[bool, dict | None]:
    """Probe the gateway via its HTTP health endpoint (cross-container).

    .. deprecated::
        Driven by the deprecated ``GATEWAY_HEALTH_URL`` /
        ``GATEWAY_HEALTH_TIMEOUT`` env vars.  Scheduled for removal alongside
        a move to a first-class dashboard config key.  See
        :data:`_GATEWAY_HEALTH_URL` for context.

    Uses ``/health/detailed`` first (returns full state), falling back to
    the simpler ``/health`` endpoint.  Returns ``(is_alive, body_dict)``.

    Accepts any of these as ``GATEWAY_HEALTH_URL``:
    - ``http://gateway:8642``                (base URL — recommended)
    - ``http://gateway:8642/health``         (explicit health path)
    - ``http://gateway:8642/health/detailed`` (explicit detailed path)

    This is a **blocking** call — run via ``run_in_executor`` from async code.
    """
    if not _GATEWAY_HEALTH_URL:
        return False, None

    # Normalise to base URL so we always probe the right paths regardless of
    # whether the user included /health or /health/detailed in the env var.
    base = _GATEWAY_HEALTH_URL.rstrip("/")
    if base.endswith("/health/detailed"):
        base = base[: -len("/health/detailed")]
    elif base.endswith("/health"):
        base = base[: -len("/health")]

    for path in (f"{base}/health/detailed", f"{base}/health"):
        try:
            req = urllib.request.Request(path, method="GET")
            with urllib.request.urlopen(req, timeout=_GATEWAY_HEALTH_TIMEOUT) as resp:
                if resp.status == 200:
                    body = json.loads(resp.read())
                    return True, body
        except Exception:
            continue
    return False, None


@app.get("/api/status")
async def get_status():
    current_ver, latest_ver = check_config_version()

    # --- Gateway liveness detection ---
    # Try local PID check first (same-host).  If that fails and a remote
    # GATEWAY_HEALTH_URL is configured, probe the gateway over HTTP so the
    # dashboard works when the gateway runs in a separate container.
    gateway_pid = get_running_pid()
    gateway_running = gateway_pid is not None
    remote_health_body: dict | None = None

    if not gateway_running and _GATEWAY_HEALTH_URL:
        loop = asyncio.get_event_loop()
        alive, remote_health_body = await loop.run_in_executor(
            None, _probe_gateway_health
        )
        if alive:
            gateway_running = True
            # PID from the remote container (display only — not locally valid)
            if remote_health_body:
                gateway_pid = remote_health_body.get("pid")

    gateway_state = None
    gateway_platforms: dict = {}
    gateway_exit_reason = None
    gateway_updated_at = None
    configured_gateway_platforms: set[str] | None = None
    try:
        from gateway.config import load_gateway_config

        gateway_config = load_gateway_config()
        configured_gateway_platforms = {
            platform.value for platform in gateway_config.get_connected_platforms()
        }
    except Exception:
        configured_gateway_platforms = None

    # Prefer the detailed health endpoint response (has full state) when the
    # local runtime status file is absent or stale (cross-container).
    runtime = read_runtime_status()
    if runtime is None and remote_health_body and remote_health_body.get("gateway_state"):
        runtime = remote_health_body

    if runtime:
        gateway_state = runtime.get("gateway_state")
        gateway_platforms = runtime.get("platforms") or {}
        if configured_gateway_platforms is not None:
            gateway_platforms = {
                key: value
                for key, value in gateway_platforms.items()
                if key in configured_gateway_platforms
            }
        gateway_exit_reason = runtime.get("exit_reason")
        gateway_updated_at = runtime.get("updated_at")
        if not gateway_running:
            gateway_state = gateway_state if gateway_state in ("stopped", "startup_failed") else "stopped"
            gateway_platforms = {}
        elif gateway_running and remote_health_body is not None:
            # The health probe confirmed the gateway is alive, but the local
            # runtime status file may be stale (cross-container).  Override
            # stopped/None state so the dashboard shows the correct badge.
            if gateway_state in (None, "stopped"):
                gateway_state = "running"

    # If there was no runtime info at all but the health probe confirmed alive,
    # ensure we still report the gateway as running (no shared volume scenario).
    if gateway_running and gateway_state is None and remote_health_body is not None:
        gateway_state = "running"

    active_sessions = 0
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=50)
            now = time.time()
            active_sessions = sum(
                1 for s in sessions
                if s.get("ended_at") is None
                and (now - s.get("last_active", s.get("started_at", 0))) < 300
            )
        finally:
            db.close()
    except Exception:
        pass

    governance_warnings: list = []
    try:
        from agent.governance import governance_posture_warnings

        governance_warnings = governance_posture_warnings()
    except Exception:
        governance_warnings = []

    return {
        "version": __version__,
        "release_date": __release_date__,
        "hermes_home": str(get_hermes_home()),
        "config_path": str(get_config_path()),
        "env_path": str(get_env_path()),
        "config_version": current_ver,
        "latest_config_version": latest_ver,
        "gateway_running": gateway_running,
        "gateway_pid": gateway_pid,
        "gateway_health_url": _GATEWAY_HEALTH_URL,
        "gateway_state": gateway_state,
        "gateway_platforms": gateway_platforms,
        "gateway_exit_reason": gateway_exit_reason,
        "gateway_updated_at": gateway_updated_at,
        "active_sessions": active_sessions,
        "governance_warnings": governance_warnings,
    }


# ---------------------------------------------------------------------------
# Gateway + update actions (invoked from the Status page).
#
# Both commands are spawned as detached subprocesses so the HTTP request
# returns immediately.  stdin is closed (``DEVNULL``) so any stray ``input()``
# calls fail fast with EOF rather than hanging forever.  stdout/stderr are
# streamed to a per-action log file under ``~/.hermes/logs/<action>.log`` so
# the dashboard can tail them back to the user.
# ---------------------------------------------------------------------------

_ACTION_LOG_DIR: Path = get_hermes_home() / "logs"

# Short ``name`` (from the URL) → absolute log file path.
_ACTION_LOG_FILES: Dict[str, str] = {
    "gateway-start": "gateway-start.log",
    "gateway-restart": "gateway-restart.log",
    "hermes-update": "hermes-update.log",
}

# ``name`` → most recently spawned Popen handle.  Used so ``status`` can
# report liveness and exit code without shelling out to ``ps``.
_ACTION_PROCS: Dict[str, subprocess.Popen] = {}


def _spawn_hermes_action(subcommand: List[str], name: str) -> subprocess.Popen:
    """Spawn ``hermes <subcommand>`` detached and record the Popen handle.

    Uses the running interpreter's ``hermes_cli.main`` module so the action
    inherits the same venv/PYTHONPATH the web server is using.
    """
    log_file_name = _ACTION_LOG_FILES[name]
    _ACTION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _ACTION_LOG_DIR / log_file_name
    log_file = open(log_path, "ab", buffering=0)
    log_file.write(
        f"\n=== {name} started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode()
    )

    cmd = [sys.executable, "-m", "hermes_cli.main", *subcommand]

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "env": {**os.environ, "HERMES_NONINTERACTIVE": "1"},
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    _ACTION_PROCS[name] = proc
    return proc


def _tail_lines(path: Path, n: int) -> List[str]:
    """Return the last ``n`` lines of ``path``.  Reads the whole file — fine
    for our small per-action logs.  Binary-decoded with ``errors='replace'``
    so log corruption doesn't 500 the endpoint."""
    if not path.exists():
        return []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-n:] if n > 0 else lines


@app.post("/api/gateway/restart")
async def restart_gateway():
    """Kick off a ``maia gateway restart`` in the background."""
    try:
        proc = _spawn_hermes_action(["gateway", "restart"], "gateway-restart")
    except Exception as exc:
        _log.exception("Failed to spawn gateway restart")
        raise HTTPException(status_code=500, detail=f"Failed to restart gateway: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "gateway-restart",
    }


@app.post("/api/gateway/start")
async def start_gateway():
    """Kick off a ``maia gateway start`` in the background."""
    try:
        proc = _spawn_hermes_action(["gateway", "start"], "gateway-start")
    except Exception as exc:
        _log.exception("Failed to spawn gateway start")
        raise HTTPException(status_code=500, detail=f"Failed to start gateway: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "gateway-start",
    }


@app.post("/api/hermes/update")
async def update_hermes():
    """Kick off ``hermes update`` in the background."""
    try:
        proc = _spawn_hermes_action(["update"], "hermes-update")
    except Exception as exc:
        _log.exception("Failed to spawn hermes update")
        raise HTTPException(status_code=500, detail=f"Failed to start update: {exc}")
    return {
        "ok": True,
        "pid": proc.pid,
        "name": "hermes-update",
    }


@app.get("/api/actions/{name}/status")
async def get_action_status(name: str, lines: int = 200):
    """Tail an action log and report whether the process is still running."""
    log_file_name = _ACTION_LOG_FILES.get(name)
    if log_file_name is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {name}")

    log_path = _ACTION_LOG_DIR / log_file_name
    tail = _tail_lines(log_path, min(max(lines, 1), 2000))

    proc = _ACTION_PROCS.get(name)
    if proc is None:
        running = False
        exit_code: Optional[int] = None
        pid: Optional[int] = None
    else:
        exit_code = proc.poll()
        running = exit_code is None
        pid = proc.pid

    return {
        "name": name,
        "running": running,
        "exit_code": exit_code,
        "pid": pid,
        "lines": tail,
    }


@app.get("/api/sessions")
async def get_sessions(limit: int = 20, offset: int = 0):
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            sessions = db.list_sessions_rich(limit=limit, offset=offset)
            total = db.session_count()
            now = time.time()
            for s in sessions:
                s["is_active"] = (
                    s.get("ended_at") is None
                    and (now - s.get("last_active", s.get("started_at", 0))) < 300
                )
            return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/sessions/search")
async def search_sessions(q: str = "", limit: int = 20):
    """Full-text search across session message content using FTS5."""
    if not q or not q.strip():
        return {"results": []}
    try:
        from hermes_state import SessionDB
        db = SessionDB()
        try:
            # Auto-add prefix wildcards so partial words match
            # e.g. "nimb" → "nimb*" matches "nimby"
            # Preserve quoted phrases and existing wildcards as-is
            import re
            terms = []
            for token in re.findall(r'"[^"]*"|\S+', q.strip()):
                if token.startswith('"') or token.endswith("*"):
                    terms.append(token)
                else:
                    terms.append(token + "*")
            prefix_query = " ".join(terms)
            matches = db.search_messages(query=prefix_query, limit=limit)
            # Group by session_id — return unique sessions with their best snippet
            seen: dict = {}
            for m in matches:
                sid = m["session_id"]
                if sid not in seen:
                    seen[sid] = {
                        "session_id": sid,
                        "snippet": m.get("snippet", ""),
                        "role": m.get("role"),
                        "source": m.get("source"),
                        "model": m.get("model"),
                        "session_started": m.get("session_started"),
                    }
            return {"results": list(seen.values())}
        finally:
            db.close()
    except Exception:
        _log.exception("GET /api/sessions/search failed")
        raise HTTPException(status_code=500, detail="Search failed")


def _normalize_config_for_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize config for the web UI.

    Hermes supports ``model`` as either a bare string (``"anthropic/claude-sonnet-4"``)
    or a dict (``{default: ..., provider: ..., base_url: ...}``).  The schema is built
    from DEFAULT_CONFIG where ``model`` is a string, but user configs often have the
    dict form.  Normalize to the string form so the frontend schema matches.

    Also surfaces ``model_context_length`` as a top-level field so the web UI can
    display and edit it.  A value of 0 means "auto-detect".
    """
    config = dict(config)  # shallow copy
    model_val = config.get("model")
    if isinstance(model_val, dict):
        # Extract context_length before flattening the dict
        ctx_len = model_val.get("context_length", 0)
        config["model"] = model_val.get("default", model_val.get("name", ""))
        config["model_context_length"] = ctx_len if isinstance(ctx_len, int) else 0
    else:
        config["model_context_length"] = 0
    return config


def _redact_config_for_non_admin(config: Dict[str, Any]) -> Dict[str, Any]:
    """Remove admin-only sections from a config payload for read-role callers.

    ``GET /api/config`` is gated at read_roles, but the raw config carries the
    governance user->role/team map, folder-policy filesystem layout, and any
    inline-configured secrets (e.g. dashboard.auth.token_hash). A read-only
    auditor should not enumerate who has which role or read stored secrets.
    Admins (and local single-user mode) still get the full document.
    """
    redacted = dict(config)
    # Governance identity/authorization surface.
    gov = redacted.get("governance")
    if isinstance(gov, dict):
        gov = dict(gov)
        for key in ("users", "folder_policies", "team_file_roots", "role_hierarchy"):
            gov.pop(key, None)
        gov["_redacted"] = "admin-only fields hidden for your role"
        redacted["governance"] = gov
    # Dashboard auth block may hold token hashes / shared secrets inline.
    dash = redacted.get("dashboard")
    if isinstance(dash, dict) and isinstance(dash.get("auth"), dict):
        dash = dict(dash)
        auth = {
            k: v for k, v in dash["auth"].items()
            if k not in ("token_hash", "token", "shared_secret", "trusted_user_header")
        }
        dash["auth"] = auth
        redacted["dashboard"] = dash
    return redacted


@app.get("/api/config")
async def get_config(request: Request):
    config = _normalize_config_for_web(load_config())
    # Strip internal keys that the frontend shouldn't see or send back
    payload = {k: v for k, v in config.items() if not k.startswith("_")}
    # In protected mode, hide the governance role map + inline secrets from
    # non-admin (read-role) callers. Local single-user mode is admin-trusted.
    if _dashboard_auth_enabled() and not _dashboard_actor_is_admin(request):
        payload = _redact_config_for_non_admin(payload)
    return payload


@app.get("/api/config/defaults")
async def get_defaults():
    return DEFAULT_CONFIG


@app.get("/api/config/schema")
async def get_schema():
    return {"fields": CONFIG_SCHEMA, "category_order": _CATEGORY_ORDER}


_EMPTY_MODEL_INFO: dict = {
    "model": "",
    "provider": "",
    "auto_context_length": 0,
    "config_context_length": 0,
    "effective_context_length": 0,
    "capabilities": {},
}


@app.get("/api/model/info")
def get_model_info():
    """Return resolved model metadata for the currently configured model.

    Calls the same context-length resolution chain the agent uses, so the
    frontend can display "Auto-detected: 200K" alongside the override field.
    Also returns model capabilities (vision, reasoning, tools) when available.
    """
    try:
        cfg = load_config()
        model_cfg = cfg.get("model", "")

        # Extract model name and provider from the config
        if isinstance(model_cfg, dict):
            model_name = model_cfg.get("default", model_cfg.get("name", ""))
            provider = model_cfg.get("provider", "")
            base_url = model_cfg.get("base_url", "")
            config_ctx = model_cfg.get("context_length")
        else:
            model_name = str(model_cfg) if model_cfg else ""
            provider = ""
            base_url = ""
            config_ctx = None

        if not model_name:
            return dict(_EMPTY_MODEL_INFO, provider=provider)

        # Resolve auto-detected context length (pass config_ctx=None to get
        # purely auto-detected value, then separately report the override)
        try:
            from agent.model_metadata import get_model_context_length
            auto_ctx = get_model_context_length(
                model=model_name,
                base_url=base_url,
                provider=provider,
                config_context_length=None,  # ignore override — we want auto value
            )
        except Exception:
            auto_ctx = 0

        config_ctx_int = 0
        if isinstance(config_ctx, int) and config_ctx > 0:
            config_ctx_int = config_ctx

        # Effective is what the agent actually uses
        effective_ctx = config_ctx_int if config_ctx_int > 0 else auto_ctx

        # Try to get model capabilities from models.dev
        caps = {}
        try:
            from agent.models_dev import get_model_capabilities
            mc = get_model_capabilities(provider=provider, model=model_name)
            if mc is not None:
                caps = {
                    "supports_tools": mc.supports_tools,
                    "supports_vision": mc.supports_vision,
                    "supports_reasoning": mc.supports_reasoning,
                    "context_window": mc.context_window,
                    "max_output_tokens": mc.max_output_tokens,
                    "model_family": mc.model_family,
                }
        except Exception:
            pass

        return {
            "model": model_name,
            "provider": provider,
            "auto_context_length": auto_ctx,
            "config_context_length": config_ctx_int,
            "effective_context_length": effective_ctx,
            "capabilities": caps,
        }
    except Exception:
        _log.exception("GET /api/model/info failed")
        return dict(_EMPTY_MODEL_INFO)


# ---------------------------------------------------------------------------
# Model assignment — pick provider+model for main slot or auxiliary slots.
# Mirrors the model.options JSON-RPC from tui_gateway but uses REST so the
# Models page (which has no chat PTY open) can drive it.
# ---------------------------------------------------------------------------

# Canonical auxiliary task slots. Keep in sync with DEFAULT_CONFIG["auxiliary"]
# in hermes_cli/config.py — listed here for deterministic ordering in the UI.
_AUX_TASK_SLOTS: Tuple[str, ...] = (
    "vision",
    "web_extract",
    "compression",
    "session_search",
    "skills_hub",
    "approval",
    "mcp",
    "title_generation",
    "curator",
)


@app.get("/api/model/options")
def get_model_options():
    """Return authenticated providers + their curated model lists.

    REST equivalent of the ``model.options`` JSON-RPC on tui_gateway, so the
    dashboard Models page can render the picker without a live chat session.
    The response shape matches ``model.options`` 1:1 so ``ModelPickerDialog``
    can share the same types.
    """
    try:
        from hermes_cli.model_switch import list_authenticated_providers

        cfg = load_config()
        model_cfg = cfg.get("model", {})
        if isinstance(model_cfg, dict):
            current_model = model_cfg.get("default", model_cfg.get("name", "")) or ""
            current_provider = model_cfg.get("provider", "") or ""
            current_base_url = model_cfg.get("base_url", "") or ""
        else:
            current_model = str(model_cfg) if model_cfg else ""
            current_provider = ""
            current_base_url = ""

        user_providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
        custom_providers = (
            cfg.get("custom_providers")
            if isinstance(cfg.get("custom_providers"), list)
            else []
        )

        providers = list_authenticated_providers(
            current_provider=current_provider,
            current_base_url=current_base_url,
            current_model=current_model,
            user_providers=user_providers,
            custom_providers=custom_providers,
            max_models=50,
        )
        return {
            "providers": providers,
            "model": current_model,
            "provider": current_provider,
        }
    except Exception:
        _log.exception("GET /api/model/options failed")
        raise HTTPException(status_code=500, detail="Failed to list model options")


@app.get("/api/model/auxiliary")
def get_auxiliary_models():
    """Return current auxiliary task assignments.

    Shape:
      {
        "tasks": [
          {"task": "vision", "provider": "auto", "model": "", "base_url": ""},
          ...
        ],
        "main": {"provider": "openrouter", "model": "anthropic/claude-opus-4.7"},
      }
    """
    try:
        cfg = load_config()
        aux_cfg = cfg.get("auxiliary", {})
        if not isinstance(aux_cfg, dict):
            aux_cfg = {}

        tasks = []
        for slot in _AUX_TASK_SLOTS:
            slot_cfg = aux_cfg.get(slot, {}) if isinstance(aux_cfg.get(slot), dict) else {}
            tasks.append({
                "task": slot,
                "provider": str(slot_cfg.get("provider", "auto") or "auto"),
                "model": str(slot_cfg.get("model", "") or ""),
                "base_url": str(slot_cfg.get("base_url", "") or ""),
            })

        model_cfg = cfg.get("model", {})
        if isinstance(model_cfg, dict):
            main = {
                "provider": str(model_cfg.get("provider", "") or ""),
                "model": str(model_cfg.get("default", model_cfg.get("name", "")) or ""),
            }
        else:
            main = {"provider": "", "model": str(model_cfg) if model_cfg else ""}

        return {"tasks": tasks, "main": main}
    except Exception:
        _log.exception("GET /api/model/auxiliary failed")
        raise HTTPException(status_code=500, detail="Failed to read auxiliary config")


@app.post("/api/model/set")
async def set_model_assignment(body: ModelAssignment):
    """Assign a model to the main slot or an auxiliary task slot.

    Writes to ``~/.hermes/config.yaml`` — applies to **new** sessions only.
    The currently running chat PTY (if any) is not affected; use the
    ``/model`` slash command inside a chat to hot-swap that specific session.
    """
    scope = (body.scope or "").strip().lower()
    provider = (body.provider or "").strip()
    model = (body.model or "").strip()
    task = (body.task or "").strip().lower()

    if scope not in ("main", "auxiliary"):
        raise HTTPException(status_code=400, detail="scope must be 'main' or 'auxiliary'")

    try:
        cfg = load_config()

        if scope == "main":
            if not provider or not model:
                raise HTTPException(status_code=400, detail="provider and model required for main")
            model_cfg = cfg.get("model", {})
            if not isinstance(model_cfg, dict):
                model_cfg = {}
            model_cfg["provider"] = provider
            model_cfg["default"] = model
            # Clear stale base_url so the resolver picks the provider's own default.
            if "base_url" in model_cfg and model_cfg.get("base_url"):
                model_cfg["base_url"] = ""
            # Also clear hardcoded context_length override — new model may have
            # a different context window.
            if "context_length" in model_cfg:
                model_cfg.pop("context_length", None)
            cfg["model"] = model_cfg
            save_config(cfg)
            return {"ok": True, "scope": "main", "provider": provider, "model": model}

        # scope == "auxiliary"
        aux = cfg.get("auxiliary")
        if not isinstance(aux, dict):
            aux = {}

        if task == "__reset__":
            # Reset every slot to provider="auto", model="" — keeps other fields intact.
            for slot in _AUX_TASK_SLOTS:
                slot_cfg = aux.get(slot)
                if not isinstance(slot_cfg, dict):
                    slot_cfg = {}
                slot_cfg["provider"] = "auto"
                slot_cfg["model"] = ""
                aux[slot] = slot_cfg
            cfg["auxiliary"] = aux
            save_config(cfg)
            return {"ok": True, "scope": "auxiliary", "reset": True}

        if not provider:
            raise HTTPException(status_code=400, detail="provider required for auxiliary")

        targets = [task] if task else list(_AUX_TASK_SLOTS)
        for slot in targets:
            if slot not in _AUX_TASK_SLOTS:
                raise HTTPException(status_code=400, detail=f"unknown auxiliary task: {slot}")
            slot_cfg = aux.get(slot)
            if not isinstance(slot_cfg, dict):
                slot_cfg = {}
            slot_cfg["provider"] = provider
            slot_cfg["model"] = model
            aux[slot] = slot_cfg

        cfg["auxiliary"] = aux
        save_config(cfg)
        return {
            "ok": True,
            "scope": "auxiliary",
            "tasks": targets,
            "provider": provider,
            "model": model,
        }
    except HTTPException:
        raise
    except Exception:
        _log.exception("POST /api/model/set failed")
        raise HTTPException(status_code=500, detail="Failed to save model assignment")




def _denormalize_config_from_web(config: Dict[str, Any]) -> Dict[str, Any]:
    """Reverse _normalize_config_for_web before saving.

    Reconstructs ``model`` as a dict by reading the current on-disk config
    to recover model subkeys (provider, base_url, api_mode, etc.) that were
    stripped from the GET response.  The frontend only sees model as a flat
    string; the rest is preserved transparently.

    Also handles ``model_context_length`` — writes it back into the model dict
    as ``context_length``.  A value of 0 or absent means "auto-detect" (omitted
    from the dict so get_model_context_length() uses its normal resolution).
    """
    config = dict(config)
    # Remove any _model_meta that might have leaked in (shouldn't happen
    # with the stripped GET response, but be defensive)
    config.pop("_model_meta", None)

    # Extract and remove model_context_length before processing model
    ctx_override = config.pop("model_context_length", 0)
    if not isinstance(ctx_override, int):
        try:
            ctx_override = int(ctx_override)
        except (TypeError, ValueError):
            ctx_override = 0

    model_val = config.get("model")
    if isinstance(model_val, str) and model_val:
        # Read the current disk config to recover model subkeys
        try:
            disk_config = load_config()
            disk_model = disk_config.get("model")
            if isinstance(disk_model, dict):
                # Preserve all subkeys, update default with the new value
                disk_model["default"] = model_val
                # Write context_length into the model dict (0 = remove/auto)
                if ctx_override > 0:
                    disk_model["context_length"] = ctx_override
                else:
                    disk_model.pop("context_length", None)
                config["model"] = disk_model
            else:
                # Model was previously a bare string — upgrade to dict if
                # user is setting a context_length override
                if ctx_override > 0:
                    config["model"] = {
                        "default": model_val,
                        "context_length": ctx_override,
                    }
        except Exception:
            pass  # can't read disk config — just use the string form
    return config


@app.put("/api/config")
async def update_config(body: ConfigUpdate):
    try:
        save_config(_denormalize_config_from_web(body.config))
        return {"ok": True}
    except Exception:
        _log.exception("PUT /api/config failed")
        raise HTTPException(status_code=500, detail="Internal server error")


class GovernanceBaseline(BaseModel):
    terminal_allowed_roles: List[str] = ["operator"]
    terminal_approver_roles: List[str] = ["manager"]
    smart_approvals: bool = True


@app.post("/api/onboarding/apply-governance-baseline")
async def apply_governance_baseline(body: GovernanceBaseline, request: Request):
    """Apply the recommended corporate governance defaults in one action.

    Admin-gated (the auth middleware routes non-GET, non-whitelisted API paths
    to admin_roles). Sets the least-privilege posture the health check looks
    for, PRESERVING existing users, folder policies, roles, and team roots.
    Returns the resulting posture warnings so the admin immediately sees what
    is still missing (e.g. no folder policies yet under default deny).
    """
    # When dashboard auth is on, the middleware already routes this POST to
    # admin_roles; the explicit check is defense-in-depth. When auth is off
    # (loopback local mode) the operator is the trust authority — mirror the
    # config/folder-policy endpoints and allow it.
    if _dashboard_auth_enabled() and not _dashboard_actor_is_admin(request):
        raise HTTPException(
            status_code=403,
            detail="Applying the governance baseline requires an admin dashboard role.",
        )

    cfg = load_config()
    governance = cfg.get("governance", {})
    governance = dict(governance) if isinstance(governance, dict) else {}

    governance["enabled"] = True
    governance["default_file_policy"] = "deny"

    terminal = governance.get("terminal", {})
    terminal = dict(terminal) if isinstance(terminal, dict) else {}
    terminal["allowed_roles"] = list(body.terminal_allowed_roles or [])
    terminal["approver_roles"] = list(body.terminal_approver_roles or [])
    governance["terminal"] = terminal
    cfg["governance"] = governance

    observability = cfg.get("observability", {})
    observability = dict(observability) if isinstance(observability, dict) else {}
    observability["enabled"] = True
    observability["audit_log_enabled"] = True
    cfg["observability"] = observability

    if body.smart_approvals:
        approvals = cfg.get("approvals", {})
        approvals = dict(approvals) if isinstance(approvals, dict) else {}
        approvals["mode"] = "smart"
        cfg["approvals"] = approvals

    try:
        save_config(cfg)
    except Exception:
        _log.exception("POST /api/onboarding/apply-governance-baseline failed")
        raise HTTPException(status_code=500, detail="Could not save the governance baseline.")

    _audit_dashboard_event(
        "governance.baseline_applied",
        request=request,
        action="onboarding.apply_governance_baseline",
        resource="governance",
        outcome="success",
        metadata={
            "terminal_allowed_roles": terminal["allowed_roles"],
            "terminal_approver_roles": terminal["approver_roles"],
            "smart_approvals": bool(body.smart_approvals),
        },
    )

    warnings: list = []
    try:
        from agent.governance import governance_posture_warnings

        warnings = governance_posture_warnings()
    except Exception:
        warnings = []

    return {
        "ok": True,
        "applied": {
            "governance.enabled": True,
            "governance.default_file_policy": "deny",
            "governance.terminal.allowed_roles": terminal["allowed_roles"],
            "governance.terminal.approver_roles": terminal["approver_roles"],
            "observability.audit_log_enabled": True,
            "approvals.mode": "smart" if body.smart_approvals else None,
        },
        "warnings": warnings,
    }


# Env vars that mean a messaging platform is wired up. Mirrors the token
# detection in scripts/install.sh plus the Mattermost/Matrix forms on the
# Gateway page.
_GATEWAY_TOKEN_ENV_VARS = (
    "TELEGRAM_BOT_TOKEN",
    "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "MATTERMOST_TOKEN",
    "MATRIX_ACCESS_TOKEN",
    "MATRIX_PASSWORD",
)


@app.get("/api/onboarding/state")
def get_onboarding_state():
    """Aggregated first-run setup state for the dashboard onboarding flow.

    The SPA root route calls this to decide whether to land on Onboarding
    (no working model provider yet) or Sessions, and the Onboarding page
    uses it to mark steps done/pending and to render the inline provider
    step (providers_catalog).
    """
    try:
        from hermes_cli.auth import PROVIDER_REGISTRY
        from hermes_cli.model_switch import list_authenticated_providers
        from hermes_cli.models import CANONICAL_PROVIDERS

        # Provider authentication checks read os.environ — refresh from .env
        # so keys saved moments ago count without a server restart.
        try:
            from hermes_cli.config import reload_env

            reload_env()
        except Exception:
            pass

        cfg = load_config()
        model_cfg = cfg.get("model", {})
        if isinstance(model_cfg, dict):
            current_model = model_cfg.get("default", model_cfg.get("name", "")) or ""
            current_provider = model_cfg.get("provider", "") or ""
            current_base_url = model_cfg.get("base_url", "") or ""
        else:
            current_model = str(model_cfg) if model_cfg else ""
            current_provider = ""
            current_base_url = ""

        user_providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
        custom_providers = (
            cfg.get("custom_providers")
            if isinstance(cfg.get("custom_providers"), list)
            else []
        )
        try:
            authenticated = list_authenticated_providers(
                current_provider=current_provider,
                current_base_url=current_base_url,
                current_model=current_model,
                user_providers=user_providers,
                custom_providers=custom_providers,
                max_models=1,
            )
        except Exception:
            authenticated = []

        env_on_disk = load_env()
        gateway_configured = any(env_on_disk.get(var) for var in _GATEWAY_TOKEN_ENV_VARS)
        if not gateway_configured:
            gateway_configured = (
                str(env_on_disk.get("WHATSAPP_ENABLED", "")).strip().lower() == "true"
            )

        governance_cfg = (
            cfg.get("governance", {}) if isinstance(cfg.get("governance"), dict) else {}
        )
        dashboard_cfg = (
            cfg.get("dashboard", {}) if isinstance(cfg.get("dashboard"), dict) else {}
        )
        auth_cfg = (
            dashboard_cfg.get("auth", {})
            if isinstance(dashboard_cfg.get("auth"), dict)
            else {}
        )
        agent_cfg = cfg.get("agent", {}) if isinstance(cfg.get("agent"), dict) else {}

        # Catalog for the inline provider step: canonical picker order, with
        # the primary API-key env var when the provider authenticates by key.
        # openrouter predates PROVIDER_REGISTRY (legacy code path), so its
        # env var is filled in explicitly.
        registry_gaps = {"openrouter": "OPENROUTER_API_KEY"}
        catalog = []
        for entry in CANONICAL_PROVIDERS:
            pcfg = PROVIDER_REGISTRY.get(entry.slug)
            env_vars = tuple(getattr(pcfg, "api_key_env_vars", ()) or ()) if pcfg else ()
            auth_type = getattr(pcfg, "auth_type", "api_key") if pcfg else "api_key"
            env_key = env_vars[0] if env_vars else registry_gaps.get(entry.slug)
            catalog.append({
                "slug": entry.slug,
                "label": entry.label,
                "description": entry.tui_desc,
                "env_key": env_key,
                "auth_type": auth_type,
            })

        from hermes_constants import VALID_REASONING_EFFORTS

        return {
            "provider_configured": bool(authenticated),
            "current_provider": current_provider,
            "current_model": current_model,
            "current_effort": str(agent_cfg.get("reasoning_effort", "") or ""),
            "valid_efforts": list(VALID_REASONING_EFFORTS),
            "gateway_configured": bool(gateway_configured),
            "governance_configured": bool(governance_cfg.get("enabled")),
            "dashboard_auth_configured": bool(auth_cfg.get("enabled")),
            "providers_catalog": catalog,
        }
    except Exception:
        _log.exception("GET /api/onboarding/state failed")
        raise HTTPException(status_code=500, detail="Failed to read onboarding state")


class ReasoningEffortBody(BaseModel):
    effort: str = ""


@app.post("/api/model/effort")
async def set_reasoning_effort(body: ReasoningEffortBody):
    """Set agent.reasoning_effort. Empty string clears it (provider default)."""
    from hermes_constants import VALID_REASONING_EFFORTS

    effort = (body.effort or "").strip().lower()
    if effort and effort not in VALID_REASONING_EFFORTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"effort must be empty (auto) or one of: "
                f"{', '.join(VALID_REASONING_EFFORTS)}"
            ),
        )
    cfg = load_config()
    agent_cfg = cfg.get("agent", {})
    agent_cfg = dict(agent_cfg) if isinstance(agent_cfg, dict) else {}
    if effort:
        agent_cfg["reasoning_effort"] = effort
    else:
        agent_cfg.pop("reasoning_effort", None)
    cfg["agent"] = agent_cfg
    try:
        save_config(cfg)
    except Exception:
        _log.exception("POST /api/model/effort failed")
        raise HTTPException(status_code=500, detail="Could not save reasoning effort")
    return {"ok": True, "effort": effort}


@app.get("/api/governance/folder-policies")
async def get_folder_policies(request: Request):
    cfg = load_config()
    governance = cfg.get("governance", {}) if isinstance(cfg.get("governance"), dict) else {}
    admin = _dashboard_actor_is_admin(request)
    managed_roots = _manageable_team_roots(request, governance)

    policies = [
        _normalise_folder_policy(policy)
        for policy in governance.get("folder_policies", [])
        if isinstance(policy, dict)
    ]
    if not admin:
        policies = [
            policy for policy in policies
            if _policy_matches_any_team_root(policy, managed_roots)
        ]

    return {
        "enabled": bool(governance.get("enabled")),
        "default_file_policy": governance.get("default_file_policy", "allow"),
        "folder_policies": policies,
        "team_file_roots": _team_root_entries(governance) if admin else {
            team: {"path": str(path)}
            for team, path in managed_roots.items()
        },
        "actor": {
            "teams": _dashboard_actor_teams(request, governance),
            "can_admin": admin,
            "managed_teams": sorted(managed_roots.keys()),
        },
    }


@app.put("/api/governance/folder-policies")
async def update_folder_policies(body: FolderPoliciesUpdate, request: Request):
    cfg = load_config()
    governance = cfg.get("governance", {}) if isinstance(cfg.get("governance"), dict) else {}
    governance = dict(governance)
    admin = _dashboard_actor_is_admin(request)
    incoming = [
        _normalise_folder_policy(policy)
        for policy in body.folder_policies
        if isinstance(policy, dict)
    ]

    for policy in incoming:
        if not policy.get("path"):
            raise HTTPException(status_code=400, detail="Every folder policy needs a path.")

    if admin:
        if body.default_file_policy is not None:
            value = str(body.default_file_policy).strip().lower()
            if value not in {"allow", "deny"}:
                raise HTTPException(status_code=400, detail="default_file_policy must be allow or deny.")
            governance["default_file_policy"] = value
        if body.team_file_roots is not None:
            governance["team_file_roots"] = body.team_file_roots
        governance["folder_policies"] = incoming
    else:
        managed_roots = _manageable_team_roots(request, governance)
        if not managed_roots:
            raise HTTPException(status_code=403, detail="No team file roots are delegated to this dashboard user.")
        actor_teams = sorted(managed_roots.keys())
        allowed_user_keys = _governance_user_keys_by_team(governance, actor_teams)
        for policy in incoming:
            _validate_team_managed_policy(
                policy,
                managed_roots=managed_roots,
                allowed_user_keys=allowed_user_keys,
            )

        current = [
            _normalise_folder_policy(policy)
            for policy in governance.get("folder_policies", [])
            if isinstance(policy, dict)
        ]
        retained = [
            policy for policy in current
            if not _policy_matches_any_team_root(policy, managed_roots)
        ]
        governance["folder_policies"] = retained + incoming

    cfg["governance"] = governance
    try:
        save_config(cfg)
    except Exception:
        _log.exception("PUT /api/governance/folder-policies failed")
        raise HTTPException(status_code=500, detail="Could not save folder policies.")

    _audit_dashboard_event(
        "governance.folder_policies_updated",
        request=request,
        action="folder_policies.update",
        resource="governance.folder_policies",
        outcome="success",
        metadata={
            "policy_count": len(governance.get("folder_policies", [])),
            "admin": admin,
            "managed_teams": sorted(_manageable_team_roots(request, governance).keys()),
        },
    )
    return {
        "ok": True,
        "folder_policies": governance.get("folder_policies", []),
        "default_file_policy": governance.get("default_file_policy", "allow"),
    }


def _governance_role_options() -> List[str]:
    """Selectable governance roles: configured role_hierarchy or defaults."""
    cfg = load_config()
    governance = cfg.get("governance", {}) if isinstance(cfg, dict) else {}
    hierarchy = governance.get("role_hierarchy") if isinstance(governance, dict) else None
    roles: List[str] = []
    if isinstance(hierarchy, list):
        for entry in hierarchy:
            name = str(entry or "").strip()
            if name and name not in roles:
                roles.append(name)
    return roles or ["viewer", "operator", "manager", "admin"]


def _governance_team_options() -> List[str]:
    """Every team name referenced anywhere in governance config.

    Teams are freeform labels: one exists as soon as a user, a delegated
    team root, or a folder policy references it. Collected here so the
    dashboard can suggest existing spellings instead of forcing recall.
    """
    cfg = load_config()
    governance = cfg.get("governance", {}) if isinstance(cfg, dict) else {}
    if not isinstance(governance, dict):
        governance = {}
    teams: List[str] = []
    seen: set[str] = set()

    def _add(value: Any) -> None:
        name = str(value or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            teams.append(name)

    roots = governance.get("team_file_roots")
    if isinstance(roots, dict):
        for team in roots:
            _add(team)
    users = governance.get("users")
    if isinstance(users, dict):
        for record in users.values():
            if isinstance(record, dict):
                for team in _coerce_role_list(record.get("teams") or record.get("team")):
                    _add(team)
    policies = governance.get("folder_policies")
    if isinstance(policies, list):
        for policy in policies:
            if isinstance(policy, dict):
                for key in ("read_teams", "write_teams"):
                    for team in _coerce_role_list(policy.get(key)):
                        _add(team)
    return sorted(teams, key=str.lower)


@app.get("/api/governance/options")
async def get_governance_options():
    """Selectable governance vocabulary for dashboard forms.

    ``roles`` is the configured role_hierarchy (or the default set) and
    ``teams`` is every team name referenced anywhere in governance, so
    forms can offer dropdowns/suggestions instead of free-typed commas.
    """
    return {
        "roles": _governance_role_options(),
        "teams": _governance_team_options(),
    }


@app.get("/api/gateway/{platform}/access-users")
async def get_gateway_access_users(platform: str):
    """Managed allowlist and read-only Governance status for a platform.

    Same contract for discord/slack/mattermost/matrix (the old
    discord-only route is the discord case of this one). New allowlist users
    remain pending until an administrator grants a role in Governance. The
    first user on a completely fresh installation is bootstrapped as admin.
    """
    return {
        "users": _load_gateway_access_users(platform),
        "roles": _governance_role_options(),
        "teams": _governance_team_options(),
    }


@app.put("/api/gateway/{platform}/access-users")
async def set_gateway_access_users(
    platform: str, body: DiscordGatewayAccessUsersUpdate, request: Request
):
    users = _save_gateway_access_users(platform, body.users)
    _audit_dashboard_event(
        f"gateway.{str(platform).lower()}_access_users",
        request=request,
        actor=_request_dashboard_actor(request),
        action="save",
        resource=f"{str(platform).lower()}_gateway_access",
        outcome="success",
        metadata={"platform": str(platform).lower(), "user_count": len(users)},
    )
    return {"ok": True, "users": users}


@app.get("/api/env")
async def get_env_vars():
    env_on_disk = load_env()
    result = {}
    for var_name, info in OPTIONAL_ENV_VARS.items():
        value = env_on_disk.get(var_name)
        result[var_name] = {
            "is_set": bool(value),
            "redacted_value": redact_key(value) if value else None,
            "description": info.get("description", ""),
            "url": info.get("url"),
            "category": info.get("category", ""),
            "is_password": info.get("password", False),
            "tools": info.get("tools", []),
            "advanced": info.get("advanced", False),
        }
    return result


@app.put("/api/env")
async def set_env_var(body: EnvVarUpdate):
    try:
        save_env_value(body.key, body.value)
        # Provider authentication checks read os.environ, so refresh it —
        # otherwise a key saved here only counts after a server restart.
        try:
            from hermes_cli.config import reload_env

            reload_env()
        except Exception:
            _log.warning("PUT /api/env: reload_env failed", exc_info=True)
        return {"ok": True, "key": body.key}
    except Exception:
        _log.exception("PUT /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/api/env")
async def remove_env_var(body: EnvVarDelete):
    try:
        removed = remove_env_value(body.key)
        if not removed:
            raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")
        os.environ.pop(body.key, None)
        return {"ok": True, "key": body.key}
    except HTTPException:
        raise
    except Exception:
        _log.exception("DELETE /api/env failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/env/reveal")
async def reveal_env_var(body: EnvVarReveal, request: Request):
    """Return the real (unredacted) value of a single env var.

    Protected by:
    - Ephemeral session token (generated per server start, injected into SPA)
    - Rate limiting (max 5 reveals per 30s window)
    - Audit logging
    """
    # --- Token check ---
    _require_token(request)

    # --- Rate limit ---
    now = time.time()
    cutoff = now - _REVEAL_WINDOW_SECONDS
    _reveal_timestamps[:] = [t for t in _reveal_timestamps if t > cutoff]
    if len(_reveal_timestamps) >= _REVEAL_MAX_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many reveal requests. Try again shortly.")
    _reveal_timestamps.append(now)

    # --- Reveal ---
    env_on_disk = load_env()
    value = env_on_disk.get(body.key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"{body.key} not found in .env")

    _log.info("env/reveal: %s", body.key)
    return {"key": body.key, "value": value}


# ---------------------------------------------------------------------------
# OAuth provider endpoints — status + disconnect (Phase 1)
# ---------------------------------------------------------------------------
#
# Phase 1 surfaces *which OAuth providers exist* and whether each is
# connected, plus a disconnect button. The actual login flow (PKCE for
# Anthropic, device-code for Nous/Codex) still runs in the CLI for now;
# Phase 2 will add in-browser flows. For unconnected providers we return
# the canonical ``hermes auth add <provider>`` command so the dashboard
# can surface a one-click copy.


def _truncate_token(value: Optional[str], visible: int = 6) -> str:
    """Return ``...XXXXXX`` (last N chars) for safe display in the UI.

    We never expose more than the trailing ``visible`` characters of an
    OAuth access token. JWT prefixes (the part before the first dot) are
    stripped first when present so the visible suffix is always part of
    the signing region rather than a meaningless header chunk.
    """
    if not value:
        return ""
    s = str(value)
    if "." in s and s.count(".") >= 2:
        # Looks like a JWT — show the trailing piece of the signature only.
        s = s.rsplit(".", 1)[-1]
    if len(s) <= visible:
        return s
    return f"…{s[-visible:]}"


def _anthropic_oauth_status() -> Dict[str, Any]:
    """Combined status across the three Anthropic credential sources we read.

    Hermes resolves Anthropic creds in this order at runtime:
    1. ``~/.hermes/.anthropic_oauth.json`` — Hermes-managed PKCE flow
    2. ``~/.claude/.credentials.json`` — Claude Code CLI credentials (auto)
    3. ``ANTHROPIC_TOKEN`` / ``ANTHROPIC_API_KEY`` env vars
    The dashboard reports the highest-priority source that's actually present.
    """
    try:
        from agent.anthropic_adapter import (
            read_hermes_oauth_credentials,
            read_claude_code_credentials,
            _HERMES_OAUTH_FILE,
        )
    except ImportError:
        read_claude_code_credentials = None  # type: ignore
        read_hermes_oauth_credentials = None  # type: ignore
        _HERMES_OAUTH_FILE = None  # type: ignore

    hermes_creds = None
    if read_hermes_oauth_credentials:
        try:
            hermes_creds = read_hermes_oauth_credentials()
        except Exception:
            hermes_creds = None
    if hermes_creds and hermes_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "hermes_pkce",
            "source_label": f"Hermes PKCE ({_HERMES_OAUTH_FILE})",
            "token_preview": _truncate_token(hermes_creds.get("accessToken")),
            "expires_at": hermes_creds.get("expiresAt"),
            "has_refresh_token": bool(hermes_creds.get("refreshToken")),
        }

    cc_creds = None
    if read_claude_code_credentials:
        try:
            cc_creds = read_claude_code_credentials()
        except Exception:
            cc_creds = None
    if cc_creds and cc_creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code",
            "source_label": "Claude Code (~/.claude/.credentials.json)",
            "token_preview": _truncate_token(cc_creds.get("accessToken")),
            "expires_at": cc_creds.get("expiresAt"),
            "has_refresh_token": bool(cc_creds.get("refreshToken")),
        }

    env_token = os.getenv("ANTHROPIC_TOKEN") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if env_token:
        return {
            "logged_in": True,
            "source": "env_var",
            "source_label": "ANTHROPIC_TOKEN environment variable",
            "token_preview": _truncate_token(env_token),
            "expires_at": None,
            "has_refresh_token": False,
        }
    return {"logged_in": False, "source": None}


def _claude_code_only_status() -> Dict[str, Any]:
    """Surface Claude Code CLI credentials as their own provider entry.

    Independent of the Anthropic entry above so users can see whether their
    Claude Code subscription tokens are actively flowing into Hermes even
    when they also have a separate Hermes-managed PKCE login.
    """
    try:
        from agent.anthropic_adapter import read_claude_code_credentials
        creds = read_claude_code_credentials()
    except Exception:
        creds = None
    if creds and creds.get("accessToken"):
        return {
            "logged_in": True,
            "source": "claude_code_cli",
            "source_label": "~/.claude/.credentials.json",
            "token_preview": _truncate_token(creds.get("accessToken")),
            "expires_at": creds.get("expiresAt"),
            "has_refresh_token": bool(creds.get("refreshToken")),
        }
    return {"logged_in": False, "source": None}


# Provider catalog. The order matters — it's how we render the UI list.
# ``cli_command`` is what the dashboard surfaces as the copy-to-clipboard
# fallback while Phase 2 (in-browser flows) isn't built yet.
# ``flow`` describes the OAuth shape so the future modal can pick the
# right UI: ``pkce`` = open URL + paste callback code, ``device_code`` =
# show code + verification URL + poll, ``external`` = read-only (delegated
# to a third-party CLI like Claude Code or Qwen).
_OAUTH_PROVIDER_CATALOG: tuple[Dict[str, Any], ...] = (
    {
        "id": "anthropic",
        "name": "Anthropic (Claude API)",
        "flow": "pkce",
        "cli_command": "hermes auth add anthropic",
        "docs_url": "https://docs.claude.com/en/api/getting-started",
        "status_fn": _anthropic_oauth_status,
    },
    {
        "id": "claude-code",
        "name": "Claude Code (subscription)",
        "flow": "external",
        "cli_command": "claude setup-token",
        "docs_url": "https://docs.claude.com/en/docs/claude-code",
        "status_fn": _claude_code_only_status,
    },
    {
        "id": "openai-codex",
        "name": "OpenAI Codex (ChatGPT)",
        "flow": "device_code",
        "cli_command": "hermes auth add openai-codex",
        "docs_url": "https://platform.openai.com/docs",
        "status_fn": None,  # dispatched via auth.get_codex_auth_status
    },
    {
        "id": "qwen-oauth",
        "name": "Qwen (via Qwen CLI)",
        "flow": "external",
        "cli_command": "hermes auth add qwen-oauth",
        "docs_url": "https://github.com/QwenLM/qwen-code",
        "status_fn": None,  # dispatched via auth.get_qwen_auth_status
    },
    {
        "id": "minimax-oauth",
        "name": "MiniMax (OAuth)",
        "flow": "pkce",
        "cli_command": "hermes auth add minimax-oauth",
        "docs_url": "https://www.minimax.io",
        "status_fn": None,  # dispatched via auth.get_minimax_oauth_auth_status
    },
)


def _resolve_provider_status(provider_id: str, status_fn) -> Dict[str, Any]:
    """Dispatch to the right status helper for an OAuth provider entry."""
    if status_fn is not None:
        try:
            return status_fn()
        except Exception as e:
            return {"logged_in": False, "error": str(e)}
    try:
        from hermes_cli import auth as hauth
        if provider_id == "nous":
            raw = hauth.get_nous_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "nous_portal",
                "source_label": raw.get("portal_base_url") or "Nous Portal",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("access_expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "openai-codex":
            raw = hauth.get_codex_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": raw.get("source") or "openai_codex",
                "source_label": raw.get("auth_mode") or "OpenAI Codex",
                "token_preview": _truncate_token(raw.get("api_key")),
                "expires_at": None,
                "has_refresh_token": False,
                "last_refresh": raw.get("last_refresh"),
            }
        if provider_id == "qwen-oauth":
            raw = hauth.get_qwen_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "qwen_cli",
                "source_label": raw.get("auth_store_path") or "Qwen CLI",
                "token_preview": _truncate_token(raw.get("access_token")),
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": bool(raw.get("has_refresh_token")),
            }
        if provider_id == "minimax-oauth":
            raw = hauth.get_minimax_oauth_auth_status()
            return {
                "logged_in": bool(raw.get("logged_in")),
                "source": "minimax_oauth",
                "source_label": f"MiniMax ({raw.get('region', 'global')})",
                "token_preview": None,
                "expires_at": raw.get("expires_at"),
                "has_refresh_token": True,
            }
    except Exception as e:
        return {"logged_in": False, "error": str(e)}
    return {"logged_in": False}


@app.get("/api/providers/oauth")
async def list_oauth_providers():
    """Enumerate every OAuth-capable LLM provider with current status.

    Response shape (per provider):
        id              stable identifier (used in DELETE path)
        name            human label
        flow            "pkce" | "device_code" | "external"
        cli_command     fallback CLI command for users to run manually
        docs_url        external docs/portal link for the "Learn more" link
        status:
          logged_in        bool — currently has usable creds
          source           short slug ("hermes_pkce", "claude_code", ...)
          source_label     human-readable origin (file path, env var name)
          token_preview    last N chars of the token, never the full token
          expires_at       ISO timestamp string or null
          has_refresh_token bool
    """
    providers = []
    for p in _OAUTH_PROVIDER_CATALOG:
        status = _resolve_provider_status(p["id"], p.get("status_fn"))
        providers.append({
            "id": p["id"],
            "name": p["name"],
            "flow": p["flow"],
            "cli_command": p["cli_command"],
            "docs_url": p["docs_url"],
            "status": status,
        })
    return {"providers": providers}


@app.delete("/api/providers/oauth/{provider_id}")
async def disconnect_oauth_provider(provider_id: str, request: Request):
    """Disconnect an OAuth provider. Token-protected (matches /env/reveal)."""
    _require_token(request)

    valid_ids = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider_id}. "
                   f"Available: {', '.join(sorted(valid_ids))}",
        )

    # Anthropic and claude-code clear the same Hermes-managed PKCE file
    # AND forget the Claude Code import. We don't touch ~/.claude/* directly
    # — that's owned by the Claude Code CLI; users can re-auth there if they
    # want to undo a disconnect.
    if provider_id in ("anthropic", "claude-code"):
        try:
            from agent.anthropic_adapter import _HERMES_OAUTH_FILE
            if _HERMES_OAUTH_FILE.exists():
                _HERMES_OAUTH_FILE.unlink()
        except Exception:
            pass
        # Also clear the credential pool entry if present.
        try:
            from hermes_cli.auth import clear_provider_auth
            clear_provider_auth("anthropic")
        except Exception:
            pass
        _log.info("oauth/disconnect: %s", provider_id)
        return {"ok": True, "provider": provider_id}

    try:
        from hermes_cli.auth import clear_provider_auth
        cleared = clear_provider_auth(provider_id)
        _log.info("oauth/disconnect: %s (cleared=%s)", provider_id, cleared)
        return {"ok": bool(cleared), "provider": provider_id}
    except Exception as e:
        _log.exception("disconnect %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# OAuth Phase 2 — in-browser PKCE & device-code flows
# ---------------------------------------------------------------------------
#
# Two flow shapes are supported:
#
#   PKCE (Anthropic):
#     1. POST /api/providers/oauth/anthropic/start
#          → server generates code_verifier + challenge, builds claude.ai
#            authorize URL, stashes verifier in _oauth_sessions[session_id]
#          → returns { session_id, flow: "pkce", auth_url }
#     2. UI opens auth_url in a new tab. User authorizes, copies code.
#     3. POST /api/providers/oauth/anthropic/submit { session_id, code }
#          → server exchanges (code + verifier) → tokens at console.anthropic.com
#          → persists to ~/.hermes/.anthropic_oauth.json AND credential pool
#          → returns { ok: true, status: "approved" }
#
#   Device code (Nous, OpenAI Codex):
#     1. POST /api/providers/oauth/{nous|openai-codex}/start
#          → server hits provider's device-auth endpoint
#          → gets { user_code, verification_url, device_code, interval, expires_in }
#          → spawns background poller thread that polls the token endpoint
#            every `interval` seconds until approved/expired
#          → stores poll status in _oauth_sessions[session_id]
#          → returns { session_id, flow: "device_code", user_code,
#                      verification_url, expires_in, poll_interval }
#     2. UI opens verification_url in a new tab and shows user_code.
#     3. UI polls GET /api/providers/oauth/{provider}/poll/{session_id}
#          every 2s until status != "pending".
#     4. On "approved" the background thread has already saved creds; UI
#        refreshes the providers list.
#
# Sessions are kept in-memory only (single-process FastAPI) and time out
# after 15 minutes. A periodic cleanup runs on each /start call to GC
# expired sessions so the dict doesn't grow without bound.

_OAUTH_SESSION_TTL_SECONDS = 15 * 60
_oauth_sessions: Dict[str, Dict[str, Any]] = {}
_oauth_sessions_lock = threading.Lock()

# Import OAuth constants from canonical source instead of duplicating.
# Guarded so hermes web still starts if anthropic_adapter is unavailable;
# Phase 2 endpoints will return 501 in that case.
try:
    from agent.anthropic_adapter import (
        _OAUTH_CLIENT_ID as _ANTHROPIC_OAUTH_CLIENT_ID,
        _OAUTH_TOKEN_URL as _ANTHROPIC_OAUTH_TOKEN_URL,
        _OAUTH_REDIRECT_URI as _ANTHROPIC_OAUTH_REDIRECT_URI,
        _OAUTH_SCOPES as _ANTHROPIC_OAUTH_SCOPES,
        _generate_pkce as _generate_pkce_pair,
    )
    _ANTHROPIC_OAUTH_AVAILABLE = True
except ImportError:
    _ANTHROPIC_OAUTH_AVAILABLE = False
_ANTHROPIC_OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"


def _gc_oauth_sessions() -> None:
    """Drop expired sessions. Called opportunistically on /start."""
    cutoff = time.time() - _OAUTH_SESSION_TTL_SECONDS
    with _oauth_sessions_lock:
        stale = [sid for sid, sess in _oauth_sessions.items() if sess["created_at"] < cutoff]
        for sid in stale:
            _oauth_sessions.pop(sid, None)


def _new_oauth_session(provider_id: str, flow: str) -> tuple[str, Dict[str, Any]]:
    """Create + register a new OAuth session, return (session_id, session_dict)."""
    sid = secrets.token_urlsafe(16)
    sess = {
        "session_id": sid,
        "provider": provider_id,
        "flow": flow,
        "created_at": time.time(),
        "status": "pending",  # pending | approved | denied | expired | error
        "error_message": None,
    }
    with _oauth_sessions_lock:
        _oauth_sessions[sid] = sess
    return sid, sess


def _save_anthropic_oauth_creds(access_token: str, refresh_token: str, expires_at_ms: int) -> None:
    """Persist Anthropic PKCE creds to both Hermes file AND credential pool.

    Mirrors what auth_commands.add_command does so the dashboard flow leaves
    the system in the same state as ``hermes auth add anthropic``.
    """
    from agent.anthropic_adapter import _HERMES_OAUTH_FILE
    payload = {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
    }
    _HERMES_OAUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HERMES_OAUTH_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Best-effort credential-pool insert. Failure here doesn't invalidate
    # the file write — pool registration only matters for the rotation
    # strategy, not for runtime credential resolution.
    try:
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid
        pool = load_pool("anthropic")
        # Avoid duplicate entries: delete any prior dashboard-issued OAuth entry
        existing = [e for e in pool.entries() if getattr(e, "source", "").startswith(f"{SOURCE_MANUAL}:dashboard_pkce")]
        for e in existing:
            try:
                pool.remove_entry(getattr(e, "id", ""))
            except Exception:
                pass
        entry = PooledCredential(
            provider="anthropic",
            id=uuid.uuid4().hex[:6],
            label="dashboard PKCE",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_pkce",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_ms=expires_at_ms,
        )
        pool.add_entry(entry)
    except Exception as e:
        _log.warning("anthropic pool add (dashboard) failed: %s", e)


def _start_anthropic_pkce() -> Dict[str, Any]:
    """Begin PKCE flow. Returns the auth URL the UI should open."""
    if not _ANTHROPIC_OAUTH_AVAILABLE:
        raise HTTPException(status_code=501, detail="Anthropic OAuth not available (missing adapter)")
    verifier, challenge = _generate_pkce_pair()
    sid, sess = _new_oauth_session("anthropic", "pkce")
    sess["verifier"] = verifier
    sess["state"] = verifier  # Anthropic round-trips verifier as state
    params = {
        "code": "true",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "scope": _ANTHROPIC_OAUTH_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": verifier,
    }
    auth_url = f"{_ANTHROPIC_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return {
        "session_id": sid,
        "flow": "pkce",
        "auth_url": auth_url,
        "expires_in": _OAUTH_SESSION_TTL_SECONDS,
    }


def _submit_anthropic_pkce(session_id: str, code_input: str) -> Dict[str, Any]:
    """Exchange authorization code for tokens. Persists on success."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess or sess["provider"] != "anthropic" or sess["flow"] != "pkce":
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    if sess["status"] != "pending":
        return {"ok": False, "status": sess["status"], "message": sess.get("error_message")}

    # Anthropic's redirect callback page formats the code as `<code>#<state>`.
    # Strip the state suffix if present (we already have the verifier server-side).
    parts = code_input.strip().split("#", 1)
    code = parts[0].strip()
    if not code:
        return {"ok": False, "status": "error", "message": "No code provided"}
    state_from_callback = parts[1] if len(parts) > 1 else ""

    exchange_data = json.dumps({
        "grant_type": "authorization_code",
        "client_id": _ANTHROPIC_OAUTH_CLIENT_ID,
        "code": code,
        "state": state_from_callback or sess["state"],
        "redirect_uri": _ANTHROPIC_OAUTH_REDIRECT_URI,
        "code_verifier": sess["verifier"],
    }).encode()
    req = urllib.request.Request(
        _ANTHROPIC_OAUTH_TOKEN_URL,
        data=exchange_data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "hermes-dashboard/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = f"Token exchange failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    access_token = result.get("access_token", "")
    refresh_token = result.get("refresh_token", "")
    expires_in = int(result.get("expires_in") or 3600)
    if not access_token:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = "No access token returned"
        return {"ok": False, "status": "error", "message": sess["error_message"]}

    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000)
    try:
        _save_anthropic_oauth_creds(access_token, refresh_token, expires_at_ms)
    except Exception as e:
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = f"Save failed: {e}"
        return {"ok": False, "status": "error", "message": sess["error_message"]}
    with _oauth_sessions_lock:
        sess["status"] = "approved"
    _log.info("oauth/pkce: anthropic login completed (session=%s)", session_id)
    return {"ok": True, "status": "approved"}


async def _start_device_code_flow(provider_id: str) -> Dict[str, Any]:
    """Initiate a device-code flow (Nous or OpenAI Codex).

    Calls the provider's device-auth endpoint via the existing CLI helpers,
    then spawns a background poller. Returns the user-facing display fields
    so the UI can render the verification page link + user code.
    """
    if provider_id == "nous":
        from hermes_cli.auth import _request_device_code, PROVIDER_REGISTRY
        import httpx
        pconfig = PROVIDER_REGISTRY["nous"]
        portal_base_url = (
            os.getenv("HERMES_PORTAL_BASE_URL")
            or os.getenv("NOUS_PORTAL_BASE_URL")
            or pconfig.portal_base_url
        ).rstrip("/")
        client_id = pconfig.client_id
        scope = pconfig.scope
        def _do_nous_device_request():
            with httpx.Client(timeout=httpx.Timeout(15.0), headers={"Accept": "application/json"}) as client:
                return _request_device_code(
                    client=client,
                    portal_base_url=portal_base_url,
                    client_id=client_id,
                    scope=scope,
                )
        device_data = await asyncio.get_event_loop().run_in_executor(None, _do_nous_device_request)
        sid, sess = _new_oauth_session("nous", "device_code")
        sess["device_code"] = str(device_data["device_code"])
        sess["interval"] = int(device_data["interval"])
        sess["expires_at"] = time.time() + int(device_data["expires_in"])
        sess["portal_base_url"] = portal_base_url
        sess["client_id"] = client_id
        threading.Thread(
            target=_nous_poller, args=(sid,), daemon=True, name=f"oauth-poll-{sid[:6]}"
        ).start()
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": str(device_data["user_code"]),
            "verification_url": str(device_data["verification_uri_complete"]),
            "expires_in": int(device_data["expires_in"]),
            "poll_interval": int(device_data["interval"]),
        }

    if provider_id == "openai-codex":
        # Codex uses fixed OpenAI device-auth endpoints; reuse the helper.
        sid, _ = _new_oauth_session("openai-codex", "device_code")
        # Use the helper but in a thread because it polls inline.
        # We can't extract just the start step without refactoring auth.py,
        # so we run the full helper in a worker and proxy the user_code +
        # verification_url back via the session dict. The helper prints
        # to stdout — we capture nothing here, just status.
        threading.Thread(
            target=_codex_full_login_worker, args=(sid,), daemon=True,
            name=f"oauth-codex-{sid[:6]}",
        ).start()
        # Block briefly until the worker has populated the user_code, OR error.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with _oauth_sessions_lock:
                s = _oauth_sessions.get(sid)
            if s and (s.get("user_code") or s["status"] != "pending"):
                break
            await asyncio.sleep(0.1)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(sid, {})
        if s.get("status") == "error":
            raise HTTPException(status_code=500, detail=s.get("error_message") or "device-auth failed")
        if not s.get("user_code"):
            raise HTTPException(status_code=504, detail="device-auth timed out before returning a user code")
        return {
            "session_id": sid,
            "flow": "device_code",
            "user_code": s["user_code"],
            "verification_url": s["verification_url"],
            "expires_in": int(s.get("expires_in") or 900),
            "poll_interval": int(s.get("interval") or 5),
        }

    raise HTTPException(status_code=400, detail=f"Provider {provider_id} does not support device-code flow")


def _nous_poller(session_id: str) -> None:
    """Background poller that drives a Nous device-code flow to completion."""
    from hermes_cli.auth import _poll_for_token, refresh_nous_oauth_from_state
    from datetime import datetime, timezone
    import httpx
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        return
    portal_base_url = sess["portal_base_url"]
    client_id = sess["client_id"]
    device_code = sess["device_code"]
    interval = sess["interval"]
    expires_in = max(60, int(sess["expires_at"] - time.time()))
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0), headers={"Accept": "application/json"}) as client:
            token_data = _poll_for_token(
                client=client,
                portal_base_url=portal_base_url,
                client_id=client_id,
                device_code=device_code,
                expires_in=expires_in,
                poll_interval=interval,
            )
        # Same post-processing as _nous_device_code_login (mint agent key)
        now = datetime.now(timezone.utc)
        token_ttl = int(token_data.get("expires_in") or 0)
        auth_state = {
            "portal_base_url": portal_base_url,
            "inference_base_url": token_data.get("inference_base_url"),
            "client_id": client_id,
            "scope": token_data.get("scope"),
            "token_type": token_data.get("token_type", "Bearer"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "obtained_at": now.isoformat(),
            "expires_at": (
                datetime.fromtimestamp(now.timestamp() + token_ttl, tz=timezone.utc).isoformat()
                if token_ttl else None
            ),
            "expires_in": token_ttl,
        }
        full_state = refresh_nous_oauth_from_state(
            auth_state, min_key_ttl_seconds=300, timeout_seconds=15.0,
            force_refresh=False, force_mint=True,
        )
        from hermes_cli.auth import persist_nous_credentials
        persist_nous_credentials(full_state)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: nous login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("nous device-code poll failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            sess["status"] = "error"
            sess["error_message"] = str(e)


def _codex_full_login_worker(session_id: str) -> None:
    """Run the complete OpenAI Codex device-code flow.

    Codex doesn't use the standard OAuth device-code endpoints; it has its
    own ``/api/accounts/deviceauth/usercode`` (JSON body, returns
    ``device_auth_id``) and ``/api/accounts/deviceauth/token`` (JSON body
    polled until 200). On success the response carries an
    ``authorization_code`` + ``code_verifier`` that get exchanged at
    CODEX_OAUTH_TOKEN_URL with grant_type=authorization_code.

    The flow is replicated inline (rather than calling
    _codex_device_code_login) because that helper prints/blocks/polls in a
    single function — we need to surface the user_code to the dashboard the
    moment we receive it, well before polling completes.
    """
    try:
        import httpx
        from hermes_cli.auth import (
            CODEX_OAUTH_CLIENT_ID,
            CODEX_OAUTH_TOKEN_URL,
            DEFAULT_CODEX_BASE_URL,
        )
        issuer = "https://auth.openai.com"

        # Step 1: request device code
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": CODEX_OAUTH_CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"deviceauth/usercode returned {resp.status_code}")
        device_data = resp.json()
        user_code = device_data.get("user_code", "")
        device_auth_id = device_data.get("device_auth_id", "")
        poll_interval = max(3, int(device_data.get("interval", "5")))
        if not user_code or not device_auth_id:
            raise RuntimeError("device-code response missing user_code or device_auth_id")
        verification_url = f"{issuer}/codex/device"
        with _oauth_sessions_lock:
            sess = _oauth_sessions.get(session_id)
            if not sess:
                return
            sess["user_code"] = user_code
            sess["verification_url"] = verification_url
            sess["device_auth_id"] = device_auth_id
            sess["interval"] = poll_interval
            sess["expires_in"] = 15 * 60  # OpenAI's effective limit
            sess["expires_at"] = time.time() + sess["expires_in"]

        # Step 2: poll until authorized
        deadline = time.monotonic() + sess["expires_in"]
        code_resp = None
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while time.monotonic() < deadline:
                time.sleep(poll_interval)
                poll = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )
                if poll.status_code == 200:
                    code_resp = poll.json()
                    break
                if poll.status_code in (403, 404):
                    continue  # user hasn't authorized yet
                raise RuntimeError(f"deviceauth/token poll returned {poll.status_code}")

        if code_resp is None:
            with _oauth_sessions_lock:
                sess["status"] = "expired"
                sess["error_message"] = "Device code expired before approval"
            return

        # Step 3: exchange authorization_code for tokens
        authorization_code = code_resp.get("authorization_code", "")
        code_verifier = code_resp.get("code_verifier", "")
        if not authorization_code or not code_verifier:
            raise RuntimeError("device-auth response missing authorization_code/code_verifier")
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": f"{issuer}/deviceauth/callback",
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_resp.status_code != 200:
            raise RuntimeError(f"token exchange returned {token_resp.status_code}")
        tokens = token_resp.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        if not access_token:
            raise RuntimeError("token exchange did not return access_token")

        # Persist via credential pool — same shape as auth_commands.add_command
        from agent.credential_pool import (
            PooledCredential,
            load_pool,
            AUTH_TYPE_OAUTH,
            SOURCE_MANUAL,
        )
        import uuid as _uuid
        pool = load_pool("openai-codex")
        base_url = (
            os.getenv("HERMES_CODEX_BASE_URL", "").strip().rstrip("/")
            or DEFAULT_CODEX_BASE_URL
        )
        entry = PooledCredential(
            provider="openai-codex",
            id=_uuid.uuid4().hex[:6],
            label="dashboard device_code",
            auth_type=AUTH_TYPE_OAUTH,
            priority=0,
            source=f"{SOURCE_MANUAL}:dashboard_device_code",
            access_token=access_token,
            refresh_token=refresh_token,
            base_url=base_url,
        )
        pool.add_entry(entry)
        with _oauth_sessions_lock:
            sess["status"] = "approved"
        _log.info("oauth/device: openai-codex login completed (session=%s)", session_id)
    except Exception as e:
        _log.warning("codex device-code worker failed (session=%s): %s", session_id, e)
        with _oauth_sessions_lock:
            s = _oauth_sessions.get(session_id)
            if s:
                s["status"] = "error"
                s["error_message"] = str(e)


@app.post("/api/providers/oauth/{provider_id}/start")
async def start_oauth_login(provider_id: str, request: Request):
    """Initiate an OAuth login flow. Token-protected."""
    _require_token(request)
    _gc_oauth_sessions()
    valid = {p["id"] for p in _OAUTH_PROVIDER_CATALOG}
    if provider_id not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown provider {provider_id}")
    catalog_entry = next(p for p in _OAUTH_PROVIDER_CATALOG if p["id"] == provider_id)
    if catalog_entry["flow"] == "external":
        raise HTTPException(
            status_code=400,
            detail=f"{provider_id} uses an external CLI; run `{catalog_entry['cli_command']}` manually",
        )
    try:
        if catalog_entry["flow"] == "pkce":
            return _start_anthropic_pkce()
        if catalog_entry["flow"] == "device_code":
            return await _start_device_code_flow(provider_id)
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("oauth/start %s failed", provider_id)
        raise HTTPException(status_code=500, detail=str(e))
    raise HTTPException(status_code=400, detail="Unsupported flow")


class OAuthSubmitBody(BaseModel):
    session_id: str
    code: str


@app.post("/api/providers/oauth/{provider_id}/submit")
async def submit_oauth_code(provider_id: str, body: OAuthSubmitBody, request: Request):
    """Submit the auth code for PKCE flows. Token-protected."""
    _require_token(request)
    if provider_id == "anthropic":
        return await asyncio.get_event_loop().run_in_executor(
            None, _submit_anthropic_pkce, body.session_id, body.code,
        )
    raise HTTPException(status_code=400, detail=f"submit not supported for {provider_id}")


@app.get("/api/providers/oauth/{provider_id}/poll/{session_id}")
async def poll_oauth_session(provider_id: str, session_id: str):
    """Poll a device-code session's status (no auth — read-only state)."""
    with _oauth_sessions_lock:
        sess = _oauth_sessions.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if sess["provider"] != provider_id:
        raise HTTPException(status_code=400, detail="Provider mismatch for session")
    return {
        "session_id": session_id,
        "status": sess["status"],
        "error_message": sess.get("error_message"),
        "expires_at": sess.get("expires_at"),
    }


@app.delete("/api/providers/oauth/sessions/{session_id}")
async def cancel_oauth_session(session_id: str, request: Request):
    """Cancel a pending OAuth session. Token-protected."""
    _require_token(request)
    with _oauth_sessions_lock:
        sess = _oauth_sessions.pop(session_id, None)
    if sess is None:
        return {"ok": False, "message": "session not found"}
    return {"ok": True, "session_id": session_id}


# ---------------------------------------------------------------------------
# Session detail endpoints
# ---------------------------------------------------------------------------



def _session_latest_descendant(session_id: str):
    """Resolve a session id to the newest child leaf session.

    /model may create child sessions. Dashboard refresh should continue the
    newest child instead of reopening the old parent.
    """
    from hermes_state import SessionDB

    def row_get(row, key, index):
        if isinstance(row, dict):
            return row.get(key)
        try:
            return row[key]
        except Exception:
            try:
                return row[index]
            except Exception:
                return None

    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid or not db.get_session(sid):
            return None, []

        conn = (
            getattr(db, "conn", None)
            or getattr(db, "_conn", None)
            or getattr(db, "connection", None)
            or getattr(db, "_connection", None)
        )

        rows = []
        if conn is not None:
            raw_rows = conn.execute(
                "SELECT id, parent_session_id, started_at FROM sessions"
            ).fetchall()
            for row in raw_rows:
                rows.append({
                    "id": row_get(row, "id", 0),
                    "parent_session_id": row_get(row, "parent_session_id", 1),
                    "started_at": row_get(row, "started_at", 2),
                })
        else:
            rows = db.list_sessions_rich(limit=10000, offset=0)

        children = {}
        for row in rows:
            rid = row.get("id")
            parent = row.get("parent_session_id")
            if rid and parent:
                children.setdefault(parent, []).append(row)

        def started(row):
            try:
                return float(row.get("started_at") or 0)
            except Exception:
                return 0.0

        current = sid
        path = [sid]
        seen = {sid}

        while children.get(current):
            candidates = [r for r in children[current] if r.get("id") not in seen]
            if not candidates:
                break
            candidates.sort(key=started, reverse=True)
            current = candidates[0]["id"]
            path.append(current)
            seen.add(current)

        return current, path
    finally:
        db.close()

@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        session = db.get_session(sid) if sid else None
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()



@app.get("/api/sessions/{session_id}/latest-descendant")
async def get_session_latest_descendant(session_id: str):
    latest, path = _session_latest_descendant(session_id)
    if not latest:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "requested_session_id": path[0] if path else session_id,
        "session_id": latest,
        "path": path,
        "changed": bool(path and latest != path[0]),
    }

@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        sid = db.resolve_session_id(session_id)
        if not sid:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = db.get_messages(sid)
        return {"session_id": sid, "messages": messages}
    finally:
        db.close()


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    from hermes_state import SessionDB
    db = SessionDB()
    try:
        if not db.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"ok": True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Log viewer endpoint
# ---------------------------------------------------------------------------


@app.get("/api/logs")
async def get_logs(
    file: str = "agent",
    lines: int = 100,
    level: Optional[str] = None,
    component: Optional[str] = None,
    search: Optional[str] = None,
):
    from hermes_cli.logs import _read_tail, LOG_FILES

    log_name = LOG_FILES.get(file)
    if not log_name:
        raise HTTPException(status_code=400, detail=f"Unknown log file: {file}")
    log_path = get_hermes_home() / "logs" / log_name
    if not log_path.exists():
        return {"file": file, "lines": []}

    try:
        from hermes_logging import COMPONENT_PREFIXES
    except ImportError:
        COMPONENT_PREFIXES = {}

    # Normalize "ALL" / "all" / empty → no filter. _matches_filters treats an
    # empty tuple as "must match a prefix" (startswith(()) is always False),
    # so passing () instead of None silently drops every line.
    min_level = level if level and level.upper() != "ALL" else None
    if component and component.lower() != "all":
        comp_prefixes = COMPONENT_PREFIXES.get(component)
        if comp_prefixes is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown component: {component}. "
                       f"Available: {', '.join(sorted(COMPONENT_PREFIXES))}",
            )
    else:
        comp_prefixes = None

    has_filters = bool(min_level or comp_prefixes or search)
    result = _read_tail(
        log_path, min(lines, 500) if not search else 2000,
        has_filters=has_filters,
        min_level=min_level,
        component_prefixes=comp_prefixes,
    )
    # Post-filter by search term (case-insensitive substring match).
    # _read_tail doesn't support free-text search, so we filter here and
    # trim to the requested line count afterward.
    if search:
        needle = search.lower()
        result = [l for l in result if needle in l.lower()][-min(lines, 500):]
    return {"file": file, "lines": result}


# ---------------------------------------------------------------------------
# Cron job management endpoints
# ---------------------------------------------------------------------------


class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"
    authorization: Optional[dict] = None


class CronJobUpdate(BaseModel):
    updates: dict


class CronAuthorizationDecision(BaseModel):
    approve: bool = True
    note: str = ""


class KnowledgeApprovalDecision(BaseModel):
    approve: bool = True
    note: str = ""


@app.get("/api/cron/jobs")
async def list_cron_jobs():
    from cron.jobs import list_jobs
    return list_jobs(include_disabled=True)


@app.get("/api/cron/jobs/{job_id}")
async def get_cron_job(job_id: str):
    from cron.jobs import get_job
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs")
async def create_cron_job(body: CronJobCreate):
    from cron.jobs import create_job
    try:
        job = create_job(prompt=body.prompt, schedule=body.schedule,
                         name=body.name, deliver=body.deliver,
                         authorization=body.authorization)
        return job
    except Exception as e:
        _log.exception("POST /api/cron/jobs failed")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/cron/jobs/{job_id}")
async def update_cron_job(job_id: str, body: CronJobUpdate):
    from cron.jobs import update_job
    job = update_job(job_id, body.updates)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/pause")
async def pause_cron_job(job_id: str):
    from cron.jobs import pause_job
    job = pause_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/resume")
async def resume_cron_job(job_id: str):
    from cron.jobs import resume_job
    job = resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/trigger")
async def trigger_cron_job(job_id: str):
    from cron.jobs import trigger_job
    job = trigger_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/cron/jobs/{job_id}/authorize")
async def authorize_cron_job(job_id: str, body: CronAuthorizationDecision, request: Request):
    from agent.governance import actor_display, can_authorize
    from cron.jobs import authorize_job, get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    auth = job.get("authorization")
    if not auth:
        raise HTTPException(status_code=400, detail="Job does not require authorization")
    actor = _request_dashboard_actor(request)
    allowed, reason = can_authorize(
        auth,
        actor=actor,
        config=_dashboard_governance_config_for_request(request),
    )
    if not allowed:
        raise HTTPException(status_code=403, detail=reason)
    updated = authorize_job(
        job_id,
        bool(body.approve),
        actor=actor_display(actor),
        note=body.note or None,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Job not found")
    return updated


@app.delete("/api/cron/jobs/{job_id}")
async def delete_cron_job(job_id: str):
    from cron.jobs import remove_job
    if not remove_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Governed knowledge endpoints
# ---------------------------------------------------------------------------


@app.get("/api/knowledge/layers")
async def get_knowledge_layers():
    from agent.enterprise_knowledge import knowledge_layers_summary

    return knowledge_layers_summary()


@app.get("/api/knowledge/approvals")
async def get_knowledge_approvals(status: str = "pending"):
    from agent.enterprise_knowledge import list_knowledge_approvals

    if status not in {"pending", "approved", "denied", "all"}:
        raise HTTPException(status_code=400, detail="status must be pending, approved, denied, or all")
    return {"approvals": list_knowledge_approvals(status)}


@app.post("/api/knowledge/approvals/{approval_id}/decide")
async def decide_knowledge_approval_endpoint(
    approval_id: str,
    body: KnowledgeApprovalDecision,
    request: Request,
):
    from agent.enterprise_knowledge import decide_knowledge_approval

    result = decide_knowledge_approval(
        approval_id,
        approve=bool(body.approve),
        note=body.note or None,
        actor=_request_dashboard_actor(request),
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=int(result.get("status_code") or 400),
            detail=result.get("error") or "Knowledge approval failed",
        )
    return result


# ---------------------------------------------------------------------------
# Staged file-change approval endpoints
# ---------------------------------------------------------------------------


class FileChangeApprovalDecision(BaseModel):
    approve: bool = True
    note: str = ""


@app.get("/api/files/approvals")
async def get_file_change_approvals(status: str = "pending"):
    from agent.file_change_approvals import list_file_change_approvals

    if status not in {"pending", "approved", "denied", "stale", "all"}:
        raise HTTPException(
            status_code=400,
            detail="status must be pending, approved, denied, stale, or all",
        )
    return {"approvals": list_file_change_approvals(status)}


@app.post("/api/files/approvals/{approval_id}/decide")
async def decide_file_change_approval_endpoint(
    approval_id: str,
    body: FileChangeApprovalDecision,
    request: Request,
):
    from agent.file_change_approvals import decide_file_change_approval

    result = decide_file_change_approval(
        approval_id,
        approve=bool(body.approve),
        note=body.note or None,
        actor=_request_dashboard_actor(request),
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=int(result.get("status_code") or 400),
            detail=result.get("error") or "File-change approval failed",
        )
    return result


# ---------------------------------------------------------------------------
# Profile management endpoints (minimal — list/create/rename/delete + SOUL.md)
# ---------------------------------------------------------------------------


class ProfileCreate(BaseModel):
    name: str
    clone_from_default: bool = False
    no_skills: bool = False


class ProfileRename(BaseModel):
    new_name: str


class ProfileSoulUpdate(BaseModel):
    content: str


def _profile_attr(info, name: str, default: Any = None) -> Any:
    try:
        return getattr(info, name)
    except Exception:
        return default


def _profile_to_dict(info) -> Dict[str, Any]:
    return {
        "name": _profile_attr(info, "name", ""),
        "path": str(_profile_attr(info, "path", "")),
        "is_default": bool(_profile_attr(info, "is_default", False)),
        "model": _profile_attr(info, "model"),
        "provider": _profile_attr(info, "provider"),
        "has_env": bool(_profile_attr(info, "has_env", False)),
        "skill_count": int(_profile_attr(info, "skill_count", 0) or 0),
    }


def _fallback_profile_dicts(profiles_mod) -> List[Dict[str, Any]]:
    def _safe(callable_, default):
        try:
            return callable_()
        except Exception:
            return default

    profiles: List[Dict[str, Any]] = []
    default_home = profiles_mod._get_default_hermes_home()
    if default_home.is_dir():
        model, provider = _safe(lambda: profiles_mod._read_config_model(default_home), (None, None))
        profiles.append({
            "name": "default",
            "path": str(default_home),
            "is_default": True,
            "model": model,
            "provider": provider,
            "has_env": (default_home / ".env").exists(),
            "skill_count": _safe(lambda: profiles_mod._count_skills(default_home), 0),
        })

    profiles_root = profiles_mod._get_profiles_root()
    if profiles_root.is_dir():
        for entry in sorted(profiles_root.iterdir()):
            if not entry.is_dir() or not profiles_mod._PROFILE_ID_RE.match(entry.name):
                continue
            model, provider = _safe(lambda entry=entry: profiles_mod._read_config_model(entry), (None, None))
            profiles.append({
                "name": entry.name,
                "path": str(entry),
                "is_default": False,
                "model": model,
                "provider": provider,
                "has_env": (entry / ".env").exists(),
                "skill_count": _safe(lambda entry=entry: profiles_mod._count_skills(entry), 0),
            })

    return profiles


def _resolve_profile_dir(name: str) -> Path:
    """Validate ``name`` and resolve to its directory or raise an HTTPException."""
    from hermes_cli import profiles as profiles_mod
    try:
        profiles_mod.validate_profile_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not profiles_mod.profile_exists(name):
        raise HTTPException(status_code=404, detail=f"Profile '{name}' does not exist.")
    return profiles_mod.get_profile_dir(name)


def _profile_setup_command(name: str) -> str:
    """Return the shell command used to configure a profile in the CLI."""
    _resolve_profile_dir(name)
    return "hermes setup" if name == "default" else f"{name} setup"


@app.get("/api/profiles")
async def list_profiles_endpoint():
    from hermes_cli import profiles as profiles_mod
    try:
        return {"profiles": [_profile_to_dict(p) for p in profiles_mod.list_profiles()]}
    except Exception:
        _log.exception("GET /api/profiles failed; falling back to profile directory scan")
        return {"profiles": _fallback_profile_dicts(profiles_mod)}


@app.post("/api/profiles")
async def create_profile_endpoint(body: ProfileCreate):
    from hermes_cli import profiles as profiles_mod
    try:
        path = profiles_mod.create_profile(
            name=body.name,
            clone_from="default" if body.clone_from_default else None,
            clone_config=body.clone_from_default,
            no_skills=body.no_skills,
        )
        # Match the CLI's profile-create flow: fresh named profiles get the
        # bundled skills installed. When cloning from default, create_profile()
        # has already copied the source profile's skills, including any
        # user-installed skills. When no_skills=True, create_profile() wrote
        # the opt-out marker and seed_profile_skills() will no-op.
        if not body.clone_from_default:
            profiles_mod.seed_profile_skills(path, quiet=True)

        # Match the CLI's profile-create flow: named profiles should get a
        # wrapper in ~/.local/bin when the alias is safe to create.
        collision = profiles_mod.check_alias_collision(body.name)
        if not collision:
            profiles_mod.create_wrapper_script(body.name)
    except (ValueError, FileExistsError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.exception("POST /api/profiles failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "name": body.name, "path": str(path)}


@app.get("/api/profiles/{name}/setup-command")
async def get_profile_setup_command(name: str):
    return {"command": _profile_setup_command(name)}


@app.post("/api/profiles/{name}/open-terminal")
async def open_profile_terminal_endpoint(name: str):
    try:
        command = _profile_setup_command(name)

        if sys.platform.startswith("win"):
            subprocess.Popen(["cmd.exe", "/c", "start", "", command])
        elif sys.platform == "darwin":
            escaped = command.replace("\\", "\\\\").replace('"', '\\"')
            applescript = (
                'tell application "Terminal"\n'
                "activate\n"
                f'do script "{escaped}"\n'
                "end tell"
            )
            subprocess.Popen(["osascript", "-e", applescript])
        else:
            terminal_commands = [
                ("x-terminal-emulator", ["x-terminal-emulator", "-e", "sh", "-lc", command]),
                ("gnome-terminal", ["gnome-terminal", "--", "sh", "-lc", command]),
                ("konsole", ["konsole", "-e", "sh", "-lc", command]),
                ("xfce4-terminal", ["xfce4-terminal", "-e", f"sh -lc '{command}'"]),
                ("mate-terminal", ["mate-terminal", "-e", f"sh -lc '{command}'"]),
                ("lxterminal", ["lxterminal", "-e", f"sh -lc '{command}'"]),
                ("tilix", ["tilix", "-e", "sh", "-lc", command]),
                ("alacritty", ["alacritty", "-e", "sh", "-lc", command]),
                ("kitty", ["kitty", "sh", "-lc", command]),
                ("xterm", ["xterm", "-e", "sh", "-lc", command]),
            ]
            for executable, popen_args in terminal_commands:
                if subprocess.call(
                    ["which", executable],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ) == 0:
                    subprocess.Popen(popen_args)
                    break
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No supported terminal emulator found",
                )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("POST /api/profiles/%s/open-terminal failed", name)
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "command": command}


@app.patch("/api/profiles/{name}")
async def rename_profile_endpoint(name: str, body: ProfileRename):
    from hermes_cli import profiles as profiles_mod
    try:
        path = profiles_mod.rename_profile(name, body.new_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, FileExistsError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.exception("PATCH /api/profiles/%s failed", name)
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "name": body.new_name, "path": str(path)}


@app.delete("/api/profiles/{name}")
async def delete_profile_endpoint(name: str):
    """Delete a profile. The dashboard collects the user's confirmation in
    its own dialog before this request, so we always pass ``yes=True`` to
    skip the CLI's interactive prompt."""
    from hermes_cli import profiles as profiles_mod
    try:
        path = profiles_mod.delete_profile(name, yes=True)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _log.exception("DELETE /api/profiles/%s failed", name)
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "path": str(path)}


@app.get("/api/profiles/{name}/soul")
async def get_profile_soul(name: str):
    soul_path = _resolve_profile_dir(name) / "SOUL.md"
    if soul_path.exists():
        try:
            return {"content": soul_path.read_text(encoding="utf-8"), "exists": True}
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not read SOUL.md: {e}")
    return {"content": "", "exists": False}


@app.put("/api/profiles/{name}/soul")
async def update_profile_soul(name: str, body: ProfileSoulUpdate):
    soul_path = _resolve_profile_dir(name) / "SOUL.md"
    try:
        soul_path.write_text(body.content, encoding="utf-8")
    except OSError as e:
        _log.exception("PUT /api/profiles/%s/soul failed", name)
        raise HTTPException(status_code=500, detail=f"Could not write SOUL.md: {e}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Skills & Tools endpoints
# ---------------------------------------------------------------------------


class SkillToggle(BaseModel):
    name: str
    enabled: bool


@app.get("/api/skills")
async def get_skills():
    from tools.skills_tool import _find_all_skills
    from hermes_cli.skills_config import get_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    skills = _find_all_skills(skip_disabled=True)
    for s in skills:
        s["enabled"] = s["name"] not in disabled
    return skills


@app.put("/api/skills/toggle")
async def toggle_skill(body: SkillToggle):
    from hermes_cli.skills_config import get_disabled_skills, save_disabled_skills
    config = load_config()
    disabled = get_disabled_skills(config)
    if body.enabled:
        disabled.discard(body.name)
    else:
        disabled.add(body.name)
    save_disabled_skills(config, disabled)
    return {"ok": True, "name": body.name, "enabled": body.enabled}


@app.get("/api/tools/toolsets")
async def get_toolsets():
    from hermes_cli.tools_config import (
        _get_effective_configurable_toolsets,
        _get_platform_tools,
        _toolset_has_keys,
    )
    from toolsets import resolve_toolset

    config = load_config()
    enabled_toolsets = _get_platform_tools(
        config,
        "cli",
        include_default_mcp_servers=False,
    )
    result = []
    for name, label, desc in _get_effective_configurable_toolsets():
        try:
            tools = sorted(set(resolve_toolset(name)))
        except Exception:
            tools = []
        is_enabled = name in enabled_toolsets
        result.append({
            "name": name, "label": label, "description": desc,
            "enabled": is_enabled,
            "available": is_enabled,
            "configured": _toolset_has_keys(name, config),
            "tools": tools,
        })
    return result


# ---------------------------------------------------------------------------
# Raw YAML config endpoint
# ---------------------------------------------------------------------------


class RawConfigUpdate(BaseModel):
    yaml_text: str


@app.get("/api/config/raw")
async def get_config_raw():
    path = get_config_path()
    if not path.exists():
        return {"yaml": ""}
    return {"yaml": path.read_text(encoding="utf-8")}


@app.put("/api/config/raw")
async def update_config_raw(body: RawConfigUpdate):
    try:
        parsed = yaml.safe_load(body.yaml_text)
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="YAML must be a mapping")
        save_config(parsed)
        return {"ok": True}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")


# ---------------------------------------------------------------------------
# Token / cost analytics endpoint
# ---------------------------------------------------------------------------


@app.get("/api/analytics/usage")
async def get_usage_analytics(days: int = 30):
    from hermes_state import SessionDB
    from agent.insights import InsightsEngine

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)
        cur = db._conn.execute("""
            SELECT date(started_at, 'unixepoch') as day,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ?
            GROUP BY day ORDER BY day
        """, (cutoff,))
        daily = [dict(r) for r in cur.fetchall()]

        cur2 = db._conn.execute("""
            SELECT model,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls
            FROM sessions WHERE started_at > ? AND model IS NOT NULL
            GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """, (cutoff,))
        by_model = [dict(r) for r in cur2.fetchall()]

        cur3 = db._conn.execute("""
            SELECT SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions,
                   SUM(COALESCE(api_call_count, 0)) as total_api_calls
            FROM sessions WHERE started_at > ?
        """, (cutoff,))
        totals = dict(cur3.fetchone())
        insights_report = InsightsEngine(db).generate(days=days)
        skills = insights_report.get("skills", {
            "summary": {
                "total_skill_loads": 0,
                "total_skill_edits": 0,
                "total_skill_actions": 0,
                "distinct_skills_used": 0,
            },
            "top_skills": [],
        })

        return {
            "daily": daily,
            "by_model": by_model,
            "totals": totals,
            "period_days": days,
            "skills": skills,
        }
    finally:
        db.close()


@app.get("/api/analytics/models")
async def get_models_analytics(days: int = 30):
    """Rich per-model analytics for the Models dashboard page.

    Returns token/cost/session breakdown per model plus capability metadata
    from models.dev (context window, vision, tools, reasoning, etc.).
    """
    from hermes_state import SessionDB

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)

        cur = db._conn.execute("""
            SELECT model,
                   billing_provider,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions,
                   SUM(COALESCE(api_call_count, 0)) as api_calls,
                   SUM(tool_call_count) as tool_calls,
                   MAX(started_at) as last_used_at,
                   AVG(input_tokens + output_tokens) as avg_tokens_per_session
            FROM sessions WHERE started_at > ? AND model IS NOT NULL AND model != ''
            GROUP BY model, billing_provider
            ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """, (cutoff,))
        rows = [dict(r) for r in cur.fetchall()]

        models = []
        for row in rows:
            provider = row.get("billing_provider") or ""
            model_name = row["model"]
            caps = {}
            try:
                from agent.models_dev import get_model_capabilities
                mc = get_model_capabilities(provider=provider, model=model_name)
                if mc is not None:
                    caps = {
                        "supports_tools": mc.supports_tools,
                        "supports_vision": mc.supports_vision,
                        "supports_reasoning": mc.supports_reasoning,
                        "context_window": mc.context_window,
                        "max_output_tokens": mc.max_output_tokens,
                        "model_family": mc.model_family,
                    }
            except Exception:
                pass

            models.append({
                "model": model_name,
                "provider": provider,
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_read_tokens": row["cache_read_tokens"],
                "reasoning_tokens": row["reasoning_tokens"],
                "estimated_cost": row["estimated_cost"],
                "actual_cost": row["actual_cost"],
                "sessions": row["sessions"],
                "api_calls": row["api_calls"],
                "tool_calls": row["tool_calls"],
                "last_used_at": row["last_used_at"],
                "avg_tokens_per_session": row["avg_tokens_per_session"],
                "capabilities": caps,
            })

        totals_cur = db._conn.execute("""
            SELECT COUNT(DISTINCT model) as distinct_models,
                   SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions,
                   SUM(COALESCE(api_call_count, 0)) as total_api_calls
            FROM sessions WHERE started_at > ? AND model IS NOT NULL AND model != ''
        """, (cutoff,))
        totals = dict(totals_cur.fetchone())

        return {
            "models": models,
            "totals": totals,
            "period_days": days,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# /api/pty — PTY-over-WebSocket bridge for the dashboard "Chat" tab.
#
# The endpoint spawns the same ``hermes --tui`` binary the CLI uses, behind
# a POSIX pseudo-terminal, and forwards bytes + resize escapes across a
# WebSocket.  The browser renders the ANSI through xterm.js (see
# web/src/pages/ChatPage.tsx).
#
# Auth: ``?token=<session_token>`` query param (browsers can't set
# Authorization on the WS upgrade).  Same ephemeral ``_SESSION_TOKEN`` as
# REST.  Localhost-only — we defensively reject non-loopback clients even
# though uvicorn binds to 127.0.0.1.
# ---------------------------------------------------------------------------

import re
import asyncio

from hermes_cli.pty_bridge import PtyBridge, PtyUnavailableError

_RESIZE_RE = re.compile(rb"\x1b\[RESIZE:(\d+);(\d+)\]")
_PTY_READ_CHUNK_TIMEOUT = 0.2
_VALID_CHANNEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# Starlette's TestClient reports the peer as "testclient"; treat it as
# loopback so tests don't need to rewrite request scope.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _is_public_bind() -> bool:
    """True when bound to all interfaces."""
    return getattr(app.state, "bound_host", "") in ("0.0.0.0", "::")


def _ws_client_is_allowed(ws: "WebSocket") -> bool:
    """Check if the WebSocket client IP is acceptable.

    Allows loopback always; allows any IP when bound to all-interfaces
    (--insecure mode, guarded by session token auth).
    """
    if _is_public_bind():
        return True
    client_host = ws.client.host if ws.client else ""
    if not client_host:
        return True
    return client_host in _LOOPBACK_HOSTS

# Per-channel subscriber registry used by /api/pub (PTY-side gateway → dashboard)
# and /api/events (dashboard → browser sidebar).  Keyed by an opaque channel id
# the chat tab generates on mount; entries auto-evict when the last subscriber
# drops AND the publisher has disconnected.
_event_channels: dict[str, set] = {}
_event_lock = asyncio.Lock()


def _resolve_chat_argv(
    resume: Optional[str] = None,
    sidecar_url: Optional[str] = None,
) -> tuple[list[str], Optional[str], Optional[dict]]:
    """Resolve the argv + cwd + env for the chat PTY.

    Default: whatever ``hermes --tui`` would run.  Tests monkeypatch this
    function to inject a tiny fake command (``cat``, ``sh -c 'printf …'``)
    so nothing has to build Node or the TUI bundle.

    Session resume is propagated via the ``HERMES_TUI_RESUME`` env var —
    matching what ``hermes_cli.main._launch_tui`` does for the CLI path.
    Appending ``--resume <id>`` to argv doesn't work because ``ui-tui`` does
    not parse its argv.

    `sidecar_url` (when set) is forwarded as ``HERMES_TUI_SIDECAR_URL`` so
    the spawned ``tui_gateway.entry`` can mirror dispatcher emits to the
    dashboard's ``/api/pub`` endpoint (see :func:`pub_ws`).
    """
    from hermes_cli.main import PROJECT_ROOT, _make_tui_argv

    argv, cwd = _make_tui_argv(PROJECT_ROOT / "ui-tui", tui_dev=False)
    env = os.environ.copy()
    env.setdefault("NODE_ENV", "production")
    # Browser-embedded chat should prefer stable wheel-based scrollback over
    # native terminal mouse tracking. When mouse tracking is enabled, wheel
    # events are consumed by the TUI and forwarded as terminal input, which
    # makes browser-side transcript scrolling feel broken. Keep the terminal
    # build unchanged for native CLI usage; only disable mouse tracking for
    # the dashboard PTY path.
    env.setdefault("HERMES_TUI_DISABLE_MOUSE", "1")

    if resume:
        latest_resume, _latest_path = _session_latest_descendant(resume)
        if latest_resume:
            resume = latest_resume
        env["HERMES_TUI_RESUME"] = resume

    if sidecar_url:
        env["HERMES_TUI_SIDECAR_URL"] = sidecar_url

    return list(argv), str(cwd) if cwd else None, env


def _build_sidecar_url(channel: str) -> Optional[str]:
    """ws:// URL the PTY child should publish events to, or None when unbound."""
    host = getattr(app.state, "bound_host", None)
    port = getattr(app.state, "bound_port", None)

    if not host or not port:
        return None

    netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
    qs = urllib.parse.urlencode({"token": _SESSION_TOKEN, "channel": channel})

    return f"ws://{netloc}/api/pub?{qs}"


async def _broadcast_event(channel: str, payload: str) -> None:
    """Fan out one publisher frame to every subscriber on `channel`."""
    async with _event_lock:
        subs = list(_event_channels.get(channel, ()))

    for sub in subs:
        try:
            await sub.send_text(payload)
        except Exception:
            # Subscriber went away mid-send; the /api/events finally clause
            # will remove it from the registry on its next iteration.
            pass


def _channel_or_close_code(ws: WebSocket) -> Optional[str]:
    """Return the channel id from the query string or None if invalid."""
    channel = ws.query_params.get("channel", "")

    return channel if _VALID_CHANNEL_RE.match(channel) else None


def _websocket_dashboard_session(ws: WebSocket) -> Optional[DashboardSession]:
    token = ws.query_params.get("token", "")
    return _session_from_dashboard_token(token)


def _websocket_session_can_chat(session: DashboardSession) -> bool:
    if not _dashboard_auth_enabled():
        return True
    auth_config = _dashboard_auth_config()
    required = _coerce_role_list(auth_config.get("manage_roles")) or _coerce_role_list(auth_config.get("admin_roles"))
    return _dashboard_roles_allow(session.roles, required)


@app.websocket("/api/pty")
async def pty_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    # --- auth + loopback check (before accept so we can close cleanly) ---
    session = _websocket_dashboard_session(ws)
    if not session:
        await ws.close(code=4401)
        return
    if not _websocket_session_can_chat(session):
        await ws.close(code=4403)
        return

    if not _ws_client_is_allowed(ws):
        await ws.close(code=4403)
        return

    await ws.accept()

    # --- spawn PTY ------------------------------------------------------
    resume = ws.query_params.get("resume") or None
    channel = _channel_or_close_code(ws)
    sidecar_url = _build_sidecar_url(channel) if channel else None

    try:
        argv, cwd, env = _resolve_chat_argv(resume=resume, sidecar_url=sidecar_url)
    except SystemExit as exc:
        # _make_tui_argv calls sys.exit(1) when node/npm is missing.
        await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return


    try:
        bridge = PtyBridge.spawn(argv, cwd=cwd, env=env)
    except PtyUnavailableError as exc:
        await ws.send_text(f"\r\n\x1b[31mChat unavailable: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return
    except (FileNotFoundError, OSError) as exc:
        await ws.send_text(f"\r\n\x1b[31mChat failed to start: {exc}\x1b[0m\r\n")
        await ws.close(code=1011)
        return

    loop = asyncio.get_running_loop()

    # --- reader task: PTY master → WebSocket ----------------------------
    async def pump_pty_to_ws() -> None:
        while True:
            chunk = await loop.run_in_executor(
                None, bridge.read, _PTY_READ_CHUNK_TIMEOUT
            )
            if chunk is None:  # EOF
                return
            if not chunk:  # no data this tick; yield control and retry
                await asyncio.sleep(0)
                continue
            try:
                await ws.send_bytes(chunk)
            except Exception:
                return

    reader_task = asyncio.create_task(pump_pty_to_ws())

    # --- writer loop: WebSocket → PTY master ----------------------------
    try:
        while True:
            msg = await ws.receive()
            msg_type = msg.get("type")
            if msg_type == "websocket.disconnect":
                break
            raw = msg.get("bytes")
            if raw is None:
                text = msg.get("text")
                raw = text.encode("utf-8") if isinstance(text, str) else b""
            if not raw:
                continue

            # Resize escape is consumed locally, never written to the PTY.
            match = _RESIZE_RE.match(raw)
            if match and match.end() == len(raw):
                cols = int(match.group(1))
                rows = int(match.group(2))
                bridge.resize(cols=cols, rows=rows)
                continue

            bridge.write(raw)
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass
        bridge.close()


# ---------------------------------------------------------------------------
# /api/ws — JSON-RPC WebSocket sidecar for the dashboard "Chat" tab.
#
# Drives the same `tui_gateway.dispatch` surface Ink uses over stdio, so the
# dashboard can render structured metadata (model badge, tool-call sidebar,
# slash launcher, session info) alongside the xterm.js terminal that PTY
# already paints. Both transports bind to the same session id when one is
# active, so a tool.start emitted by the agent fans out to both sinks.
# ---------------------------------------------------------------------------


@app.websocket("/api/ws")
async def gateway_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    session = _websocket_dashboard_session(ws)
    if not session:
        await ws.close(code=4401)
        return
    if not _websocket_session_can_chat(session):
        await ws.close(code=4403)
        return

    if not _ws_client_is_allowed(ws):
        await ws.close(code=4403)
        return

    from tui_gateway.ws import handle_ws

    await handle_ws(ws)


# ---------------------------------------------------------------------------
# /api/pub + /api/events — chat-tab event broadcast.
#
# The PTY-side ``tui_gateway.entry`` opens /api/pub at startup (driven by
# HERMES_TUI_SIDECAR_URL set in /api/pty's PTY env) and writes every
# dispatcher emit through it.  The dashboard fans those frames out to any
# subscriber that opened /api/events on the same channel id.  This is what
# gives the React sidebar its tool-call feed without breaking the PTY
# child's stdio handshake with Ink.
# ---------------------------------------------------------------------------


@app.websocket("/api/pub")
async def pub_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    token = ws.query_params.get("token", "")
    if not hmac.compare_digest(token.encode(), _SESSION_TOKEN.encode()):
        await ws.close(code=4401)
        return

    if not _ws_client_is_allowed(ws):
        await ws.close(code=4403)
        return

    channel = _channel_or_close_code(ws)
    if not channel:
        await ws.close(code=4400)
        return

    await ws.accept()

    try:
        while True:
            await _broadcast_event(channel, await ws.receive_text())
    except WebSocketDisconnect:
        pass


@app.websocket("/api/events")
async def events_ws(ws: WebSocket) -> None:
    if not _DASHBOARD_EMBEDDED_CHAT_ENABLED:
        await ws.close(code=4403)
        return

    session = _websocket_dashboard_session(ws)
    if not session:
        await ws.close(code=4401)
        return

    if not _ws_client_is_allowed(ws):
        await ws.close(code=4403)
        return

    channel = _channel_or_close_code(ws)
    if not channel:
        await ws.close(code=4400)
        return

    await ws.accept()

    async with _event_lock:
        _event_channels.setdefault(channel, set()).add(ws)

    try:
        while True:
            # Subscribers don't speak — the receive() just blocks until
            # disconnect so the connection stays open as long as the
            # browser holds it.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _event_lock:
            subs = _event_channels.get(channel)

            if subs is not None:
                subs.discard(ws)

                if not subs:
                    _event_channels.pop(channel, None)


def _normalise_prefix(raw: Optional[str]) -> str:
    """Normalise an X-Forwarded-Prefix header value.

    Returns a string like ``"/hermes"`` (no trailing slash) or ``""`` when
    no prefix is set / the header is malformed. We deliberately reject
    anything containing ``..`` or non-printable bytes so a hostile proxy
    can't inject HTML via the prefix.
    """
    if not raw:
        return ""
    p = raw.strip()
    if not p:
        return ""
    if not p.startswith("/"):
        p = "/" + p
    p = p.rstrip("/")
    if "//" in p or ".." in p or any(c in p for c in ('"', "'", "<", ">", " ", "\n", "\r", "\t")):
        return ""
    if len(p) > 64:
        return ""
    return p


def mount_spa(application: FastAPI):
    """Mount the built SPA. Falls back to index.html for client-side routing.

    The session token is injected into index.html via a ``<script>`` tag so
    the SPA can authenticate against protected API endpoints without a
    separate (unauthenticated) token-dispensing endpoint.

    When served behind a path-prefix reverse proxy (e.g.
    ``mission-control.tilos.com/hermes/*`` -> local Caddy -> :9119), the
    proxy injects ``X-Forwarded-Prefix: /hermes`` on every request. We
    rewrite the served ``index.html`` so absolute asset URLs (``/assets/...``)
    and the SPA's runtime ``__HERMES_BASE_PATH__`` honour that prefix
    without rebuilding the bundle.
    """
    if not WEB_DIST.exists():
        @application.get("/{full_path:path}")
        async def no_frontend(full_path: str):
            return JSONResponse(
                {"error": "Frontend not built. Run: cd web && npm run build"},
                status_code=404,
            )
        return

    _index_path = WEB_DIST / "index.html"

    def _serve_index(prefix: str = ""):
        """Return index.html with the session token + base-path injected.

        ``prefix`` is the normalised ``X-Forwarded-Prefix`` (e.g. ``/hermes``)
        or empty string when served at root.
        """
        html = _index_path.read_text()
        chat_js = "true" if _DASHBOARD_EMBEDDED_CHAT_ENABLED else "false"
        auth_required = _dashboard_auth_enabled()
        token_part = "" if auth_required else f'window.__HERMES_SESSION_TOKEN__="{_SESSION_TOKEN}";'
        token_script = (
            f"<script>{token_part}"
            f"window.__HERMES_DASHBOARD_AUTH_REQUIRED__={'true' if auth_required else 'false'};"
            f"window.__HERMES_DASHBOARD_EMBEDDED_CHAT__={chat_js};"
            f'window.__HERMES_BASE_PATH__="{prefix}";</script>'
        )
        if prefix:
            # Rewrite absolute asset URLs baked into the Vite build so the
            # browser fetches them through the same proxy prefix.
            html = html.replace('href="/assets/', f'href="{prefix}/assets/')
            html = html.replace('src="/assets/', f'src="{prefix}/assets/')
            html = html.replace('href="/favicon.ico"', f'href="{prefix}/favicon.ico"')
            html = html.replace('href="/fonts/', f'href="{prefix}/fonts/')
            html = html.replace('href="/ds-assets/', f'href="{prefix}/ds-assets/')
            html = html.replace('src="/ds-assets/', f'src="{prefix}/ds-assets/')
        html = html.replace("</head>", f"{token_script}</head>", 1)
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    # When served behind a path-prefix proxy, the built CSS contains
    # absolute ``url(/fonts/...)`` and ``url(/ds-assets/...)`` references.
    # Browsers resolve those against the document origin, which means
    # under ``/hermes`` they'd hit ``mission-control.tilos.com/fonts/...``
    # (the MC Pages app), not the Hermes backend. Intercept CSS asset
    # requests BEFORE the StaticFiles mount and rewrite the absolute paths
    # when a prefix is in play.
    @application.get("/assets/{filename}.css")
    async def serve_css(filename: str, request: Request):
        css_path = WEB_DIST / "assets" / f"{filename}.css"
        if not css_path.is_file() or not css_path.resolve().is_relative_to(
            WEB_DIST.resolve()
        ):
            return JSONResponse({"error": "not found"}, status_code=404)
        prefix = _normalise_prefix(request.headers.get("x-forwarded-prefix"))
        css = css_path.read_text()
        if prefix:
            for asset_dir in ("/fonts/", "/fonts-terminal/", "/ds-assets/", "/assets/"):
                css = css.replace(f"url({asset_dir}", f"url({prefix}{asset_dir}")
                css = css.replace(f"url(\"{asset_dir}", f"url(\"{prefix}{asset_dir}")
                css = css.replace(f"url('{asset_dir}", f"url('{prefix}{asset_dir}")
        return Response(content=css, media_type="text/css")

    application.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @application.get("/{full_path:path}")
    async def serve_spa(full_path: str, request: Request):
        prefix = _normalise_prefix(request.headers.get("x-forwarded-prefix"))
        file_path = WEB_DIST / full_path
        # Prevent path traversal via url-encoded sequences (%2e%2e/)
        if (
            full_path
            and file_path.resolve().is_relative_to(WEB_DIST.resolve())
            and file_path.exists()
            and file_path.is_file()
        ):
            return FileResponse(file_path)
        return _serve_index(prefix)


# ---------------------------------------------------------------------------
# Dashboard theme endpoints
# ---------------------------------------------------------------------------

# Built-in dashboard themes — label + description only.  The actual color
# definitions live in the frontend (web/src/themes/presets.ts).
_BUILTIN_DASHBOARD_THEMES = [
    {"name": "default",       "label": "Ampliia",             "description": "Light paper, grid lines, black text, and Ampliia blue"},
    {"name": "default-large", "label": "Ampliia (Large)",     "description": "Ampliia with bigger fonts and roomier spacing"},
    {"name": "midnight",      "label": "Midnight",            "description": "Deep blue-violet with cool accents"},
    {"name": "ember",     "label": "Ember",          "description": "Warm crimson and bronze — forge vibes"},
    {"name": "mono",      "label": "Mono",           "description": "Clean grayscale — minimal and focused"},
    {"name": "cyberpunk", "label": "Cyberpunk",      "description": "Neon green on black — matrix terminal"},
    {"name": "rose",      "label": "Rosé",           "description": "Soft pink and warm ivory — easy on the eyes"},
]


def _parse_theme_layer(value: Any, default_hex: str, default_alpha: float = 1.0) -> Optional[Dict[str, Any]]:
    """Normalise a theme layer spec from YAML into `{hex, alpha}` form.

    Accepts shorthand (a bare hex string) or full dict form.  Returns
    ``None`` on garbage input so the caller can fall back to a built-in
    default rather than blowing up.
    """
    if value is None:
        return {"hex": default_hex, "alpha": default_alpha}
    if isinstance(value, str):
        return {"hex": value, "alpha": default_alpha}
    if isinstance(value, dict):
        hex_val = value.get("hex", default_hex)
        alpha_val = value.get("alpha", default_alpha)
        if not isinstance(hex_val, str):
            return None
        try:
            alpha_f = float(alpha_val)
        except (TypeError, ValueError):
            alpha_f = default_alpha
        return {"hex": hex_val, "alpha": max(0.0, min(1.0, alpha_f))}
    return None


_THEME_DEFAULT_TYPOGRAPHY: Dict[str, str] = {
    "fontSans": 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    "fontMono": 'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace',
    "baseSize": "15px",
    "lineHeight": "1.55",
    "letterSpacing": "0",
}

_THEME_DEFAULT_LAYOUT: Dict[str, str] = {
    "radius": "0.5rem",
    "density": "comfortable",
}

_THEME_OVERRIDE_KEYS = {
    "card", "cardForeground", "popover", "popoverForeground",
    "primary", "primaryForeground", "secondary", "secondaryForeground",
    "muted", "mutedForeground", "accent", "accentForeground",
    "destructive", "destructiveForeground", "success", "warning",
    "border", "input", "ring",
}

# Well-known named asset slots themes can populate.  Any other keys under
# ``assets.custom`` are exposed as ``--theme-asset-custom-<key>`` CSS vars
# for plugin/shell use.
_THEME_NAMED_ASSET_KEYS = {"bg", "hero", "logo", "crest", "sidebar", "header"}

# Component-style buckets themes can override.  The value under each bucket
# is a mapping from camelCase property name to CSS string; each pair emits
# ``--component-<bucket>-<kebab-property>`` on :root.  The frontend's shell
# components (Card, App header, Backdrop, etc.) consume these vars so themes
# can restyle chrome (clip-path, border-image, segmented progress, etc.)
# without shipping their own CSS.
_THEME_COMPONENT_BUCKETS = {
    "card", "header", "footer", "sidebar", "tab",
    "progress", "badge", "backdrop", "page",
}

_THEME_LAYOUT_VARIANTS = {"standard", "cockpit", "tiled"}

# Cap on customCSS length so a malformed/oversized theme YAML can't blow up
# the response payload or the <style> tag.  32 KiB is plenty for every
# practical reskin (the Strike Freedom demo is ~2 KiB).
_THEME_CUSTOM_CSS_MAX = 32 * 1024


def _normalise_theme_definition(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise a user theme YAML into the wire format `ThemeProvider`
    expects.  Returns ``None`` if the theme is unusable.

    Accepts both the full schema (palette/typography/layout) and a loose
    form with bare hex strings, so hand-written YAMLs stay friendly.
    """
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    # Palette
    palette_src = data.get("palette", {}) if isinstance(data.get("palette"), dict) else {}
    # Allow top-level `colors.background` as a shorthand too.
    colors_src = data.get("colors", {}) if isinstance(data.get("colors"), dict) else {}

    def _layer(key: str, default_hex: str, default_alpha: float = 1.0) -> Dict[str, Any]:
        spec = palette_src.get(key, colors_src.get(key))
        parsed = _parse_theme_layer(spec, default_hex, default_alpha)
        return parsed if parsed is not None else {"hex": default_hex, "alpha": default_alpha}

    palette = {
        "background": _layer("background", "#041c1c", 1.0),
        "midground": _layer("midground", "#ffe6cb", 1.0),
        "foreground": _layer("foreground", "#ffffff", 0.0),
        "warmGlow": palette_src.get("warmGlow") or data.get("warmGlow") or "rgba(255, 189, 56, 0.35)",
        "noiseOpacity": 1.0,
    }
    raw_noise = palette_src.get("noiseOpacity", data.get("noiseOpacity"))
    try:
        palette["noiseOpacity"] = float(raw_noise) if raw_noise is not None else 1.0
    except (TypeError, ValueError):
        palette["noiseOpacity"] = 1.0

    # Typography
    typo_src = data.get("typography", {}) if isinstance(data.get("typography"), dict) else {}
    typography = dict(_THEME_DEFAULT_TYPOGRAPHY)
    for key in ("fontSans", "fontMono", "fontDisplay", "fontUrl", "baseSize", "lineHeight", "letterSpacing"):
        val = typo_src.get(key)
        if isinstance(val, str) and val.strip():
            typography[key] = val

    # Layout
    layout_src = data.get("layout", {}) if isinstance(data.get("layout"), dict) else {}
    layout = dict(_THEME_DEFAULT_LAYOUT)
    radius = layout_src.get("radius")
    if isinstance(radius, str) and radius.strip():
        layout["radius"] = radius
    density = layout_src.get("density")
    if isinstance(density, str) and density in ("compact", "comfortable", "spacious"):
        layout["density"] = density

    # Color overrides — keep only valid keys with string values.
    overrides_src = data.get("colorOverrides", {})
    color_overrides: Dict[str, str] = {}
    if isinstance(overrides_src, dict):
        for key, val in overrides_src.items():
            if key in _THEME_OVERRIDE_KEYS and isinstance(val, str) and val.strip():
                color_overrides[key] = val

    # Assets — named slots + arbitrary user-defined keys.  Values must be
    # strings (URLs or CSS ``url(...)``/``linear-gradient(...)`` expressions).
    # We don't fetch remote assets here; the frontend just injects them as
    # CSS vars.  Empty values are dropped so a theme can explicitly clear a
    # slot by setting ``hero: ""``.
    assets_out: Dict[str, Any] = {}
    assets_src = data.get("assets", {}) if isinstance(data.get("assets"), dict) else {}
    for key in _THEME_NAMED_ASSET_KEYS:
        val = assets_src.get(key)
        if isinstance(val, str) and val.strip():
            assets_out[key] = val
    custom_assets_src = assets_src.get("custom")
    if isinstance(custom_assets_src, dict):
        custom_assets: Dict[str, str] = {}
        for key, val in custom_assets_src.items():
            if (
                isinstance(key, str)
                and key.replace("-", "").replace("_", "").isalnum()
                and isinstance(val, str)
                and val.strip()
            ):
                custom_assets[key] = val
        if custom_assets:
            assets_out["custom"] = custom_assets

    # Custom CSS — raw CSS text the frontend injects as a scoped <style>
    # tag on theme apply.  Clipped to _THEME_CUSTOM_CSS_MAX to keep the
    # payload bounded.  We intentionally do NOT parse/sanitise the CSS
    # here — the dashboard is localhost-only and themes are user-authored
    # YAML in ~/.hermes/, same trust level as the config file itself.
    custom_css_val = data.get("customCSS")
    custom_css: Optional[str] = None
    if isinstance(custom_css_val, str) and custom_css_val.strip():
        custom_css = custom_css_val[:_THEME_CUSTOM_CSS_MAX]

    # Component style overrides — per-bucket dicts of camelCase CSS
    # property -> CSS string.  The frontend converts these into CSS vars
    # that shell components (Card, App header, Backdrop) consume.
    component_styles_src = data.get("componentStyles", {})
    component_styles: Dict[str, Dict[str, str]] = {}
    if isinstance(component_styles_src, dict):
        for bucket, props in component_styles_src.items():
            if bucket not in _THEME_COMPONENT_BUCKETS or not isinstance(props, dict):
                continue
            clean: Dict[str, str] = {}
            for prop, value in props.items():
                if (
                    isinstance(prop, str)
                    and prop.replace("-", "").replace("_", "").isalnum()
                    and isinstance(value, (str, int, float))
                    and str(value).strip()
                ):
                    clean[prop] = str(value)
            if clean:
                component_styles[bucket] = clean

    layout_variant_src = data.get("layoutVariant")
    layout_variant = (
        layout_variant_src
        if isinstance(layout_variant_src, str) and layout_variant_src in _THEME_LAYOUT_VARIANTS
        else "standard"
    )

    result: Dict[str, Any] = {
        "name": name,
        "label": data.get("label") or name,
        "description": data.get("description", ""),
        "palette": palette,
        "typography": typography,
        "layout": layout,
        "layoutVariant": layout_variant,
    }
    if color_overrides:
        result["colorOverrides"] = color_overrides
    if assets_out:
        result["assets"] = assets_out
    if custom_css is not None:
        result["customCSS"] = custom_css
    if component_styles:
        result["componentStyles"] = component_styles
    return result


def _discover_user_themes() -> list:
    """Scan ~/.hermes/dashboard-themes/*.yaml for user-created themes.

    Returns a list of fully-normalised theme definitions ready to ship
    to the frontend, so the client can apply them without a secondary
    round-trip or a built-in stub.
    """
    themes_dir = get_hermes_home() / "dashboard-themes"
    if not themes_dir.is_dir():
        return []
    result = []
    for f in sorted(themes_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        normalised = _normalise_theme_definition(data)
        if normalised is not None:
            result.append(normalised)
    return result


@app.get("/api/dashboard/themes")
async def get_dashboard_themes():
    """Return available themes and the currently active one.

    Built-in entries ship name/label/description only (the frontend owns
    their full definitions in `web/src/themes/presets.ts`).  User themes
    from `~/.hermes/dashboard-themes/*.yaml` ship with their full
    normalised definition under `definition`, so the client can apply
    them without a stub.
    """
    config = load_config()
    active = cfg_get(config, "dashboard", "theme", default="default")
    user_themes = _discover_user_themes()
    seen = set()
    themes = []
    for t in _BUILTIN_DASHBOARD_THEMES:
        seen.add(t["name"])
        themes.append(t)
    for t in user_themes:
        if t["name"] in seen:
            continue
        themes.append({
            "name": t["name"],
            "label": t["label"],
            "description": t["description"],
            "definition": t,
        })
        seen.add(t["name"])
    return {"themes": themes, "active": active}


class ThemeSetBody(BaseModel):
    name: str


@app.put("/api/dashboard/theme")
async def set_dashboard_theme(body: ThemeSetBody):
    """Set the active dashboard theme (persists to config.yaml)."""
    config = load_config()
    if "dashboard" not in config:
        config["dashboard"] = {}
    config["dashboard"]["theme"] = body.name
    save_config(config)
    return {"ok": True, "theme": body.name}


# ---------------------------------------------------------------------------
# Dashboard plugin system
# ---------------------------------------------------------------------------

def _discover_dashboard_plugins() -> list:
    """Scan plugins/*/dashboard/manifest.json for dashboard extensions.

    Checks three plugin sources (same as hermes_cli.plugins):
    1. User plugins:    ~/.hermes/plugins/<name>/dashboard/manifest.json
    2. Bundled plugins: <repo>/plugins/<name>/dashboard/manifest.json  (memory/, etc.)
    3. Project plugins: ./.hermes/plugins/  (only if HERMES_ENABLE_PROJECT_PLUGINS)
    """
    plugins = []
    seen_names: set = set()

    from hermes_cli.plugins import get_bundled_plugins_dir
    bundled_root = get_bundled_plugins_dir()
    search_dirs = [
        (get_hermes_home() / "plugins", "user"),
        (bundled_root / "memory", "bundled"),
        (bundled_root, "bundled"),
    ]
    if os.environ.get("HERMES_ENABLE_PROJECT_PLUGINS"):
        search_dirs.append((Path.cwd() / ".hermes" / "plugins", "project"))

    for plugins_root, source in search_dirs:
        if not plugins_root.is_dir():
            continue
        for child in sorted(plugins_root.iterdir()):
            if not child.is_dir():
                continue
            manifest_file = child / "dashboard" / "manifest.json"
            if not manifest_file.exists():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                name = data.get("name", child.name)
                if name in seen_names:
                    continue
                seen_names.add(name)
                # Tab options: ``path`` + ``position`` for a new tab, optional
                # ``override`` to replace a built-in route, and ``hidden`` to
                # register the plugin component/slots without adding a tab
                # (useful for slot-only plugins like a header-crest injector).
                raw_tab = data.get("tab", {}) if isinstance(data.get("tab"), dict) else {}
                tab_info = {
                    "path": raw_tab.get("path", f"/{name}"),
                    "position": raw_tab.get("position", "end"),
                }
                override_path = raw_tab.get("override")
                if isinstance(override_path, str) and override_path.startswith("/"):
                    tab_info["override"] = override_path
                if bool(raw_tab.get("hidden")):
                    tab_info["hidden"] = True
                # Slots: list of named slot locations this plugin populates.
                # The frontend exposes ``registerSlot(pluginName, slotName, Component)``
                # on window; plugins with non-empty slots call it from their JS bundle.
                slots_src = data.get("slots")
                slots: List[str] = []
                if isinstance(slots_src, list):
                    slots = [s for s in slots_src if isinstance(s, str) and s]
                plugins.append({
                    "name": name,
                    "label": data.get("label", name),
                    "description": data.get("description", ""),
                    "icon": data.get("icon", "Puzzle"),
                    "version": data.get("version", "0.0.0"),
                    "tab": tab_info,
                    "slots": slots,
                    "entry": data.get("entry", "dist/index.js"),
                    "css": data.get("css"),
                    "has_api": bool(data.get("api")),
                    "source": source,
                    "_dir": str(child / "dashboard"),
                    "_api_file": data.get("api"),
                })
            except Exception as exc:
                _log.warning("Bad dashboard plugin manifest %s: %s", manifest_file, exc)
                continue
    return plugins


# Cache discovered plugins per-process (refresh on explicit re-scan).
_dashboard_plugins_cache: Optional[list] = None


def _get_dashboard_plugins(force_rescan: bool = False) -> list:
    global _dashboard_plugins_cache
    if _dashboard_plugins_cache is None or force_rescan:
        _dashboard_plugins_cache = _discover_dashboard_plugins()
    return _dashboard_plugins_cache


@app.get("/api/dashboard/plugins")
async def get_dashboard_plugins():
    """Return discovered dashboard plugins (excludes user-hidden ones)."""
    plugins = _get_dashboard_plugins()
    # Read user's hidden plugins list from config.
    config = load_config()
    hidden: list = cfg_get(config, "dashboard", "hidden_plugins", default=[]) or []
    # Strip internal fields before sending to frontend and filter out hidden.
    return [
        {k: v for k, v in p.items() if not k.startswith("_")}
        for p in plugins
        if p["name"] not in hidden
    ]


@app.get("/api/dashboard/plugins/rescan")
async def rescan_dashboard_plugins():
    """Force re-scan of dashboard plugins."""
    plugins = _get_dashboard_plugins(force_rescan=True)
    return {"ok": True, "count": len(plugins)}


class _AgentPluginInstallBody(BaseModel):
    identifier: str
    force: bool = False
    enable: bool = True


def _strip_dashboard_manifest(p: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _merged_plugins_hub() -> Dict[str, Any]:
    """Agent discovery + dashboard manifests + optional provider picker metadata."""
    from hermes_cli.plugins_cmd import (
        _discover_all_plugins,
        _get_current_context_engine,
        _get_current_memory_provider,
        _discover_context_engines,
        _discover_memory_providers,
        _get_disabled_set,
        _get_enabled_set,
        _read_manifest as _read_plugin_manifest_at,
    )

    dashboard_list = _get_dashboard_plugins()
    dash_by_name = {str(p["name"]): p for p in dashboard_list}

    disabled_set = _get_disabled_set()
    enabled_set = _get_enabled_set()

    # Read user-hidden plugins from config for the user_hidden field.
    config = load_config()
    hidden_plugins: list = cfg_get(config, "dashboard", "hidden_plugins", default=[]) or []

    plugins_root_resolved = (get_hermes_home() / "plugins").resolve()
    rows: List[Dict[str, Any]] = []

    for name, version, description, source, dir_str in _discover_all_plugins():
        if name in disabled_set:
            runtime_status = "disabled"
        elif name in enabled_set:
            runtime_status = "enabled"
        else:
            runtime_status = "inactive"

        dir_path = Path(dir_str)
        dm = dash_by_name.get(name)
        has_dash_manifest = dm is not None or (dir_path / "dashboard" / "manifest.json").exists()

        under_user_tree = False
        try:
            dir_path.resolve().relative_to(plugins_root_resolved)
            under_user_tree = True
        except ValueError:
            pass

        can_remove_update = (
            source in ("user", "git") and under_user_tree and Path(dir_str).is_dir()
        )

        # Check if this plugin provides tools that require auth
        auth_required = False
        auth_command = ""
        manifest_data = _read_plugin_manifest_at(dir_path)
        provides_tools = manifest_data.get("provides_tools") or []
        if provides_tools:
            try:
                from tools.registry import registry
                for tname in provides_tools:
                    entry = registry.get_entry(tname)
                    if entry and entry.check_fn and not entry.check_fn():
                        auth_required = True
                        auth_command = f"hermes auth {name}"
                        break
            except Exception:
                pass

        rows.append({
            "name": name,
            "version": version or "",
            "description": description or "",
            "source": source,
            "runtime_status": runtime_status,
            "has_dashboard_manifest": has_dash_manifest,
            "dashboard_manifest": _strip_dashboard_manifest(dm) if dm else None,
            "path": dir_str,
            "can_remove": can_remove_update,
            "can_update_git": can_remove_update and (Path(dir_str) / ".git").exists(),
            "auth_required": auth_required,
            "auth_command": auth_command,
            "user_hidden": name in hidden_plugins,
        })

    agent_names = {r["name"] for r in rows}
    orphan_dashboard = [
        _strip_dashboard_manifest(p)
        for p in dashboard_list
        if str(p["name"]) not in agent_names
    ]

    memory_providers: List[Dict[str, str]] = []
    try:
        for n, desc in _discover_memory_providers():
            memory_providers.append({"name": n, "description": desc})
    except Exception:
        memory_providers = []

    context_engines: List[Dict[str, str]] = []
    try:
        for n, desc in _discover_context_engines():
            context_engines.append({"name": n, "description": desc})
    except Exception:
        context_engines = []

    return {
        "plugins": rows,
        "orphan_dashboard_plugins": orphan_dashboard,
        "providers": {
            "memory_provider": _get_current_memory_provider() or "",
            "memory_options": memory_providers,
            "context_engine": _get_current_context_engine(),
            "context_options": context_engines,
        },
    }


@app.get("/api/dashboard/plugins/hub")
async def get_plugins_hub(request: Request):
    """Unified agent plugins + dashboard extension metadata (session protected)."""
    _require_token(request)
    try:
        return _merged_plugins_hub()
    except Exception as exc:
        _log.warning("plugins/hub failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to build plugins hub.") from exc


@app.post("/api/dashboard/agent-plugins/install")
async def post_agent_plugin_install(request: Request, body: _AgentPluginInstallBody):
    _require_token(request)
    from hermes_cli.plugins_cmd import dashboard_install_plugin

    result = dashboard_install_plugin(
        body.identifier.strip(),
        force=body.force,
        enable=body.enable,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error") or "Install failed.",
        )
    _get_dashboard_plugins(force_rescan=True)
    # Strip internal paths from the response
    result.pop("after_install_path", None)
    return result


def _validate_plugin_name(name: str) -> str:
    """Reject path-traversal attempts in plugin name URL parameters."""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid plugin name.")
    return name


@app.post("/api/dashboard/agent-plugins/{name}/enable")
async def post_agent_plugin_enable(request: Request, name: str):
    _require_token(request)
    name = _validate_plugin_name(name)
    from hermes_cli.plugins_cmd import dashboard_set_agent_plugin_enabled

    result = dashboard_set_agent_plugin_enabled(name, enabled=True)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Enable failed.")
    return result


@app.post("/api/dashboard/agent-plugins/{name}/disable")
async def post_agent_plugin_disable(request: Request, name: str):
    _require_token(request)
    name = _validate_plugin_name(name)
    from hermes_cli.plugins_cmd import dashboard_set_agent_plugin_enabled

    result = dashboard_set_agent_plugin_enabled(name, enabled=False)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Disable failed.")
    return result


@app.post("/api/dashboard/agent-plugins/{name}/update")
async def post_agent_plugin_update(request: Request, name: str):
    _require_token(request)
    name = _validate_plugin_name(name)
    from hermes_cli.plugins_cmd import dashboard_update_user_plugin

    result = dashboard_update_user_plugin(name)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Update failed.")
    _get_dashboard_plugins(force_rescan=True)
    return result


@app.delete("/api/dashboard/agent-plugins/{name}")
async def delete_agent_plugin(request: Request, name: str):
    _require_token(request)
    name = _validate_plugin_name(name)
    from hermes_cli.plugins_cmd import dashboard_remove_user_plugin

    result = dashboard_remove_user_plugin(name)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Remove failed.")
    _get_dashboard_plugins(force_rescan=True)
    return result


class _PluginProvidersPutBody(BaseModel):
    memory_provider: Optional[str] = None
    context_engine: Optional[str] = None


@app.put("/api/dashboard/plugin-providers")
async def put_plugin_providers(request: Request, body: _PluginProvidersPutBody):
    """Persist memory provider / context engine selection (writes config.yaml)."""
    _require_token(request)
    from hermes_cli.plugins_cmd import (
        _save_context_engine,
        _save_memory_provider,
    )

    if body.memory_provider is not None:
        _save_memory_provider(body.memory_provider)
    if body.context_engine is not None:
        _save_context_engine(body.context_engine)
    return {"ok": True}


class _PluginVisibilityBody(BaseModel):
    hidden: bool


@app.post("/api/dashboard/plugins/{name}/visibility")
async def post_plugin_visibility(request: Request, name: str, body: _PluginVisibilityBody):
    """Toggle a plugin's sidebar visibility (persists to config.yaml dashboard.hidden_plugins)."""
    _require_token(request)
    name = _validate_plugin_name(name)

    config = load_config()
    if "dashboard" not in config or not isinstance(config.get("dashboard"), dict):
        config["dashboard"] = {}
    hidden_list: list = config["dashboard"].get("hidden_plugins") or []
    if not isinstance(hidden_list, list):
        hidden_list = []

    if body.hidden and name not in hidden_list:
        hidden_list.append(name)
    elif not body.hidden and name in hidden_list:
        hidden_list.remove(name)

    config["dashboard"]["hidden_plugins"] = hidden_list
    save_config(config)
    return {"ok": True, "name": name, "hidden": body.hidden}


@app.get("/dashboard-plugins/{plugin_name}/{file_path:path}")
async def serve_plugin_asset(plugin_name: str, file_path: str):
    """Serve static assets from a dashboard plugin directory.

    Only serves files from the plugin's ``dashboard/`` subdirectory.
    Path traversal is blocked by checking ``resolve().is_relative_to()``.
    """
    plugins = _get_dashboard_plugins()
    plugin = next((p for p in plugins if p["name"] == plugin_name), None)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")

    base = Path(plugin["_dir"])
    target = (base / file_path).resolve()

    if not target.is_relative_to(base.resolve()):
        raise HTTPException(status_code=403, detail="Path traversal blocked")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Guess content type
    suffix = target.suffix.lower()
    content_types = {
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".html": "text/html",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
    }
    media_type = content_types.get(suffix, "application/octet-stream")
    return FileResponse(target, media_type=media_type)


def _mount_plugin_api_routes():
    """Import and mount backend API routes from plugins that declare them.

    Each plugin's ``api`` field points to a Python file that must expose
    a ``router`` (FastAPI APIRouter).  Routes are mounted under
    ``/api/plugins/<name>/``.
    """
    for plugin in _get_dashboard_plugins():
        api_file_name = plugin.get("_api_file")
        if not api_file_name:
            continue
        api_path = Path(plugin["_dir"]) / api_file_name
        if not api_path.exists():
            _log.warning("Plugin %s declares api=%s but file not found", plugin["name"], api_file_name)
            continue
        try:
            module_name = f"hermes_dashboard_plugin_{plugin['name']}"
            spec = importlib.util.spec_from_file_location(module_name, api_path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            # Register in sys.modules BEFORE exec_module so pydantic/FastAPI
            # can resolve forward references (e.g. models defined in a file
            # that uses `from __future__ import annotations`). Without this,
            # TypeAdapter lazy-build fails at first request with
            # "is not fully defined" because the module namespace isn't
            # reachable by name for string-annotation resolution.
            sys.modules[module_name] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            router = getattr(mod, "router", None)
            if router is None:
                _log.warning("Plugin %s api file has no 'router' attribute", plugin["name"])
                continue
            app.include_router(router, prefix=f"/api/plugins/{plugin['name']}")
            _log.info("Mounted plugin API routes: /api/plugins/%s/", plugin["name"])
        except Exception as exc:
            _log.warning("Failed to load plugin %s API routes: %s", plugin["name"], exc)


# Mount plugin API routes before the SPA catch-all.
_mount_plugin_api_routes()

mount_spa(app)


def _is_wsl() -> bool:
    """True when running inside Windows Subsystem for Linux."""
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def start_server(
    host: str = "127.0.0.1",
    port: int = 9119,
    open_browser: bool = True,
    allow_public: bool = False,
    *,
    embedded_chat: bool = False,
    open_path: str = "/",
):
    """Start the web UI server."""
    import uvicorn

    global _DASHBOARD_EMBEDDED_CHAT_ENABLED
    _DASHBOARD_EMBEDDED_CHAT_ENABLED = embedded_chat

    _LOCALHOST = ("127.0.0.1", "localhost", "::1")
    auth_config = _dashboard_auth_config()
    auth_ready = _dashboard_auth_configured_for_bind(host, auth_config)
    if host not in _LOCALHOST and not allow_public and not auth_ready:
        raise SystemExit(
            f"Refusing to bind to {host} — the dashboard exposes API keys, "
            f"config, and server file controls.\n"
            f"Enable dashboard.auth with {auth_config.get('token_env') or 'MAIA_DASHBOARD_TOKEN'} "
            f"or dashboard.auth.token_hash, trusted SSO headers, or channel_tokens "
            f"before serving it on an intranet/public interface. "
            f"Use --insecure only for temporary trusted-network testing."
        )
    if host not in _LOCALHOST and auth_ready:
        _log.warning(
            "Binding protected dashboard to %s. Keep TLS/reverse-proxy and "
            "firewall rules in front of public deployments.", host,
        )
    elif host not in _LOCALHOST:
        _log.warning(
            "Binding to %s with --insecure — the dashboard has no robust "
            "authentication. Only use on trusted networks.", host,
        )

    # Record the bound host so host_header_middleware can validate incoming
    # Host headers against it. Defends against DNS rebinding (GHSA-ppp5-vxwm-4cf7).
    # bound_port is also stashed so /api/pty can build the back-WS URL the
    # PTY child uses to publish events to the dashboard sidebar.
    app.state.bound_host = host
    app.state.bound_port = port

    path = open_path if open_path.startswith("/") else f"/{open_path}"
    url = f"http://{host}:{port}{'' if path == '/' else path}"

    if open_browser:
        import subprocess as _subprocess
        import webbrowser

        def _open():
            time.sleep(1.0)
            # On WSL the Linux openers webbrowser tries (gio/xdg-open) fail
            # with "Operation not supported" — hand the URL to Windows.
            if _is_wsl():
                for opener in (
                    ["wslview", url],
                    ["powershell.exe", "-NoProfile", "Start-Process", url],
                ):
                    try:
                        _subprocess.run(
                            opener,
                            stdout=_subprocess.DEVNULL,
                            stderr=_subprocess.DEVNULL,
                            timeout=15,
                            check=True,
                        )
                        return
                    except Exception:
                        continue
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=_open, daemon=True).start()

    print(f"  Maia Web UI → {url}")
    uvicorn.run(app, host=host, port=port, log_level="warning")

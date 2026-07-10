"""Per-user storage paths for human gateway identities.

CLI/local sessions retain the historical profile-wide directories. Human
gateway sessions (and cron runs carrying their creator identity) receive a
stable, opaque directory derived from ``platform:user_id`` so personal memory
and agent-created skills cannot bleed between users.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from hermes_constants import get_hermes_home


def _session_identity() -> tuple[str, str]:
    try:
        from gateway.session_context import get_session_env

        platform = get_session_env("HERMES_SESSION_PLATFORM", "")
        user_id = get_session_env("HERMES_SESSION_USER_ID", "")
    except Exception:
        platform = ""
        user_id = ""
    return str(platform or "").strip().lower(), str(user_id or "").strip()


def scoped_user_root(
    platform: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Path]:
    """Return the isolated root for a gateway actor, or ``None`` for local."""

    session_platform, session_user_id = _session_identity()
    resolved_platform = str(platform or session_platform or "").strip().lower()
    resolved_user_id = str(user_id or session_user_id or "").strip()
    if not resolved_user_id or resolved_platform in ("", "local", "cli"):
        return None

    safe_platform = re.sub(r"[^a-z0-9_-]+", "-", resolved_platform).strip("-")
    safe_platform = safe_platform[:32] or "gateway"
    identity = f"{resolved_platform}:{resolved_user_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return get_hermes_home() / "users" / f"{safe_platform}-{digest}"


def personal_memory_dir(
    platform: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Path:
    root = scoped_user_root(platform=platform, user_id=user_id)
    return (root / "memories") if root else (get_hermes_home() / "memories")


def personal_skills_dir(
    platform: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Path:
    root = scoped_user_root(platform=platform, user_id=user_id)
    return (root / "skills") if root else (get_hermes_home() / "skills")

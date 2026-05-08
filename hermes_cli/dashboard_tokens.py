"""Short-lived dashboard login tokens issued from authenticated channels."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional

from hermes_constants import get_hermes_home

TOKEN_PREFIX = "cdt_"


def _store_path() -> Path:
    return get_hermes_home() / "dashboard" / "channel_login_tokens.json"


def _hash_token(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _read_store() -> dict[str, Any]:
    path = _store_path()
    if not path.exists():
        return {"tokens": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"tokens": []}
    if not isinstance(data, dict):
        return {"tokens": []}
    tokens = data.get("tokens")
    if not isinstance(tokens, list):
        data["tokens"] = []
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

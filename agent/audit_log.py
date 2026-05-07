"""Corporate audit logging for governance-sensitive decisions.

The regular logging subsystem is optimized for operators debugging runtime
behavior.  This module writes append-only JSONL events for decisions that need
compliance review: governance denies, cron approval checkpoints, migration
actions, and similar enterprise controls.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


def _load_observability_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
    except Exception:
        cfg = {}
    obs = cfg.get("observability", {}) if isinstance(cfg, dict) else {}
    return obs if isinstance(obs, dict) else {}


def _audit_log_path(config: dict[str, Any]) -> Path:
    raw = str(config.get("audit_log_path") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = get_hermes_home() / path
        return path
    return get_hermes_home() / "logs" / "audit.jsonl"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _redact(value: Any, *, parent_key: str = "") -> Any:
    if parent_key and _is_sensitive_key(parent_key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, parent_key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, parent_key=parent_key) for item in value]
    return value


def _actor_payload(actor: Optional[Any]) -> dict[str, Any]:
    if actor is None:
        try:
            from agent.governance import actor_display, current_actor

            actor = current_actor()
            return {
                "id": actor_display(actor),
                "platform": getattr(actor, "platform", None),
                "user_id": getattr(actor, "user_id", None),
                "user_name": getattr(actor, "user_name", None),
            }
        except Exception:
            return {"id": "unknown"}
    if isinstance(actor, str):
        return {"id": actor}
    try:
        from agent.governance import actor_display

        return {
            "id": actor_display(actor),
            "platform": getattr(actor, "platform", None),
            "user_id": getattr(actor, "user_id", None),
            "user_name": getattr(actor, "user_name", None),
        }
    except Exception:
        return {"id": str(actor)}


def _post_siem_webhook(url: str, event: dict[str, Any], timeout: float) -> None:
    try:
        payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout):
            pass
    except Exception as exc:
        logger.warning("Audit SIEM webhook delivery failed: %s", exc)


def record_audit_event(
    event_type: str,
    *,
    actor: Optional[Any] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    outcome: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> bool:
    """Append one audit event.

    Returns ``True`` when the event was written locally.  Failures are logged
    and swallowed so audit plumbing never breaks the user-facing operation.
    """

    config = _load_observability_config()
    if not bool(config.get("enabled", True)):
        return False
    if not bool(config.get("audit_log_enabled", True)):
        return False

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": str(event_type),
        "actor": _actor_payload(actor),
        "action": action,
        "resource": resource,
        "outcome": outcome,
        "reason": reason,
        "metadata": metadata or {},
    }
    if bool(config.get("redact_sensitive_values", True)):
        event = _redact(event)

    path = _audit_log_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True, separators=(",", ":")))
            f.write("\n")
        try:
            os.chmod(path, 0o600)
        except (OSError, NotImplementedError):
            pass
    except Exception as exc:
        logger.warning("Could not write audit event %s: %s", event_type, exc)
        return False

    webhook_url = str(config.get("siem_webhook_url") or "").strip()
    if webhook_url:
        try:
            timeout = float(config.get("siem_timeout_seconds") or 2)
        except (TypeError, ValueError):
            timeout = 2.0
        _post_siem_webhook(webhook_url, event, timeout)

    return True

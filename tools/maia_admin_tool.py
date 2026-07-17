"""Governed self-administration tool for Maia gateway conversations."""

from __future__ import annotations

import json
from typing import Any

from agent.governance import Actor, has_explicit_user_access, is_enabled
from agent.governance_admin import (
    GovernanceAdminError,
    execute_governance_admin_action,
)
from gateway.session_context import get_session_env
from tools.registry import registry


def _gateway_actor() -> Actor:
    """Build the caller only from task-local gateway context.

    Deliberately ignores MAIA_USER_ID and model arguments: neither environment
    overrides nor prompt content may impersonate the human who sent a message.
    """

    return Actor(
        platform=get_session_env("HERMES_SESSION_PLATFORM", ""),
        user_id=get_session_env("HERMES_SESSION_USER_ID", ""),
        user_name=get_session_env("HERMES_SESSION_USER_NAME", ""),
    )


def check_maia_admin_requirements() -> bool:
    actor = _gateway_actor()
    return bool(
        actor.platform
        and actor.user_id
        and is_enabled()
        and has_explicit_user_access(actor)
    )


_PAYLOAD_KEYS = {
    "actor_key",
    "name",
    "roles",
    "teams",
    "gateway_admission",
    "file_access",
    "team",
    "members",
    "delegated_root",
    "path",
    "recursive",
    "policy",
}


def maia_admin(args: dict[str, Any], **_kwargs: Any) -> str:
    action = str(args.get("action") or "").strip().lower()
    payload = {key: args[key] for key in _PAYLOAD_KEYS if key in args}
    try:
        result = execute_governance_admin_action(
            action,
            payload,
            actor=_gateway_actor(),
        )
        return json.dumps(result, ensure_ascii=False)
    except GovernanceAdminError as exc:
        return json.dumps(
            {
                "success": False,
                "action": action,
                "error": str(exc),
                "code": exc.code,
            },
            ensure_ascii=False,
        )
    except Exception:
        # Do not expose config paths, secrets, or tracebacks through chat.
        return json.dumps(
            {
                "success": False,
                "action": action,
                "error": "Maia could not complete the governed administration action.",
                "code": "internal_error",
            }
        )


_FILE_GRANT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string"},
        "recursive": {"type": "boolean", "default": True},
        "read": {"type": "boolean", "default": False},
        "write": {"type": "boolean", "default": False},
        "write_approval_roles": {
            "type": "array",
            "items": {"type": "string"},
        },
        "write_approval_users": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["path"],
}

_POLICY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string"},
        "description": {"type": "string"},
        "roles": {"type": "array", "items": {"type": "string"}},
        "read_roles": {"type": "array", "items": {"type": "string"}},
        "write_roles": {"type": "array", "items": {"type": "string"}},
        "teams": {"type": "array", "items": {"type": "string"}},
        "read_teams": {"type": "array", "items": {"type": "string"}},
        "write_teams": {"type": "array", "items": {"type": "string"}},
        "deny_teams": {"type": "array", "items": {"type": "string"}},
        "users": {"type": "array", "items": {"type": "string"}},
        "read_users": {"type": "array", "items": {"type": "string"}},
        "write_users": {"type": "array", "items": {"type": "string"}},
        "deny_users": {"type": "array", "items": {"type": "string"}},
        "write_approval_roles": {
            "type": "array",
            "items": {"type": "string"},
        },
        "write_approval_users": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

registry.register(
    name="maia_admin",
    toolset="messaging",
    description=(
        "Safely administer this Maia installation from an authenticated gateway "
        "conversation. Use this instead of editing config.yaml or .env with file/terminal "
        "tools. The runtime derives the requesting human from the gateway message and "
        "rechecks Governance on every call. System admins may manage admitted users, roles, "
        "teams, direct grants, and folder policies. Team managers may only manage folder "
        "policies under delegated roots and for their own teams. Use inspect first when the "
        "requester's scope or current names are unclear. This tool never manages provider "
        "secrets or dashboard authentication credentials. Never use this tool merely because "
        "an authorized writer responded to an edit discussion: carrying out that edit and "
        "changing file-access policy are separate actions."
    ),
    schema={
        "name": "maia_admin",
        "description": (
            "Governed Maia administration for gateway users. Actions: inspect; upsert_user "
            "or remove_user; create_team, update_team, delete_team; set_file_policy or "
            "remove_file_policy. Authorization uses the authenticated sender, never an "
            "actor/requester argument. A conversational response about one file edit is not "
            "authorization to call this tool or modify access."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "inspect",
                        "upsert_user",
                        "remove_user",
                        "create_team",
                        "update_team",
                        "delete_team",
                        "set_file_policy",
                        "remove_file_policy",
                    ],
                },
                "actor_key": {
                    "type": "string",
                    "description": "Target stable identity in platform:user_id form. Never the requester.",
                },
                "name": {"type": "string"},
                "roles": {"type": "array", "items": {"type": "string"}},
                "teams": {"type": "array", "items": {"type": "string"}},
                "gateway_admission": {
                    "type": "boolean",
                    "description": "For user actions, also add/remove the target from the platform allowlist.",
                    "default": False,
                },
                "file_access": {
                    "type": "array",
                    "items": _FILE_GRANT_SCHEMA,
                    "description": "Replacement direct grants for the target user or team.",
                },
                "team": {"type": "string"},
                "members": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Governed platform:user_id identities assigned to the team.",
                },
                "delegated_root": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string"},
                        "manager_roles": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "managers": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "path": {"type": "string"},
                "recursive": {"type": "boolean", "default": True},
                "policy": _POLICY_SCHEMA,
            },
            "required": ["action"],
        },
    },
    handler=maia_admin,
    check_fn=check_maia_admin_requirements,
    requires_env=[],
    emoji="🛡️",
)

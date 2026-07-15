"""Per-user terminal sandbox mount resolution.

Translates a gateway user's governance folder policies into Docker bind-mount
specs so their shell / execute_code commands run in a container that can only
reach the folders they are actually granted. See docs/per-user-sandbox.md.

The resolver is pure (config + filesystem existence checks) and safe to unit
test without Docker. Gateway sessions register its output before the agent
starts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from agent.governance import (
    Actor,
    _governance_config_error,
    check_file_access,
    current_actor,
    file_write_approval_requirement,
    is_trusted_local_operator,
    load_governance_config,
    resolve_governed_path,
)


SECURE_EXECUTION_UNAVAILABLE_CODE = "secure_execution_unavailable"
_SECURE_EXECUTION_GUIDANCE = (
    "Do not tell the requester to ask for another file grant. Explain that Maia "
    "did not run the command because its secure Docker sandbox is unavailable, "
    "that no file was changed, and that an administrator must restore the "
    "sandbox runtime. Include the runtime diagnostic from the error when present "
    "so the administrator knows whether the image, network, or engine failed. "
    "Once it is ready, retry the same request; a new chat thread is not required."
)


def secure_execution_tool_error(
    reason: str,
    *,
    operation: str = "execute",
    resource: str = "terminal",
    runtime_status: str = "unavailable",
) -> str:
    """Return a retryable runtime failure distinct from an access denial."""

    message = str(reason or "Secure execution is unavailable.").strip()
    return json.dumps(
        {
            "error": message,
            "code": SECURE_EXECUTION_UNAVAILABLE_CODE,
            "blocked_by": "maia_secure_sandbox",
            "retryable": True,
            "permission_status": "unchanged",
            "runtime_status": runtime_status,
            "operation": operation,
            "resource": resource,
            "user_guidance": _SECURE_EXECUTION_GUIDANCE,
        },
        ensure_ascii=False,
    )


def sandbox_enabled(config: Optional[dict[str, Any]] = None) -> bool:
    """Return the immutable per-user gateway sandbox posture."""

    return True


def _policy_paths(config: dict[str, Any]) -> list[str]:
    policies = config.get("folder_policies")
    if not isinstance(policies, list):
        return []
    paths: list[str] = []
    for policy in policies:
        if isinstance(policy, dict) and str(policy.get("path") or "").strip():
            paths.append(str(policy["path"]).strip())
    return paths


def resolve_sandbox_mounts(
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Return ``host:container:mode`` Docker bind specs for *actor*'s folders.

    Only paths the actor can read or write (per governance folder policies) are
    mounted, default-deny by construction. Write-granted paths mount ``rw``;
    read-only and write-approval-gated paths mount ``ro`` so a shell cannot
    bypass staged approval. The container path equals the host path so absolute
    paths resolve identically inside and outside the container.

    Returns an empty list when governance is misconfigured — the
    caller must treat "no mounts" as "nothing granted" (fail closed), never as
    "mount everything".
    """

    cfg = load_governance_config() if config is None else config
    if _governance_config_error(cfg):
        return []

    who = current_actor() if actor is None else actor
    if is_trusted_local_operator(who, cfg):
        return []
    modes: dict[str, str] = {}

    for raw_path in _policy_paths(cfg):
        try:
            resolved = resolve_governed_path(raw_path)
        except (OSError, RuntimeError):
            continue
        if resolved is None:
            continue
        host = str(resolved)
        # Don't mount non-existent paths: docker -v would auto-create a
        # root-owned empty dir on the host, which is both surprising and a
        # small privilege footgun.
        if not os.path.exists(host):
            continue

        read_ok, _ = check_file_access(host, "read", actor=who, config=cfg)
        if not read_ok:
            continue

        mode = "ro"
        write_ok, _ = check_file_access(host, "write", actor=who, config=cfg)
        if write_ok:
            # A write that must be staged for approval must NOT be directly
            # writable from the shell — fail safe to ro so the file tool's
            # staging is the only path. Approvers (requirement resolves to
            # None) keep rw.
            requirement = file_write_approval_requirement(
                host, actor=who, config=cfg
            )
            mode = "ro" if requirement else "rw"

        # Most-permissive wins if the same resolved path appears twice.
        if modes.get(host) == "rw":
            continue
        modes[host] = mode

    return [f"{host}:{host}:{mode}" for host, mode in sorted(modes.items())]


def build_sandbox_overrides(
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return the ``register_task_env_overrides`` dict for a sandboxed session.

    Consumed by the gateway wiring (the increment that registers this per
    session). Kept here so the mount set and the override shape live together
    and can be unit-tested without the gateway.
    """

    return {
        "env_type": "docker",
        "governance_sandbox": True,
        "docker_volumes": resolve_sandbox_mounts(actor=actor, config=config),
        "cwd": "/workspace",
    }


def sandbox_backend_error(
    env_type: str,
    *,
    actor: Optional[Actor] = None,
    config: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Return a denial reason if the sandbox is on but cannot isolate.

    Fail closed: a per-user sandbox only isolates on the Docker backend. If the
    sandbox is enabled for a gateway (non-local) actor while the terminal
    backend is not Docker, refuse rather than run the user's commands
    unsandboxed on the host. The local operator is the single trust authority
    and is never sandboxed.
    """

    cfg = load_governance_config() if config is None else config
    if not sandbox_enabled(cfg):
        return None
    who = current_actor() if actor is None else actor
    if is_trusted_local_operator(who, cfg):
        return None
    if str(env_type or "").strip().lower() != "docker":
        return (
            "Per-user sandbox is enabled (governance.terminal.sandbox) but the "
            f"terminal backend is {env_type!r}, not 'docker', so commands "
            "cannot be isolated to your granted folders. Terminal is blocked "
            "until the server runs the Docker backend."
        )
    return None

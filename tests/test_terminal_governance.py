"""Tests for governance-gated terminal access and command approvals.

Covers governance.terminal.allowed_roles (who may run commands at all),
governance.terminal.approver_roles (who may APPROVE flagged commands —
the requester can no longer self-approve), and the identity-aware
resolver in tools.approval.
"""

import json


def _write_config(home, content: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(content, encoding="utf-8")


def _terminal_config(home, terminal_block: str) -> None:
    _write_config(
        home,
        f"""
governance:
  enabled: true
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_OPERATOR":
      roles: [operator]
    "slack:U_MANAGER":
      roles: [manager]
  terminal:
{terminal_block}
""",
    )


# ---------------------------------------------------------------------------
# governance.terminal_access_error
# ---------------------------------------------------------------------------

def test_terminal_access_denied_below_required_role(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _terminal_config(tmp_path, "    allowed_roles: [operator]")

    from agent.governance import Actor, terminal_access_error

    # Unknown user falls back to default_role viewer → denied.
    denied = terminal_access_error(
        actor=Actor(platform="slack", user_id="U_STRANGER")
    )
    assert denied is not None
    assert "not permitted to run commands" in denied

    # Operator and above pass.
    assert (
        terminal_access_error(actor=Actor(platform="slack", user_id="U_OPERATOR"))
        is None
    )
    assert (
        terminal_access_error(actor=Actor(platform="slack", user_id="U_MANAGER"))
        is None
    )


def test_terminal_access_unrestricted_when_unset_but_legacy_disabled_cannot_bypass(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from agent.governance import Actor, terminal_access_error

    # No terminal block at all.
    _write_config(tmp_path, "governance:\n  enabled: true\n")
    assert (
        terminal_access_error(actor=Actor(platform="slack", user_id="U_ANYONE"))
        is None
    )

    # A legacy disabled value cannot turn the gate off.
    _write_config(
        tmp_path,
        "governance:\n  enabled: false\n  terminal:\n    allowed_roles: [admin]\n",
    )
    assert "denied" in terminal_access_error(
        actor=Actor(platform="slack", user_id="U_ANYONE")
    ).lower()


def test_terminal_tool_blocks_denied_actor(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _terminal_config(tmp_path, "    allowed_roles: [operator]")
    monkeypatch.setenv("MAIA_USER_ID", "U_STRANGER")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "slack")

    from tools.terminal_tool import terminal_tool

    result = json.loads(terminal_tool(command="echo hi"))
    assert "Terminal access denied by governance" in (result.get("error") or "")
    assert result["code"] == "governance_access_denied"
    assert "manager or administrator" in result["user_guidance"]


def test_terminal_tool_distinguishes_unavailable_sandbox_from_file_denial(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MAIA_USER_ID", "U_OPERATOR")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "slack")
    _write_config(
        tmp_path,
        """
governance:
  enabled: false
  users:
    "slack:U_OPERATOR":
      roles: [operator]
  folder_policies: []
""",
    )

    from tools.terminal_tool import terminal_tool

    result = json.loads(terminal_tool(command="echo should-not-run"))
    assert result["code"] == "secure_execution_unavailable"
    assert result["resource"] == "terminal"
    assert result["retryable"] is True
    assert result["permission_status"] == "unchanged"
    assert "another file grant" in result["user_guidance"]
    assert "runtime diagnostic" in result["user_guidance"]
    assert "manager or administrator for access" not in result["user_guidance"]


def test_execute_code_distinguishes_unavailable_sandbox_from_file_denial(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MAIA_USER_ID", "U_OPERATOR")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "slack")
    _terminal_config(tmp_path, "    allowed_roles: [operator]")

    from tools import code_execution_tool
    from tools.terminal_tool import (
        clear_task_env_overrides,
        register_task_env_overrides,
    )

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("Docker Desktop WSL integration is disabled")

    monkeypatch.setattr(code_execution_tool, "_execute_remote", unavailable)
    register_task_env_overrides(
        "governed-code",
        {
            "env_type": "docker",
            "governance_sandbox": True,
            "docker_volumes": [],
        },
    )
    try:
        result = json.loads(
            code_execution_tool.execute_code(
                code="print('should not run')",
                task_id="governed-code",
            )
        )
    finally:
        clear_task_env_overrides("governed-code")

    assert result["code"] == "secure_execution_unavailable"
    assert result["resource"] == "execute_code"
    assert result["runtime_status"] == "wsl_integration_disabled"
    assert result["permission_status"] == "unchanged"


# ---------------------------------------------------------------------------
# governance.terminal_approval_requirement
# ---------------------------------------------------------------------------

def test_approval_requirement_applies_to_non_approvers_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _terminal_config(tmp_path, "    approver_roles: [manager]")

    from agent.governance import Actor, terminal_approval_requirement

    requirement = terminal_approval_requirement(
        actor=Actor(platform="slack", user_id="U_OPERATOR")
    )
    assert requirement is not None
    assert requirement["roles"] == ["manager"]

    # Managers satisfy the requirement themselves — self-approval stays.
    assert (
        terminal_approval_requirement(
            actor=Actor(platform="slack", user_id="U_MANAGER")
        )
        is None
    )


def test_no_requirement_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, "governance:\n  enabled: true\n")

    from agent.governance import Actor, terminal_approval_requirement

    assert (
        terminal_approval_requirement(
            actor=Actor(platform="slack", user_id="U_OPERATOR")
        )
        is None
    )


# ---------------------------------------------------------------------------
# tools.approval — identity-aware resolution
# ---------------------------------------------------------------------------

def _queue_entry(session_key: str, requirement):
    from tools import approval as approval_mod

    data = {"command": "rm -rf build", "description": "recursive delete"}
    if requirement:
        data["approval_requirement"] = requirement
        data["requested_by"] = "slack:U_OPERATOR"
    entry = approval_mod._ApprovalEntry(data)
    with approval_mod._lock:
        approval_mod._gateway_queues.setdefault(session_key, []).append(entry)
    return entry


def _clear_queue(session_key: str):
    from tools import approval as approval_mod

    with approval_mod._lock:
        approval_mod._gateway_queues.pop(session_key, None)


def test_identity_blind_resolve_fails_closed_on_requirement(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _terminal_config(tmp_path, "    approver_roles: [manager]")

    from tools.approval import resolve_gateway_approval

    session_key = "test:blind"
    entry = _queue_entry(session_key, {"roles": ["manager"], "users": []})
    try:
        count = resolve_gateway_approval(session_key, "once")
        assert count == 0
        assert entry.result is None
        assert not entry.event.is_set()
    finally:
        _clear_queue(session_key)


def test_requester_cannot_self_approve_but_manager_can(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _terminal_config(tmp_path, "    approver_roles: [manager]")

    from tools.approval import resolve_gateway_approval_detailed

    session_key = "test:gated"
    entry = _queue_entry(session_key, {"roles": ["manager"], "users": []})
    try:
        # The requesting operator clicks Approve — rejected, entry untouched.
        rejected = resolve_gateway_approval_detailed(
            session_key, "once",
            platform="slack", user_id="U_OPERATOR", user_name="operator",
        )
        assert rejected["resolved"] == 0
        assert rejected["rejected"] == 1
        assert "cannot approve" in rejected["reason"]
        assert entry.result is None

        # A manager approves — resolves and unblocks.
        approved = resolve_gateway_approval_detailed(
            session_key, "once",
            platform="slack", user_id="U_MANAGER", user_name="boss",
        )
        assert approved["resolved"] == 1
        assert entry.result == "once"
        assert entry.event.is_set()
    finally:
        _clear_queue(session_key)


def test_deny_stays_open_to_requester(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _terminal_config(tmp_path, "    approver_roles: [manager]")

    from tools.approval import resolve_gateway_approval_detailed

    session_key = "test:deny"
    entry = _queue_entry(session_key, {"roles": ["manager"], "users": []})
    try:
        result = resolve_gateway_approval_detailed(
            session_key, "deny",
            platform="slack", user_id="U_OPERATOR", user_name="operator",
        )
        assert result["resolved"] == 1
        assert entry.result == "deny"
    finally:
        _clear_queue(session_key)


def test_unrestricted_entries_resolve_as_before(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, "governance:\n  enabled: true\n")

    from tools.approval import resolve_gateway_approval

    session_key = "test:plain"
    entry = _queue_entry(session_key, None)
    try:
        count = resolve_gateway_approval(session_key, "once")
        assert count == 1
        assert entry.result == "once"
    finally:
        _clear_queue(session_key)

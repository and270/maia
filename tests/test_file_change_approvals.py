import json


def _write_config(home, content: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(content, encoding="utf-8")


def _governed_config(home, governed_dir, extra: str = "") -> None:
    _write_config(
        home,
        f"""
governance:
  enabled: true
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_WRITER":
      roles: [operator]
    "slack:U_MANAGER":
      roles: [manager]
    "slack:U_ADMIN":
      roles: [admin]
  folder_policies:
    - path: '{governed_dir}'
      write_users: ["slack:U_WRITER"]
      write_roles: [manager]
      write_approval_roles: [manager]
{extra}
""",
    )


def _as_writer(monkeypatch):
    monkeypatch.setenv("MAIA_USER_ID", "U_WRITER")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "slack")


# ---------------------------------------------------------------------------
# governance.file_write_approval_requirement
# ---------------------------------------------------------------------------

def test_requirement_applies_to_writer_but_not_to_approver(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent.governance import Actor, file_write_approval_requirement

    target = str(governed / "report.md")
    requirement = file_write_approval_requirement(
        target, actor=Actor(platform="slack", user_id="U_WRITER")
    )
    assert requirement is not None
    assert requirement["roles"] == ["manager"]

    # Managers satisfy the requirement themselves and can write directly.
    assert (
        file_write_approval_requirement(
            target, actor=Actor(platform="slack", user_id="U_MANAGER")
        )
        is None
    )
    # Role hierarchy: admins outrank managers.
    assert (
        file_write_approval_requirement(
            target, actor=Actor(platform="slack", user_id="U_ADMIN")
        )
        is None
    )


def test_child_policy_with_empty_lists_opts_out(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    open_dir = governed / "scratch"
    open_dir.mkdir(parents=True)
    _governed_config(
        tmp_path,
        governed,
        extra=f"""    - path: '{open_dir}'
      write_users: ["slack:U_WRITER"]
      write_approval_roles: []
""",
    )

    from agent.governance import Actor, file_write_approval_requirement

    writer = Actor(platform="slack", user_id="U_WRITER")
    assert (
        file_write_approval_requirement(str(governed / "report.md"), actor=writer)
        is not None
    )
    assert (
        file_write_approval_requirement(str(open_dir / "notes.md"), actor=writer)
        is None
    )


def test_requirement_survives_legacy_disabled_value(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: false
  folder_policies:
    - path: '{governed}'
      write_approval_roles: [manager]
""",
    )

    from agent.governance import Actor, file_write_approval_requirement

    requirement = file_write_approval_requirement(
        str(governed / "report.md"),
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )
    assert requirement is not None
    assert requirement["roles"] == ["manager"]


def test_eligible_approvers_resolved_from_role_map(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent.governance import eligible_file_change_approvers

    approvers = eligible_file_change_approvers({"roles": ["manager"], "users": []})
    assert "slack:U_MANAGER" in approvers
    assert "slack:U_ADMIN" in approvers  # hierarchy: admin >= manager
    assert "slack:U_WRITER" not in approvers

    approvers = eligible_file_change_approvers(
        {"roles": [], "users": ["discord:12345"]}
    )
    assert approvers == []


def test_named_manager_approver_can_inspect_and_execute_selected_path(tmp_path):
    from agent.governance import (
        Actor,
        check_file_access,
        eligible_file_change_approvers,
    )

    governed = tmp_path / "finance"
    config = {
        "enabled": True,
        "default_file_policy": "deny",
        "role_hierarchy": ["viewer", "operator", "manager", "admin"],
        "users": {
            "discord:WRITER": {"roles": ["operator"]},
            "discord:MANAGER": {"roles": ["manager"]},
        },
        "folder_policies": [
            {
                "path": str(governed),
                "write_users": ["discord:WRITER"],
                "write_approval_users": ["discord:MANAGER"],
            }
        ],
    }
    requirement = {"roles": [], "users": ["discord:MANAGER"]}
    target = str(governed / "numbers.xlsx")

    assert eligible_file_change_approvers(
        requirement,
        path=target,
        config=config,
    ) == ["discord:MANAGER"]
    for operation in ("read", "write"):
        allowed, reason = check_file_access(
            target,
            operation,
            actor=Actor(platform="discord", user_id="MANAGER"),
            config=config,
        )
        assert allowed is True
        assert reason == ""


def test_named_operator_cannot_become_file_approver(tmp_path):
    from agent.governance import eligible_file_change_approvers

    governed = tmp_path / "finance"
    config = {
        "enabled": True,
        "role_hierarchy": ["viewer", "operator", "manager", "admin"],
        "users": {"discord:OPERATOR": {"roles": ["operator"]}},
        "folder_policies": [
            {
                "path": str(governed),
                "write_users": ["discord:OPERATOR"],
                "write_approval_users": ["discord:OPERATOR"],
            }
        ],
    }

    assert eligible_file_change_approvers(
        {"roles": [], "users": ["discord:OPERATOR"]},
        path=str(governed / "numbers.xlsx"),
        config=config,
    ) == []


def test_file_grant_rejects_approval_role_with_no_eligible_identity():
    from agent.governance_admin import (
        GovernanceAdminError,
        replace_subject_file_grants,
    )
    import pytest

    governance = {
        "role_hierarchy": ["viewer", "operator", "manager", "admin"],
        "users": {"discord:WRITER": {"roles": ["operator"]}},
        "folder_policies": [],
    }
    with pytest.raises(GovernanceAdminError, match="no eligible approver"):
        replace_subject_file_grants(
            governance,
            subject="discord:WRITER",
            subject_kind="user",
            grants=[
                {
                    "path": "/srv/finance",
                    "recursive": True,
                    "read": True,
                    "write": True,
                    "write_approval_roles": ["manager"],
                    "write_approval_users": [],
                }
            ],
        )


def test_file_grant_requires_named_manager_or_admin_for_new_approval_mode():
    from agent.governance_admin import (
        GovernanceAdminError,
        replace_subject_file_grants,
    )
    import pytest

    governance = {
        "role_hierarchy": ["viewer", "operator", "manager", "admin"],
        "users": {
            "discord:WRITER": {"roles": ["operator"]},
            "discord:MANAGER": {"roles": ["manager"]},
        },
        "folder_policies": [],
    }
    grant = {
        "path": "/srv/finance",
        "recursive": True,
        "read": True,
        "write": True,
        "write_requires_approval": True,
        "write_approval_roles": [],
        "write_approval_users": [],
    }
    with pytest.raises(GovernanceAdminError, match="at least one named approver"):
        replace_subject_file_grants(
            governance,
            subject="discord:WRITER",
            subject_kind="user",
            grants=[grant],
        )

    grant["write_approval_users"] = ["discord:WRITER"]
    with pytest.raises(GovernanceAdminError, match="manager or administrator"):
        replace_subject_file_grants(
            governance,
            subject="discord:WRITER",
            subject_kind="user",
            grants=[grant],
        )

    grant["write_approval_users"] = ["discord:MANAGER"]
    replace_subject_file_grants(
        governance,
        subject="discord:WRITER",
        subject_kind="user",
        grants=[grant],
    )
    assert governance["folder_policies"] == [
        {
            "path": "/srv/finance",
            "recursive": True,
            "read_users": ["discord:WRITER"],
            "write_users": ["discord:WRITER"],
            "write_approval_roles": [],
            "write_approval_users": ["discord:MANAGER"],
        }
    ]


# ---------------------------------------------------------------------------
# stage / decide store behavior
# ---------------------------------------------------------------------------

def test_stage_and_approve_applies_change(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent.file_change_approvals import (
        decide_file_change_approval,
        list_file_change_approvals,
        stage_file_change,
    )
    from agent.governance import Actor

    target = governed / "report.md"
    staged = stage_file_change(
        path=str(target),
        content="approved content\n",
        requirement={"roles": ["manager"], "users": []},
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )
    assert staged["pending_approval"] is True
    assert staged["original_unchanged"] is True
    assert "slack:U_MANAGER" in staged["eligible_approvers"]
    assert "slack:U_ADMIN" in staged["eligible_approvers"]
    assert "Do not say" in staged["agent_instruction"]
    assert "conditional write access" in staged["agent_instruction"]
    assert "Never call `maia_admin`" in staged["agent_instruction"]
    assert not target.exists()

    pending = list_file_change_approvals("pending")
    assert len(pending) == 1
    assert pending[0]["id"] == staged["approval_id"]
    assert "+approved content" in pending[0]["diff"]

    # A non-approver cannot decide.
    denied = decide_file_change_approval(
        staged["approval_id"],
        approve=True,
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )
    assert denied["success"] is False
    assert denied.get("status_code") == 403
    assert not target.exists()

    decided = decide_file_change_approval(
        staged["approval_id"],
        approve=True,
        note="lgtm",
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert decided["success"] is True
    assert target.read_text(encoding="utf-8") == "approved content\n"
    assert decided["approval"]["status"] == "approved"

    # Already decided — cannot decide twice.
    again = decide_file_change_approval(
        staged["approval_id"],
        approve=False,
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert again["success"] is False


def test_deny_discards_change(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent.file_change_approvals import (
        decide_file_change_approval,
        stage_file_change,
    )
    from agent.governance import Actor

    target = governed / "report.md"
    staged = stage_file_change(
        path=str(target),
        content="rejected content",
        requirement={"roles": ["manager"], "users": []},
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )
    decided = decide_file_change_approval(
        staged["approval_id"],
        approve=False,
        note="not like this",
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert decided["success"] is True
    assert decided["approval"]["status"] == "denied"
    assert not target.exists()


def test_stage_fails_closed_when_no_identity_can_approve(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_WRITER":
      roles: [operator]
  folder_policies:
    - path: '{governed}'
      write_users: ["slack:U_WRITER"]
      write_approval_roles: [manager]
""",
    )

    from agent.file_change_approvals import (
        list_file_change_approvals,
        stage_file_change,
    )
    from agent.governance import Actor

    target = governed / "report.md"
    result = stage_file_change(
        path=str(target),
        content="proposed",
        requirement={"roles": ["manager"], "users": []},
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )
    assert result["success"] is False
    assert result["approval_unavailable"] is True
    assert result["original_unchanged"] is True
    assert "no configured governed identity" in result["error"]
    assert "read-only mount is the enforcement mechanism" in result["agent_instruction"]
    assert not target.exists()
    assert list_file_change_approvals("pending") == []


def test_binary_artifact_is_stored_outside_json_and_applied_exactly(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent import file_change_approvals as fca
    from agent.governance import Actor

    target = governed / "report.xlsx"
    target.write_bytes(b"old-workbook")
    source = tmp_path / "generated.xlsx"
    replacement = b"PK\x03\x04\x00\xffbinary-workbook\x00payload"
    source.write_bytes(replacement)

    staged = fca.stage_file_artifact(
        path=str(target),
        source_path=str(source),
        requirement={"roles": ["manager"], "users": []},
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )
    assert staged["pending_approval"] is True
    assert target.read_bytes() == b"old-workbook"

    request = fca.get_file_change_approval(staged["approval_id"])
    assert request["operation"] == "replace_file"
    assert "content" not in request
    assert request["artifact"]["size"] == len(replacement)
    payload = fca.artifacts_path() / request["artifact"]["storage_path"]
    assert payload.read_bytes() == replacement
    assert replacement.hex() not in fca.approvals_path().read_text(encoding="utf-8")

    decided = fca.decide_file_change_approval(
        staged["approval_id"],
        approve=True,
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert decided["success"] is True
    assert target.read_bytes() == replacement
    assert not payload.exists()


def test_binary_artifact_tampering_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent import file_change_approvals as fca
    from agent.governance import Actor

    target = governed / "report.pdf"
    source = tmp_path / "generated.pdf"
    source.write_bytes(b"%PDF-original-staged-payload")
    staged = fca.stage_file_artifact(
        path=str(target),
        source_path=str(source),
        requirement={"roles": ["manager"], "users": []},
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )
    request = fca.get_file_change_approval(staged["approval_id"])
    payload = fca.artifacts_path() / request["artifact"]["storage_path"]
    payload.write_bytes(b"%PDF-tampered-staged-payload")

    decided = fca.decide_file_change_approval(
        staged["approval_id"],
        approve=True,
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert decided["success"] is False
    assert "hash changed" in decided["error"]
    assert not target.exists()
    assert fca.get_file_change_approval(staged["approval_id"])["status"] == "pending"


def test_denied_binary_artifact_payload_is_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent import file_change_approvals as fca
    from agent.governance import Actor

    source = tmp_path / "generated.zip"
    source.write_bytes(b"PK\x03\x04archive")
    staged = fca.stage_file_artifact(
        path=str(governed / "archive.zip"),
        source_path=str(source),
        requirement={"roles": ["manager"], "users": []},
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )
    request = fca.get_file_change_approval(staged["approval_id"])
    payload = fca.artifacts_path() / request["artifact"]["storage_path"]

    decided = fca.decide_file_change_approval(
        staged["approval_id"],
        approve=False,
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert decided["success"] is True
    assert not payload.exists()


def test_stale_base_blocks_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent.file_change_approvals import (
        decide_file_change_approval,
        get_file_change_approval,
        stage_file_change,
    )
    from agent.governance import Actor

    target = governed / "report.md"
    target.write_text("original", encoding="utf-8")
    staged = stage_file_change(
        path=str(target),
        content="proposed",
        requirement={"roles": ["manager"], "users": []},
        actor=Actor(platform="slack", user_id="U_WRITER"),
    )

    # The file changes on disk after staging — the reviewed diff is stale.
    target.write_text("changed externally", encoding="utf-8")

    decided = decide_file_change_approval(
        staged["approval_id"],
        approve=True,
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert decided["success"] is False
    assert decided.get("status_code") == 409
    assert target.read_text(encoding="utf-8") == "changed externally"
    assert get_file_change_approval(staged["approval_id"])["status"] == "stale"


def test_notifier_fires_on_stage(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from agent import file_change_approvals as fca
    from agent.governance import Actor

    seen = []
    fca.set_file_approval_notifier(seen.append)
    try:
        staged = fca.stage_file_change(
            path=str(governed / "report.md"),
            content="content",
            requirement={"roles": ["manager"], "users": []},
            actor=Actor(platform="slack", user_id="U_WRITER"),
        )
    finally:
        fca.set_file_approval_notifier(None)

    assert len(seen) == 1
    assert seen[0]["id"] == staged["approval_id"]
    assert seen[0]["requirement"]["roles"] == ["manager"]


# ---------------------------------------------------------------------------
# file tools integration
# ---------------------------------------------------------------------------

def test_write_file_tool_blocks_conditional_writer_without_staging(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    _as_writer(monkeypatch)

    from agent.file_change_approvals import list_file_change_approvals
    from tools.file_tools import write_file_tool

    target = governed / "report.md"
    result = json.loads(write_file_tool(str(target), "hello governed world"))
    assert result["success"] is False
    assert result["code"] == "governed_write_review_required"
    assert result["approval_required"] is True
    assert result["planning_only"] is True
    assert result["original_unchanged"] is True
    assert "conditional write access" in result["error"]
    assert "slack:U_MANAGER" in result["eligible_approvers"]
    assert "slack:U_ADMIN" in result["same_platform_approvers"]
    assert result["approver_mention_text"] == "<@U_MANAGER> <@U_ADMIN>"
    assert result["same_platform_approver_mentions"] == [
        "<@U_MANAGER>",
        "<@U_ADMIN>",
    ]
    assert "Do not say the requester lacks write access" in result["agent_instruction"]
    assert "Do not stage or queue" in result["agent_instruction"]
    assert not target.exists()
    assert list_file_change_approvals("pending") == []


def test_discord_admin_is_mentioned_and_can_execute_the_reviewed_edit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_file_policy: deny
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "discord:WRITER":
      roles: [operator]
    "discord:ADMIN":
      roles: [admin]
  folder_policies:
    - path: '{governed}'
      read_users: ["discord:WRITER"]
      write_users: ["discord:WRITER"]
      write_approval_users: ["discord:ADMIN"]
""",
    )

    from tools import file_tools

    class Result:
        def to_dict(self):
            return {"success": True}

    class FileOps:
        def write_file(self, path, content):
            target.write_text(content, encoding="utf-8")
            return Result()

    target = governed / "numbers.xlsx"
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda _task_id: FileOps())
    monkeypatch.setenv("MAIA_USER_PLATFORM", "discord")
    monkeypatch.setenv("MAIA_USER_ID", "WRITER")

    blocked = json.loads(file_tools.write_file_tool(str(target), "reviewed"))
    assert blocked["code"] == "governed_write_review_required"
    assert blocked["eligible_approvers"] == ["discord:ADMIN"]
    assert blocked["approver_mention_text"] == "<@ADMIN>"
    assert "<@ADMIN>" in blocked["error"]
    assert not target.exists()

    monkeypatch.setenv("MAIA_USER_ID", "ADMIN")
    written = json.loads(file_tools.write_file_tool(str(target), "reviewed"))
    assert written["success"] is True
    assert target.read_text(encoding="utf-8") == "reviewed"


def test_write_file_tool_writes_directly_for_approver(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    monkeypatch.setenv("MAIA_USER_ID", "U_MANAGER")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "slack")

    from tools import file_tools

    class Result:
        def to_dict(self):
            return {"success": True}

    class FileOps:
        def write_file(self, path, content):
            target.write_text(content, encoding="utf-8")
            return Result()

    target = governed / "report.md"
    monkeypatch.setattr(file_tools, "_get_file_ops", lambda _task_id: FileOps())
    result = json.loads(
        file_tools.write_file_tool(str(target), "manager writes directly")
    )
    assert result.get("pending_approval") is None
    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "manager writes directly"


def test_shared_conversation_rechecks_authenticated_sender_on_each_tool_call(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("MAIA_USER_ID", raising=False)
    monkeypatch.delenv("MAIA_USER_PLATFORM", raising=False)
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)

    from gateway.session_context import clear_session_vars, set_session_vars
    from tools import file_tools

    target = governed / "report.md"

    class Result:
        def to_dict(self):
            return {"success": True}

    class FileOps:
        def write_file(self, path, content):
            target.write_text(content, encoding="utf-8")
            return Result()

    monkeypatch.setattr(file_tools, "_get_file_ops", lambda _task_id: FileOps())
    session_key = "agent:main:slack:channel:C1:T1"

    writer_tokens = set_session_vars(
        platform="slack",
        chat_id="C1",
        thread_id="T1",
        user_id="U_WRITER",
        user_name="Employee",
        session_key=session_key,
    )
    try:
        blocked = json.loads(
            file_tools.write_file_tool(str(target), "manager-approved result")
        )
    finally:
        clear_session_vars(writer_tokens)

    assert blocked["code"] == "governed_write_review_required"
    assert blocked["requester"] == "slack:U_WRITER"
    assert not target.exists()

    manager_tokens = set_session_vars(
        platform="slack",
        chat_id="C1",
        thread_id="T1",
        user_id="U_MANAGER",
        user_name="Manager",
        session_key=session_key,
    )
    try:
        written = json.loads(
            file_tools.write_file_tool(str(target), "manager-approved result")
        )
    finally:
        clear_session_vars(manager_tokens)

    assert written["success"] is True
    assert target.read_text(encoding="utf-8") == "manager-approved result"


def test_replace_file_tool_blocks_before_export_for_conditional_writer(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    _as_writer(monkeypatch)

    class RemoteEnvironment:
        pass

    class FakeFileOps:
        env = RemoteEnvironment()

        def export_file_to_host(self, source_path, destination_path, *, max_bytes):
            raise AssertionError("conditional writer must be blocked before export")

    from tools import file_tools

    monkeypatch.setattr(file_tools, "_get_file_ops", lambda task_id: FakeFileOps())
    target = governed / "report.xlsx"
    target.write_bytes(b"old")
    result = json.loads(
        file_tools.replace_file_tool(
            "/tmp/updated.xlsx", str(target), note="Updated expenses"
        )
    )
    assert result["code"] == "governed_write_review_required"
    assert result["planning_only"] is True
    assert target.read_bytes() == b"old"


def test_replace_file_tool_applies_directly_when_no_approval_is_required(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    monkeypatch.setenv("MAIA_USER_ID", "U_MANAGER")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "slack")

    replacement = b"%PDF-direct-generated-file"

    class RemoteEnvironment:
        pass

    class FakeFileOps:
        env = RemoteEnvironment()

        def export_file_to_host(self, source_path, destination_path, *, max_bytes):
            destination_path.write_bytes(replacement)
            return {"success": True, "bytes": len(replacement)}

    from tools import file_tools

    monkeypatch.setattr(file_tools, "_get_file_ops", lambda task_id: FakeFileOps())
    target = governed / "report.pdf"
    result = json.loads(
        file_tools.replace_file_tool("/tmp/report.pdf", str(target))
    )
    assert result["success"] is True
    assert result.get("pending_approval") is None
    assert target.read_bytes() == replacement


def test_patch_replace_blocks_conditional_writer_without_staging(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    _as_writer(monkeypatch)

    target = governed / "report.md"
    target.write_text("total: 100\nnotes: draft\n", encoding="utf-8")

    from tools.file_tools import patch_tool

    result = json.loads(
        patch_tool(
            mode="replace",
            path=str(target),
            old_string="total: 100",
            new_string="total: 250",
        )
    )
    assert result["code"] == "governed_write_review_required"
    assert result["planning_only"] is True
    assert target.read_text(encoding="utf-8") == "total: 100\nnotes: draft\n"


def test_patch_v4a_returns_same_review_block_on_gated_paths(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    _as_writer(monkeypatch)

    target = governed / "report.md"
    target.write_text("line\n", encoding="utf-8")

    from tools.file_tools import patch_tool

    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {target}\n"
        "@@\n"
        "-line\n"
        "+edited\n"
        "*** End Patch\n"
    )
    result = json.loads(patch_tool(mode="patch", patch=patch))
    assert result["code"] == "governed_write_review_required"
    assert result["planning_only"] is True
    assert target.read_text(encoding="utf-8") == "line\n"

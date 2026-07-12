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

    # Managers satisfy the requirement themselves — no staging for them.
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
    assert approvers == ["discord:12345"]


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

def test_write_file_tool_stages_instead_of_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    _as_writer(monkeypatch)

    from tools.file_tools import write_file_tool
    from agent.file_change_approvals import decide_file_change_approval
    from agent.governance import Actor

    target = governed / "report.md"
    result = json.loads(write_file_tool(str(target), "hello governed world"))
    assert result.get("pending_approval") is True
    assert not target.exists()

    decided = decide_file_change_approval(
        result["approval_id"],
        approve=True,
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert decided["success"] is True
    assert target.read_text(encoding="utf-8") == "hello governed world"


def test_write_file_tool_writes_directly_for_approver(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    monkeypatch.setenv("MAIA_USER_ID", "U_MANAGER")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "slack")

    from tools.file_tools import write_file_tool

    target = governed / "report.md"
    result = json.loads(write_file_tool(str(target), "manager writes directly"))
    assert result.get("pending_approval") is None
    assert target.read_text(encoding="utf-8") == "manager writes directly"


def test_patch_replace_stages_final_content(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    governed = tmp_path / "finance"
    governed.mkdir()
    _governed_config(tmp_path, governed)
    _as_writer(monkeypatch)

    target = governed / "report.md"
    target.write_text("total: 100\nnotes: draft\n", encoding="utf-8")

    from tools.file_tools import patch_tool
    from agent.file_change_approvals import get_file_change_approval

    result = json.loads(
        patch_tool(
            mode="replace",
            path=str(target),
            old_string="total: 100",
            new_string="total: 250",
        )
    )
    assert result.get("pending_approval") is True
    # Nothing applied yet.
    assert target.read_text(encoding="utf-8") == "total: 100\nnotes: draft\n"

    staged = get_file_change_approval(result["approval_id"])
    assert staged["content"] == "total: 250\nnotes: draft\n"
    assert "-total: 100" in staged["diff"]
    assert "+total: 250" in staged["diff"]


def test_patch_v4a_rejected_on_gated_paths(tmp_path, monkeypatch):
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
    assert "require human approval" in result.get("error", "")
    assert target.read_text(encoding="utf-8") == "line\n"

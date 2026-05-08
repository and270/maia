import json


def _write_config(home, content: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(content, encoding="utf-8")


def test_folder_policy_uses_role_hierarchy(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    finance_dir = tmp_path / "finance"
    finance_dir.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_MANAGER":
      roles: [manager]
    "slack:U_VIEWER":
      roles: [viewer]
  folder_policies:
    - path: "{finance_dir}"
      read_roles: [manager]
      write_roles: [admin]
""",
    )

    from agent.governance import Actor, check_file_access

    target = str(finance_dir / "report.md")
    allowed, _ = check_file_access(
        target,
        "read",
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert allowed is True

    allowed, reason = check_file_access(
        target,
        "read",
        actor=Actor(platform="slack", user_id="U_VIEWER"),
    )
    assert allowed is False
    assert "lacks read access" in reason

    allowed, _ = check_file_access(
        target,
        "write",
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )
    assert allowed is False


def test_folder_policy_default_deny_blocks_unmatched_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    allowed_dir = tmp_path / "allowed"
    blocked_dir = tmp_path / "blocked"
    allowed_dir.mkdir()
    blocked_dir.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_role: viewer
  default_file_policy: deny
  folder_policies:
    - path: "{allowed_dir}"
      read_roles: [viewer]
""",
    )

    from agent.governance import Actor, check_file_access

    allowed, _ = check_file_access(
        str(allowed_dir / "notes.md"),
        "read",
        actor=Actor(platform="slack", user_id="U_VIEWER"),
    )
    assert allowed is True

    allowed, reason = check_file_access(
        str(blocked_dir / "notes.md"),
        "read",
        actor=Actor(platform="slack", user_id="U_VIEWER"),
    )
    assert allowed is False
    assert "no folder policy allows read" in reason


def test_folder_policy_designated_users_and_explicit_denies(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    legal_dir = tmp_path / "legal"
    legal_dir.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_VIEWER":
      roles: [viewer]
    "slack:U_BLOCKED":
      roles: [admin]
  folder_policies:
    - path: "{legal_dir}"
      read_roles: [manager]
      read_users: ["slack:U_VIEWER"]
      deny_users: ["slack:U_BLOCKED"]
""",
    )

    from agent.governance import Actor, check_file_access

    allowed, _ = check_file_access(
        str(legal_dir / "contract.md"),
        "read",
        actor=Actor(platform="slack", user_id="U_VIEWER"),
    )
    assert allowed is True

    allowed, reason = check_file_access(
        str(legal_dir / "contract.md"),
        "read",
        actor=Actor(platform="slack", user_id="U_BLOCKED"),
    )
    assert allowed is False
    assert "explicitly denied" in reason


def test_folder_policy_supports_team_read_write_and_team_denies(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    marketing_dir = tmp_path / "marketing"
    marketing_dir.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_role: viewer
  users:
    "slack:U_LEAD":
      roles: [manager]
      teams: [marketing]
    "slack:U_ANALYST":
      roles: [operator]
      teams: [marketing]
    "slack:U_BLOCKED":
      roles: [operator]
      teams: [marketing]
    "slack:U_FINANCE":
      roles: [operator]
      teams: [finance]
  folder_policies:
    - path: "{marketing_dir}"
      read_teams: [marketing]
      write_users: ["slack:U_LEAD"]
      deny_users: ["slack:U_BLOCKED"]
""",
    )

    from agent.governance import Actor, check_file_access

    target = str(marketing_dir / "campaign.md")
    allowed, _ = check_file_access(
        target,
        "read",
        actor=Actor(platform="slack", user_id="U_ANALYST"),
    )
    assert allowed is True

    allowed, _ = check_file_access(
        target,
        "write",
        actor=Actor(platform="slack", user_id="U_LEAD"),
    )
    assert allowed is True

    allowed, reason = check_file_access(
        target,
        "write",
        actor=Actor(platform="slack", user_id="U_ANALYST"),
    )
    assert allowed is False
    assert "lacks write access" in reason
    assert "allowed users: ['slack:U_LEAD']" in reason

    allowed, reason = check_file_access(
        target,
        "read",
        actor=Actor(platform="slack", user_id="U_FINANCE"),
    )
    assert allowed is False
    assert "lacks read access" in reason

    allowed, reason = check_file_access(
        target,
        "read",
        actor=Actor(platform="slack", user_id="U_BLOCKED"),
    )
    assert allowed is False
    assert "explicitly denied" in reason


def test_file_tool_governance_uses_resolved_task_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "secret.txt").write_text("restricted\n", encoding="utf-8")
    monkeypatch.setenv("TERMINAL_CWD", str(workspace))
    monkeypatch.chdir(tmp_path)
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  role_hierarchy: [viewer, manager, admin]
  users:
    "local":
      roles: [viewer]
  folder_policies:
    - path: "{workspace}"
      read_roles: [manager]
""",
    )

    from tools.file_tools import read_file_tool

    result = json.loads(read_file_tool("secret.txt"))
    assert "error" in result
    assert "Access denied by governance" in result["error"]


def test_cron_authorization_respects_governance_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "slack")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "U_MANAGER")
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_MANAGER":
      roles: [manager]
""",
    )

    import cron.jobs as jobs_mod
    from cron.jobs import create_job, request_job_authorization
    from tools.cronjob_tools import cronjob

    cron_dir = tmp_path / "cron"
    monkeypatch.setattr(jobs_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", cron_dir / "output")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", cron_dir / "jobs.json")

    job = create_job(
        prompt="Prepare the report",
        schedule="30m",
        authorization={"required": True, "roles": ["manager"]},
    )
    paused = request_job_authorization(job["id"])
    assert paused["state"] == "awaiting_authorization"

    result = json.loads(cronjob(action="authorize", job_id=job["id"]))
    assert result["success"] is True
    assert result["job"]["authorization"]["status"] == "approved"
    assert result["job"]["enabled"] is True


def test_cron_authorization_rejects_unauthorized_actor(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "slack")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "U_VIEWER")
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_VIEWER":
      roles: [viewer]
""",
    )

    import cron.jobs as jobs_mod
    from cron.jobs import create_job, get_job, request_job_authorization
    from tools.cronjob_tools import cronjob

    cron_dir = tmp_path / "cron"
    monkeypatch.setattr(jobs_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", cron_dir / "output")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", cron_dir / "jobs.json")

    job = create_job(
        prompt="Prepare the report",
        schedule="30m",
        authorization={"required": True, "roles": ["manager"]},
    )
    request_job_authorization(job["id"])

    result = json.loads(cronjob(action="authorize", job_id=job["id"]))
    assert result["success"] is False
    assert "Required roles: ['manager']" in result["error"]
    stored = get_job(job["id"])
    assert stored["state"] == "awaiting_authorization"
    assert stored["authorization"]["status"] == "pending"

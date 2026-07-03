import json


def _write_config(home, content: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(content, encoding="utf-8")


def test_folder_policy_uses_role_hierarchy(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
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
    - path: '{finance_dir}'
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
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
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
    - path: '{allowed_dir}'
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


def test_malformed_governance_config_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        'governance:\n  enabled: true\n  folder_policies:\n    - path: "C:\\secrets"\n',
    )

    from agent.governance import Actor, check_file_access, load_governance_config

    cfg = load_governance_config()
    assert cfg["enabled"] is True
    assert "__config_load_error__" in cfg

    allowed, reason = check_file_access(
        str(tmp_path / "anything.txt"),
        "read",
        actor=Actor(platform="slack", user_id="U_MANAGER"),
    )

    assert allowed is False
    assert "config.yaml could not be loaded" in reason
    assert "blocked until the governance configuration is fixed" in reason


def test_folder_policy_designated_users_and_explicit_denies(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
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
    - path: '{legal_dir}'
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
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
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
    - path: '{marketing_dir}'
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
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
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
    - path: '{workspace}'
      read_roles: [manager]
""",
    )

    from tools.file_tools import read_file_tool

    result = json.loads(read_file_tool("secret.txt"))
    assert "error" in result
    assert "Access denied by governance" in result["error"]


def test_cron_authorization_respects_governance_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
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
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
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


def test_cron_authorization_fails_closed_when_config_is_malformed(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "slack")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "U_MANAGER")
    _write_config(
        tmp_path,
        'governance:\n  enabled: true\n  folder_policies:\n    - path: "C:\\secrets"\n',
    )

    from agent.governance import can_authorize

    allowed, reason = can_authorize({"required": True, "roles": ["manager"]})

    assert allowed is False
    assert "Cron authorization denied by governance" in reason
    assert "config.yaml could not be loaded" in reason


def test_self_configuration_context_is_actor_and_role_aware(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    marketing_dir = tmp_path / "marketing"
    marketing_dir.mkdir()
    _write_config(
        tmp_path,
        f"""
dashboard:
  auth:
    enabled: true
    read_roles: [auditor, manager, admin]
    manage_roles: [manager, admin]
    admin_roles: [admin]
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_MARKETING":
      roles: [manager]
      teams: [marketing]
  team_file_roots:
    marketing:
      path: '{marketing_dir}'
      manager_roles: [manager]
  cron:
    default_authorizer_roles: [admin]
""",
    )

    from agent.governance import Actor, render_self_configuration_context

    text = render_self_configuration_context(
        actor=Actor(platform="slack", user_id="U_MARKETING")
    )

    assert "Actor: slack:U_MARKETING" in text
    assert "Roles: manager" in text
    assert "Teams: marketing" in text
    assert "Read dashboard data: yes" in text
    assert "Manage approvals or delegated File Access: yes" in text
    assert (
        "Administer config, secrets, models, gateway settings, dashboard auth, "
        "user authorization, plugins, global folder policies, and roles: no"
    ) in text
    assert str({"marketing": str(marketing_dir)}) in text
    assert "Management-scope actions are limited" in text


def test_malformed_folder_policies_fail_closed(tmp_path, monkeypatch):
    """folder_policies written as a mapping (not a list) must deny, not fall
    through to the permissive default_file_policy."""
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  default_file_policy: allow
  folder_policies:
    finance:
      path: /company/finance
      read_roles: [manager]
""",
    )

    from agent.governance import Actor, check_file_access

    allowed, reason = check_file_access(
        "/company/finance/secret.txt", "read",
        actor=Actor(platform="slack", user_id="U1"),
    )
    assert allowed is False
    assert "misconfigured" in reason


def test_typo_default_file_policy_fails_closed(tmp_path, monkeypatch):
    """A default_file_policy that isn't 'allow'/'deny' (e.g. a typo) must fail
    closed rather than silently allowing."""
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  default_file_policy: denyy
""",
    )

    from agent.governance import Actor, check_file_access

    allowed, reason = check_file_access(
        "/anywhere/file.txt", "write",
        actor=Actor(platform="slack", user_id="U1"),
    )
    assert allowed is False
    assert "unrecognized value" in reason


def test_wellformed_deny_default_still_denies_unmatched(tmp_path, monkeypatch):
    """Sanity: a valid deny default with a valid policy list still behaves."""
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  default_file_policy: deny
  role_hierarchy: [viewer, admin]
  folder_policies:
    - path: /company/public
      read_roles: [viewer]
""",
    )

    from agent.governance import Actor, check_file_access

    # Unmatched path under deny default → denied.
    allowed, _ = check_file_access(
        "/company/private/x.txt", "read",
        actor=Actor(platform="slack", user_id="U1"),
    )
    assert allowed is False


def test_parent_deny_cascades_to_child_policy(tmp_path, monkeypatch):
    """An explicit deny on a parent folder must not be re-granted by a child
    folder's own policy (least privilege / ancestor-deny cascade)."""
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  role_hierarchy: [viewer, manager, admin]
  users:
    'slack:U_BAD':
      roles: [manager]
    'slack:U_OK':
      roles: [manager]
  folder_policies:
    - path: /company
      deny_users: ['slack:U_BAD']
    - path: /company/finance
      read_roles: [manager]
""",
    )

    from agent.governance import Actor, check_file_access

    # Denied on the parent — must stay denied under the child policy.
    bad, _ = check_file_access(
        "/company/finance/ledger.csv", "read",
        actor=Actor(platform="slack", user_id="U_BAD"),
    )
    assert bad is False

    # A different manager (not denied) is still granted by the child policy.
    ok, _ = check_file_access(
        "/company/finance/ledger.csv", "read",
        actor=Actor(platform="slack", user_id="U_OK"),
    )
    assert ok is True

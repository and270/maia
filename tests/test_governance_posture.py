"""Tests for the shared governance posture health check."""


def _write_config(home, content: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(content, encoding="utf-8")


def _codes(warnings):
    return {w["code"] for w in warnings}


def test_legacy_disabled_governance_is_still_assessed(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, "governance:\n  enabled: false\n")

    from agent.governance import governance_posture_warnings

    codes = {warning["code"] for warning in governance_posture_warnings()}
    assert "no_folder_policies" in codes


def test_enabled_but_permissive_flags_every_weakness(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # Enabled, no policies, no terminal gate, approvals off, audit off.
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
approvals:
  mode: "off"
observability:
  audit_log_enabled: false
""",
    )

    from agent.governance import governance_posture_warnings

    codes = _codes(governance_posture_warnings())
    assert "no_folder_policies" in codes
    assert "terminal_ungoverned" in codes
    assert "approvals_off" in codes
    assert "audit_disabled" in codes


def test_hardened_config_has_no_warnings(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    finance = tmp_path / "finance"
    finance.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_file_policy: deny
  role_hierarchy: [viewer, operator, manager, admin]
  terminal:
    allowed_roles: [operator]
    approver_roles: [manager]
  folder_policies:
    - path: '{finance}'
      read_roles: [manager]
approvals:
  mode: smart
observability:
  audit_log_enabled: true
""",
    )

    from agent.governance import governance_posture_warnings

    assert governance_posture_warnings() == []


def test_partial_hardening_flags_only_the_gap(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    finance = tmp_path / "finance"
    finance.mkdir()
    # Files locked down, audit on, but terminal is still ungated.
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_file_policy: deny
  folder_policies:
    - path: '{finance}'
      read_roles: [manager]
approvals:
  mode: smart
observability:
  audit_log_enabled: true
""",
    )

    from agent.governance import governance_posture_warnings

    codes = _codes(governance_posture_warnings())
    assert codes == {"terminal_ungoverned"}


def test_delegated_team_root_counts_as_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  default_file_policy: deny
  team_file_roots:
    marketing:
      path: "/srv/company/marketing"
  terminal:
    approver_roles: [manager]
approvals:
  mode: smart
observability:
  audit_log_enabled: true
""",
    )

    from agent.governance import governance_posture_warnings

    # team_file_roots satisfies the "no policies" check even with no
    # folder_policies list.
    assert "no_folder_policies" not in _codes(governance_posture_warnings())


def test_write_approval_without_matching_identity_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    discord:writer:
      roles: [operator]
  folder_policies:
    - path: "/srv/reviewed"
      write_users: ["discord:writer"]
      write_approval_roles: [manager]
""",
    )

    from agent.governance import governance_posture_warnings

    warnings = governance_posture_warnings()
    unreachable = [
        item
        for item in warnings
        if item["code"] == "file_approval_without_eligible_identity"
    ]
    assert len(unreachable) == 1
    assert unreachable[0]["severity"] == "error"
    assert "remain unchanged" in unreachable[0]["message"]


def test_write_approval_role_is_reachable_through_higher_role(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
governance:
  enabled: true
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    discord:writer:
      roles: [operator]
    discord:administrator:
      roles: [admin]
  folder_policies:
    - path: "/srv/reviewed"
      write_users: ["discord:writer"]
      write_approval_roles: [manager]
""",
    )

    from agent.governance import governance_posture_warnings

    assert "file_approval_without_eligible_identity" not in _codes(
        governance_posture_warnings()
    )


def test_config_error_surfaces_as_single_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # Malformed YAML → load error.
    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "config.yaml").write_text("governance: [oops\n", encoding="utf-8")

    from agent.governance import governance_posture_warnings

    warnings = governance_posture_warnings()
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "error"
    assert warnings[0]["code"] == "config_error"

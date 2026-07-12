"""Tests for the per-user terminal sandbox mount resolver."""


def _write_config(home, content: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(content, encoding="utf-8")


def _mode_for(mounts, path):
    """Return 'ro'/'rw' for *path*, or None if not mounted.

    The mount spec is ``host:container:mode`` with container == host. Rebuilding
    the exact expected spec avoids ambiguous colon-splitting (host paths contain
    a drive-letter colon on the Windows dev box; real server paths do not).
    """
    host = str(path)
    if f"{host}:{host}:rw" in mounts:
        return "rw"
    if f"{host}:{host}:ro" in mounts:
        return "ro"
    return None


def test_sandbox_enabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, "governance:\n  enabled: true\n")

    from agent.sandbox import sandbox_enabled

    assert sandbox_enabled() is True


def test_sandbox_enabled_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        "governance:\n  enabled: true\n  terminal:\n    sandbox:\n      enabled: true\n",
    )

    from agent.sandbox import sandbox_enabled

    assert sandbox_enabled() is True


def test_mounts_reflect_read_write_grants(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    shared = tmp_path / "shared"
    marketing = tmp_path / "marketing"
    finance = tmp_path / "finance"
    for d in (shared, marketing, finance):
        d.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_file_policy: deny
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_BRUNO":
      roles: [operator]
      teams: [marketing]
  folder_policies:
    - path: '{shared}'
      read_roles: [operator]
    - path: '{marketing}'
      read_teams: [marketing]
      write_teams: [marketing]
    - path: '{finance}'
      read_roles: [admin]
      write_roles: [admin]
""",
    )

    from agent.governance import Actor
    from agent.sandbox import resolve_sandbox_mounts

    bruno = Actor(platform="slack", user_id="U_BRUNO")
    M = resolve_sandbox_mounts(actor=bruno)

    assert _mode_for(M, shared) == "ro"       # read-only grant
    assert _mode_for(M, marketing) == "rw"    # team read+write
    assert _mode_for(M, finance) is None            # no access → not mounted


def test_write_approval_folder_mounts_readonly_for_requester(tmp_path, monkeypatch):
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
  users:
    "slack:U_FELIPE":
      roles: [operator]
    "slack:U_MANAGER":
      roles: [manager]
  folder_policies:
    - path: '{finance}'
      read_users: ["slack:U_FELIPE"]
      read_roles: [manager]
      write_users: ["slack:U_FELIPE"]
      write_roles: [manager]
      write_approval_roles: [manager]
""",
    )

    from agent.governance import Actor
    from agent.sandbox import resolve_sandbox_mounts

    # Felipe can write, but writes are approval-gated → shell mount is ro so he
    # cannot bypass staging from the terminal.
    felipe = Actor(platform="slack", user_id="U_FELIPE")
    assert _mode_for(resolve_sandbox_mounts(actor=felipe), finance) == "ro"

    # The manager is an approver (writes directly) → rw.
    manager = Actor(platform="slack", user_id="U_MANAGER")
    assert _mode_for(resolve_sandbox_mounts(actor=manager), finance) == "rw"


def test_nonexistent_paths_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    real = tmp_path / "real"
    real.mkdir()
    ghost = tmp_path / "ghost"  # never created
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_file_policy: deny
  users:
    "slack:U1":
      roles: [admin]
  role_hierarchy: [viewer, admin]
  folder_policies:
    - path: '{real}'
      read_roles: [admin]
      write_roles: [admin]
    - path: '{ghost}'
      read_roles: [admin]
      write_roles: [admin]
""",
    )

    from agent.governance import Actor
    from agent.sandbox import resolve_sandbox_mounts

    M = resolve_sandbox_mounts(actor=Actor(platform="slack", user_id="U1"))
    assert _mode_for(M, real) is not None
    assert _mode_for(M, ghost) is None


def test_disabled_governance_yields_no_mounts(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, "governance:\n  enabled: false\n")

    from agent.governance import Actor
    from agent.sandbox import resolve_sandbox_mounts

    assert resolve_sandbox_mounts(actor=Actor(platform="slack", user_id="U1")) == []


# ---------------------------------------------------------------------------
# sandbox_backend_error — fail-closed guard
# ---------------------------------------------------------------------------

def _sandbox_on(tmp_path):
    _write_config(
        tmp_path,
        "governance:\n  enabled: true\n  terminal:\n    sandbox:\n      enabled: true\n",
    )


def test_backend_error_fails_closed_when_legacy_sandbox_setting_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(tmp_path, "governance:\n  enabled: true\n")

    from agent.governance import Actor
    from agent.sandbox import sandbox_backend_error

    assert "blocked" in sandbox_backend_error(
        "local", actor=Actor(platform="slack", user_id="U1")
    ).lower()


def test_backend_error_exempts_local_operator(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _sandbox_on(tmp_path)

    from agent.governance import Actor
    from agent.sandbox import sandbox_backend_error

    # Local CLI operator is the trust authority — never sandboxed, never blocked.
    assert sandbox_backend_error("local", actor=Actor(platform="local")) is None


def test_backend_error_blocks_gateway_actor_without_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _sandbox_on(tmp_path)

    from agent.governance import Actor
    from agent.sandbox import sandbox_backend_error

    reason = sandbox_backend_error(
        "local", actor=Actor(platform="slack", user_id="U1")
    )
    assert reason is not None
    assert "not 'docker'" in reason


def test_backend_error_allows_gateway_actor_on_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _sandbox_on(tmp_path)

    from agent.governance import Actor
    from agent.sandbox import sandbox_backend_error

    assert (
        sandbox_backend_error("docker", actor=Actor(platform="slack", user_id="U1"))
        is None
    )


def test_build_overrides_carries_mounts(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    shared = tmp_path / "shared"
    shared.mkdir()
    _write_config(
        tmp_path,
        f"""
governance:
  enabled: true
  default_file_policy: deny
  terminal:
    sandbox:
      enabled: true
  users:
    "slack:U1":
      roles: [admin]
  role_hierarchy: [viewer, admin]
  folder_policies:
    - path: '{shared}'
      read_roles: [admin]
""",
    )

    from agent.governance import Actor
    from agent.sandbox import build_sandbox_overrides

    overrides = build_sandbox_overrides(actor=Actor(platform="slack", user_id="U1"))
    assert overrides["cwd"] == "/workspace"
    assert overrides["env_type"] == "docker"
    assert any(str(shared) in spec for spec in overrides["docker_volumes"])


def test_windows_policy_path_resolves_to_wsl_mount(monkeypatch):
    monkeypatch.setattr("agent.governance.os.name", "posix")

    from agent.governance import resolve_governed_path

    resolved = resolve_governed_path(r"C:\Users\andre\Documents\Finance")
    assert str(resolved) == "/mnt/c/Users/andre/Documents/Finance"


def test_terminal_tool_fails_closed_without_docker(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _sandbox_on(tmp_path)
    monkeypatch.setenv("MAIA_USER_ID", "U1")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "slack")
    monkeypatch.setenv("TERMINAL_ENV", "local")

    import json as _json
    from tools.terminal_tool import terminal_tool

    result = _json.loads(terminal_tool(command="echo hi"))
    assert "Per-user sandbox is enabled" in (result.get("error") or "")

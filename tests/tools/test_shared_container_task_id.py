"""
Regression tests for the shared-container task_id mapping.

The top-level agent and all delegate_task subagents share a single
terminal sandbox keyed by ``"default"``.  ``_resolve_container_task_id``
is the sole gatekeeper for which tool-call task_ids go to the shared
container vs. get their own isolated sandbox.  RL / benchmark
environments opt in to isolation by calling
``register_task_env_overrides(task_id, {...})`` before the agent loop;
every other task_id collapses back to ``"default"``.

If you change the collapse logic, update both the helper and these
tests -- see `hermes-agent-dev` skill, "Why do subagents get their own
containers?" section, and the Container lifecycle paragraph under
Docker Backend in ``website/docs/user-guide/configuration.md``.
"""

import pytest

from tools import terminal_tool


@pytest.fixture(autouse=True)
def _clean_overrides():
    """Ensure no stray overrides from other tests leak in."""
    before = dict(terminal_tool._task_env_overrides)
    parents_before = dict(terminal_tool._task_env_parents)
    active_before = dict(terminal_tool._active_environments)
    signatures_before = dict(terminal_tool._active_environment_override_signatures)
    terminal_tool._task_env_overrides.clear()
    terminal_tool._task_env_parents.clear()
    terminal_tool._active_environments.clear()
    terminal_tool._active_environment_override_signatures.clear()
    yield
    terminal_tool._task_env_overrides.clear()
    terminal_tool._task_env_overrides.update(before)
    terminal_tool._task_env_parents.clear()
    terminal_tool._task_env_parents.update(parents_before)
    terminal_tool._active_environments.clear()
    terminal_tool._active_environments.update(active_before)
    terminal_tool._active_environment_override_signatures.clear()
    terminal_tool._active_environment_override_signatures.update(signatures_before)


def test_none_task_id_maps_to_default():
    assert terminal_tool._resolve_container_task_id(None) == "default"


def test_empty_task_id_maps_to_default():
    assert terminal_tool._resolve_container_task_id("") == "default"


def test_literal_default_stays_default():
    assert terminal_tool._resolve_container_task_id("default") == "default"


def test_subagent_task_id_collapses_to_default():
    # delegate_task constructs IDs like "subagent-<N>-<uuid_hex>"; these
    # should share the parent's container, not spin up their own.
    assert terminal_tool._resolve_container_task_id("subagent-0-deadbeef") == "default"
    assert terminal_tool._resolve_container_task_id("subagent-42-cafef00d") == "default"


def test_arbitrary_session_id_collapses_to_default():
    # Session UUIDs or anything else without an override still collapse.
    assert terminal_tool._resolve_container_task_id("sess-123e4567-e89b-12d3") == "default"


def test_rl_task_with_override_keeps_its_own_id():
    # RL / benchmark pattern: register a per-task image, then the task_id
    # must survive ``_resolve_container_task_id`` so the rollout lands in
    # its own sandbox.
    terminal_tool.register_task_env_overrides(
        "tb2-task-fix-git", {"docker_image": "tb2:fix-git", "cwd": "/app"}
    )
    try:
        assert (
            terminal_tool._resolve_container_task_id("tb2-task-fix-git")
            == "tb2-task-fix-git"
        )
    finally:
        terminal_tool.clear_task_env_overrides("tb2-task-fix-git")


def test_cleared_override_collapses_again():
    terminal_tool.register_task_env_overrides("tb2-x", {"docker_image": "x:y"})
    assert terminal_tool._resolve_container_task_id("tb2-x") == "tb2-x"
    terminal_tool.clear_task_env_overrides("tb2-x")
    assert terminal_tool._resolve_container_task_id("tb2-x") == "default"


def test_subagent_inherits_governed_parent_override():
    terminal_tool.register_task_env_overrides(
        "gateway-session", {"env_type": "docker", "docker_volumes": []}
    )
    assert terminal_tool.register_task_env_parent(
        "subagent-0-secure", "gateway-session"
    ) is True
    assert (
        terminal_tool._resolve_container_task_id("subagent-0-secure")
        == "gateway-session"
    )
    terminal_tool.clear_task_env_parent("subagent-0-secure")
    assert terminal_tool._resolve_container_task_id("subagent-0-secure") == "default"


def test_get_active_env_reads_shared_container_from_subagent_id():
    """``get_active_env`` must see the shared ``"default"`` sandbox when
    called with a subagent's task_id, so the agent loop's turn-budget
    enforcement reads the real env (not None) during delegation."""
    sentinel = object()
    terminal_tool._active_environments["default"] = sentinel
    try:
        assert terminal_tool.get_active_env("subagent-7-cafe") is sentinel
        assert terminal_tool.get_active_env(None) is sentinel
        assert terminal_tool.get_active_env("default") is sentinel
    finally:
        terminal_tool._active_environments.pop("default", None)


def test_get_active_env_honours_rl_override():
    rl_env = object()
    default_env = object()
    terminal_tool._active_environments["default"] = default_env
    terminal_tool.register_task_env_overrides("rl-42", {"docker_image": "x"})
    terminal_tool._active_environments["rl-42"] = rl_env
    terminal_tool._active_environment_override_signatures["rl-42"] = (
        terminal_tool._environment_override_signature({"docker_image": "x"})
    )
    try:
        # With an override registered, lookup returns the task's own env,
        # not the shared "default" one.
        assert terminal_tool.get_active_env("rl-42") is rl_env
    finally:
        terminal_tool.clear_task_env_overrides("rl-42")
        terminal_tool._active_environments.pop("default", None)
        terminal_tool._active_environments.pop("rl-42", None)


class _GovernedEnv:
    def __init__(self):
        self.discarded = 0

    def discard(self):
        self.discarded += 1


def _install_governed_env(task_id, overrides):
    env = _GovernedEnv()
    terminal_tool._active_environments[task_id] = env
    terminal_tool._active_environment_override_signatures[task_id] = (
        terminal_tool._environment_override_signature(overrides)
    )
    return env


def test_same_governance_mounts_reuse_active_environment():
    task_id = "gateway-session-stable"
    overrides = {
        "env_type": "docker",
        "governance_sandbox": True,
        "docker_volumes": ["/company:/company:ro"],
    }
    terminal_tool.register_task_env_overrides(task_id, overrides)
    env = _install_governed_env(task_id, overrides)

    terminal_tool.register_task_env_overrides(task_id, dict(overrides))

    assert terminal_tool._active_environments[task_id] is env
    assert env.discarded == 0


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (["/company:/company:ro"], ["/company:/company:rw"]),
        (["/company:/company:rw"], ["/company:/company:ro"]),
        (["/company:/company:ro"], []),
        ([], ["/company:/company:ro"]),
    ],
)
def test_governance_mount_change_discards_cached_environment(before, after):
    task_id = "gateway-session-changing"
    old_overrides = {
        "env_type": "docker",
        "governance_sandbox": True,
        "docker_volumes": before,
    }
    terminal_tool.register_task_env_overrides(task_id, old_overrides)
    env = _install_governed_env(task_id, old_overrides)

    terminal_tool.register_task_env_overrides(
        task_id,
        {**old_overrides, "docker_volumes": after},
    )

    assert task_id not in terminal_tool._active_environments
    assert task_id not in terminal_tool._active_environment_override_signatures
    assert env.discarded == 1


def test_governed_raw_execution_rejects_unsigned_file_tool_environment():
    task_id = "gateway-session-file-tool-first"
    overrides = {
        "env_type": "docker",
        "governance_sandbox": True,
        "docker_volumes": ["/company:/company:ro"],
    }
    terminal_tool.register_task_env_overrides(task_id, overrides)
    file_tool_env = _GovernedEnv()
    terminal_tool._active_environments[task_id] = file_tool_env

    retired = terminal_tool._retire_stale_environment_for_overrides(
        task_id,
        overrides,
    )

    assert retired is True
    assert task_id not in terminal_tool._active_environments
    assert file_tool_env.discarded == 1

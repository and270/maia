"""Personal memories and skills are isolated by gateway identity."""

import json

from agent.user_scope import personal_memory_dir, personal_skills_dir
from gateway.session_context import clear_session_vars, set_session_vars


SKILL_ONE = """---
name: alice-private-procedure
description: A private procedure created by Alice.
---

# Alice private procedure

Use only for Alice's personal workflow.
"""

SKILL_TWO = """---
name: bob-private-procedure
description: A private procedure created by Bob.
---

# Bob private procedure

Use only for Bob's personal workflow.
"""


def _set_home(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))


def test_memory_store_paths_are_isolated_and_opaque(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)
    from tools.memory_tool import MemoryStore

    alice = MemoryStore(platform="discord", user_id="alice/raw/id")
    bob = MemoryStore(platform="discord", user_id="bob/raw/id")
    alice.load_from_disk()
    bob.load_from_disk()

    assert alice.memory_dir != bob.memory_dir
    assert "alice/raw/id" not in str(alice.memory_dir)
    assert alice.add("memory", "Alice-only QA preference.")["success"] is True

    bob.load_from_disk()
    assert bob.memory_entries == []
    assert (alice.memory_dir / "MEMORY.md").exists()
    assert not (bob.memory_dir / "MEMORY.md").exists()


def test_personal_skill_creation_listing_and_commands_do_not_cross_users(
    monkeypatch, tmp_path
):
    _set_home(monkeypatch, tmp_path)
    from agent import skill_commands
    from tools import skill_manager_tool, skills_tool

    profile_skills = tmp_path / "skills"
    monkeypatch.setattr(skill_manager_tool, "SKILLS_DIR", profile_skills)
    monkeypatch.setattr(skills_tool, "SKILLS_DIR", profile_skills)

    alice_tokens = set_session_vars(platform="discord", user_id="alice")
    try:
        alice_result = json.loads(
            skill_manager_tool.skill_manage(
                action="create",
                name="alice-private-procedure",
                content=SKILL_ONE,
            )
        )
        assert alice_result["success"] is True
        alice_dir = personal_skills_dir()
        assert (alice_dir / "alice-private-procedure" / "SKILL.md").exists()
        alice_skill_path = alice_dir / "alice-private-procedure"
        alice_commands = skill_commands.scan_skill_commands()
        assert "/alice-private-procedure" in alice_commands

        bob_tokens = set_session_vars(platform="discord", user_id="bob")
        try:
            bob_list = json.loads(skills_tool.skills_list())
            bob_names = {skill["name"] for skill in bob_list.get("skills", [])}
            assert "alice-private-procedure" not in bob_names

            bob_commands = skill_commands.get_skill_commands()
            assert "/alice-private-procedure" not in bob_commands
            escaped_view = json.loads(skills_tool.skill_view(str(alice_skill_path)))
            assert escaped_view["success"] is False
            assert "outside your visible skill scope" in escaped_view["error"]

            bob_result = json.loads(
                skill_manager_tool.skill_manage(
                    action="create",
                    name="bob-private-procedure",
                    content=SKILL_TWO,
                )
            )
            assert bob_result["success"] is True
            assert (personal_skills_dir() / "bob-private-procedure" / "SKILL.md").exists()
        finally:
            clear_session_vars(bob_tokens)

        set_session_vars(platform="discord", user_id="alice")
        alice_list = json.loads(skills_tool.skills_list())
        alice_names = {skill["name"] for skill in alice_list.get("skills", [])}
        assert "alice-private-procedure" in alice_names
        assert "bob-private-procedure" not in alice_names
    finally:
        clear_session_vars(alice_tokens)


def test_local_sessions_keep_profile_wide_legacy_paths(monkeypatch, tmp_path):
    _set_home(monkeypatch, tmp_path)

    assert personal_memory_dir(platform="cli", user_id="local-user") == tmp_path / "memories"
    assert personal_skills_dir(platform="local", user_id="local-user") == tmp_path / "skills"

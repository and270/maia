"""Regression: skill_manage on the default user scope must NOT mutate a
corporate/team skill in place — that bypasses the approval pipeline.

Reproduces the auditor's exploit: a ``scope="user"`` patch/edit/delete of a
name that collides with a shared skill previously rewrote the shared copy
directly (success=True, no approval staged).
"""

import json

import pytest


def _enable_knowledge_config(home):
    (home).mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        """
governance:
  enabled: true
knowledge:
  enabled: true
""",
        encoding="utf-8",
    )


def _make_corporate_skill(home, name: str, body: str) -> "object":
    from pathlib import Path

    skill_dir = home / "corporate" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    md = skill_dir / "SKILL.md"
    md.write_text(
        f"---\nname: {name}\ndescription: corporate policy\n---\n{body}\n",
        encoding="utf-8",
    )
    return md


@pytest.mark.parametrize("action_kwargs", [
    {"action": "patch", "old_string": "require MFA", "new_string": "MFA optional"},
    {"action": "edit", "content": "---\nname: sec\ndescription: x\n---\nHacked\n"},
    {"action": "delete"},
])
def test_user_scope_cannot_mutate_corporate_skill(tmp_path, monkeypatch, action_kwargs):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _enable_knowledge_config(tmp_path)
    md = _make_corporate_skill(tmp_path, "sec", "ALWAYS require MFA")
    original = md.read_text(encoding="utf-8")

    from tools.skill_manager_tool import skill_manage

    # Default scope is "user" — must be refused for a shared skill.
    result = json.loads(skill_manage(name="sec", **action_kwargs))

    assert result.get("success") is False, result
    assert "shared" in json.dumps(result).lower()
    # The corporate skill on disk is untouched.
    assert md.exists()
    assert md.read_text(encoding="utf-8") == original


def test_guard_does_not_flag_a_user_skill(tmp_path, monkeypatch):
    """The shared-skill guard must return None (allow) for a user-scoped skill,
    so legitimate user-scope edits are not blocked."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _enable_knowledge_config(tmp_path)

    # A skill under the user skills dir (not corporate/teams).
    from agent.skill_utils import get_skills_dir

    user_skill = get_skills_dir() / "mine"
    user_skill.mkdir(parents=True, exist_ok=True)
    (user_skill / "SKILL.md").write_text(
        "---\nname: mine\ndescription: personal\n---\nBody\n", encoding="utf-8"
    )

    from tools.skill_manager_tool import _shared_skill_scope_error

    assert _shared_skill_scope_error("mine") is None

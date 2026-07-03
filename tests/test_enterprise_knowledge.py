import json


def _write_config(home, content: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(content, encoding="utf-8")


def _skill_text(name: str, description: str) -> str:
    return f"""---
name: {name}
description: {description}
---

# {name}

Use the approved operating procedure.
"""


def test_corporate_and_team_knowledge_are_injected_above_user_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
knowledge:
  enabled: true
governance:
  enabled: true
  role_hierarchy: [viewer, manager, admin]
  users:
    "slack:U_MANAGER":
      roles: [manager]
      teams: [finance]
""",
    )

    from agent.enterprise_knowledge import (
        build_enterprise_knowledge_prompt,
        corporate_memory_path,
        corporate_skills_dir,
        team_memory_path,
        team_skills_dir,
    )
    from agent.governance import Actor

    corporate_memory_path().parent.mkdir(parents=True, exist_ok=True)
    corporate_memory_path().write_text("Corporate tone is concise.", encoding="utf-8")
    team_memory_path("finance").parent.mkdir(parents=True, exist_ok=True)
    team_memory_path("finance").write_text("Finance reports use approved templates.", encoding="utf-8")
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "MEMORY.md").write_text("User-only memory", encoding="utf-8")

    corp_skill = corporate_skills_dir() / "security-review"
    corp_skill.mkdir(parents=True)
    (corp_skill / "SKILL.md").write_text(
        _skill_text("security-review", "Tenant-wide security review."),
        encoding="utf-8",
    )
    team_skill = team_skills_dir("finance") / "finance-close"
    team_skill.mkdir(parents=True)
    (team_skill / "SKILL.md").write_text(
        _skill_text("finance-close", "Finance close checklist."),
        encoding="utf-8",
    )

    prompt = build_enterprise_knowledge_prompt(
        Actor(platform="slack", user_id="U_MANAGER")
    )

    assert "MAIA HERMES SHARED KNOWLEDGE" in prompt
    assert "Corporate tone is concise." in prompt
    assert "Finance reports use approved templates." in prompt
    assert "security-review" in prompt
    assert "finance-close" in prompt
    assert "User-only memory" not in prompt


def test_corporate_memory_write_requires_human_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
knowledge:
  enabled: true
governance:
  enabled: true
  role_hierarchy: [viewer, manager, admin]
  users:
    "local:approver":
      roles: [admin]
""",
    )

    from agent.enterprise_knowledge import corporate_memory_path, decide_knowledge_approval
    from agent.governance import Actor
    from tools.memory_tool import memory_tool

    staged = json.loads(
        memory_tool(
            action="add",
            target="memory",
            content="Corporate escalation uses the on-call rotation.",
            scope="corporate",
            approval_note="Promote validated incident policy.",
        )
    )

    assert staged["pending_approval"] is True
    assert not corporate_memory_path().exists()

    decided = decide_knowledge_approval(
        staged["approval_id"],
        approve=True,
        actor=Actor(platform="local", user_id="approver"),
    )

    assert decided["success"] is True
    assert "on-call rotation" in corporate_memory_path().read_text(encoding="utf-8")


def test_team_skill_write_requires_approval_and_becomes_viewable(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIA_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("MAIA_USER_ID", "manager")
    monkeypatch.setenv("MAIA_USER_PLATFORM", "local")
    _write_config(
        tmp_path,
        """
knowledge:
  enabled: true
governance:
  enabled: true
  role_hierarchy: [viewer, manager, admin]
  users:
    "local:manager":
      roles: [manager]
      teams: [finance]
""",
    )

    from agent.enterprise_knowledge import decide_knowledge_approval, team_skills_dir
    from agent.governance import Actor
    from tools.skill_manager_tool import skill_manage
    from tools.skills_tool import skill_view

    staged = json.loads(
        skill_manage(
            action="create",
            name="finance-close",
            content=_skill_text("finance-close", "Finance close checklist."),
            scope="team",
            team="finance",
            approval_note="Finance team wants a shared close procedure.",
        )
    )

    assert staged["pending_approval"] is True
    assert not (team_skills_dir("finance") / "finance-close" / "SKILL.md").exists()

    decided = decide_knowledge_approval(
        staged["approval_id"],
        approve=True,
        actor=Actor(platform="local", user_id="manager"),
    )

    assert decided["success"] is True
    assert (team_skills_dir("finance") / "finance-close" / "SKILL.md").exists()

    viewed = json.loads(skill_view("finance-close"))
    assert viewed["success"] is True
    assert "Finance close checklist" in viewed["content"]

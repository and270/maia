import json
from copy import deepcopy

import pytest

from agent.governance import Actor
from agent.governance_admin import (
    GovernanceAdminError,
    execute_governance_admin_action,
)
from gateway.session_context import clear_session_vars, set_session_vars


def _config(tmp_path):
    team_root = tmp_path / "finance"
    team_root.mkdir()
    return {
        "unrelated": {"preserved": True},
        "dashboard": {"auth": {"admin_roles": ["admin"]}},
        "governance": {
            "enabled": True,
            "role_hierarchy": ["viewer", "operator", "manager", "admin"],
            "teams": {"Finance": {}},
            "team_file_roots": {
                "Finance": {"path": str(team_root), "manager_roles": ["manager"]}
            },
            "users": {
                "discord:100": {"name": "Admin", "roles": ["admin"]},
                "discord:200": {
                    "name": "Manager",
                    "roles": ["manager"],
                    "teams": ["Finance"],
                },
                "discord:300": {"name": "Viewer", "roles": ["viewer"]},
            },
            "folder_policies": [],
        },
    }


@pytest.fixture
def service_state(tmp_path, monkeypatch):
    import agent.governance_admin as admin

    state = {"config": _config(tmp_path), "admission": [], "audit": []}

    monkeypatch.setattr(admin, "_load_full_config", lambda: deepcopy(state["config"]))

    def save(config):
        state["config"] = deepcopy(config)

    monkeypatch.setattr(admin, "_save_full_config", save)
    monkeypatch.setattr(
        admin,
        "_set_gateway_admission",
        lambda platform, user_id, admitted: state["admission"].append(
            (platform, user_id, admitted)
        ),
    )
    monkeypatch.setattr(
        admin,
        "_audit",
        lambda event, **kwargs: state["audit"].append((event, kwargs)),
    )
    return state


def test_admin_can_admit_governed_user_with_direct_file_access(service_state, tmp_path):
    allowed = tmp_path / "finance" / "reports"
    result = execute_governance_admin_action(
        "upsert_user",
        {
            "actor_key": "discord:400",
            "name": "Analyst",
            "roles": ["operator"],
            "teams": ["Finance"],
            "gateway_admission": True,
            "file_access": [
                {"path": str(allowed), "recursive": True, "read": True}
            ],
        },
        actor=Actor(platform="discord", user_id="100"),
    )

    assert result["success"] is True
    assert service_state["admission"] == [("discord", "400", True)]
    saved = service_state["config"]
    assert saved["unrelated"] == {"preserved": True}
    assert saved["governance"]["users"]["discord:400"]["roles"] == ["operator"]
    assert saved["governance"]["folder_policies"][0]["read_users"] == [
        "discord:400"
    ]
    assert service_state["audit"][-1][1]["outcome"] == "success"


def test_non_admin_cannot_manage_people_and_denial_is_audited(service_state):
    with pytest.raises(GovernanceAdminError) as exc:
        execute_governance_admin_action(
            "upsert_user",
            {"actor_key": "discord:400", "roles": ["viewer"]},
            actor=Actor(platform="discord", user_id="300"),
        )

    assert exc.value.code == "admin_required"
    assert "discord:400" not in service_state["config"]["governance"]["users"]
    assert service_state["audit"][-1][1]["outcome"] == "denied"


def test_manager_can_only_set_team_policy_under_delegated_root(service_state, tmp_path):
    inside = tmp_path / "finance" / "quarterly"
    result = execute_governance_admin_action(
        "set_file_policy",
        {
            "path": str(inside),
            "recursive": True,
            "policy": {"read_teams": ["Finance"]},
        },
        actor=Actor(platform="discord", user_id="200"),
    )
    assert result["success"] is True

    with pytest.raises(GovernanceAdminError) as exc:
        execute_governance_admin_action(
            "set_file_policy",
            {
                "path": str(tmp_path / "legal"),
                "policy": {"read_teams": ["Finance"]},
            },
            actor=Actor(platform="discord", user_id="200"),
        )
    assert exc.value.code == "outside_delegated_root"


def test_manager_cannot_create_role_wide_grant(service_state, tmp_path):
    with pytest.raises(GovernanceAdminError) as exc:
        execute_governance_admin_action(
            "set_file_policy",
            {
                "path": str(tmp_path / "finance" / "all"),
                "policy": {"read_roles": ["viewer"]},
            },
            actor=Actor(platform="discord", user_id="200"),
        )
    assert exc.value.code == "role_grant_forbidden"


def test_last_admin_cannot_remove_own_admin_role(service_state):
    with pytest.raises(GovernanceAdminError) as exc:
        execute_governance_admin_action(
            "upsert_user",
            {"actor_key": "discord:100", "roles": ["manager"]},
            actor=Actor(platform="discord", user_id="100"),
        )
    assert exc.value.code == "last_admin"


def test_team_update_without_members_preserves_existing_members(service_state):
    result = execute_governance_admin_action(
        "update_team",
        {
            "team": "Finance",
            "file_access": [
                {"path": "finance/shared", "recursive": True, "read": True}
            ],
        },
        actor=Actor(platform="discord", user_id="100"),
    )

    assert result["success"] is True
    assert "discord:200" in result["team"]["members"]


def test_admin_policy_rejects_unknown_governed_user(service_state, tmp_path):
    with pytest.raises(GovernanceAdminError, match="Unknown governed users"):
        execute_governance_admin_action(
            "set_file_policy",
            {
                "path": str(tmp_path / "finance" / "restricted"),
                "policy": {"read_users": ["discord:999"]},
            },
            actor=Actor(platform="discord", user_id="100"),
        )


def test_admin_policy_accepts_named_manager_without_second_path_grant(
    service_state, tmp_path
):
    target = tmp_path / "finance" / "reviewed"
    result = execute_governance_admin_action(
        "set_file_policy",
        {
            "path": str(target),
            "policy": {
                "read_users": ["discord:300"],
                "write_users": ["discord:300"],
                "write_approval_users": ["discord:200"],
            },
        },
        actor=Actor(platform="discord", user_id="100"),
    )

    assert result["success"] is True
    saved = service_state["config"]["governance"]["folder_policies"][0]
    assert saved["write_approval_users"] == ["discord:200"]
    assert "discord:200" not in saved.get("write_users", [])


def test_manager_can_choose_global_admin_as_reviewer_inside_delegated_root(
    service_state, tmp_path
):
    target = tmp_path / "finance" / "manager-reviewed"
    result = execute_governance_admin_action(
        "set_file_policy",
        {
            "path": str(target),
            "policy": {
                "read_users": ["discord:200"],
                "write_users": ["discord:200"],
                "write_approval_users": ["discord:100"],
            },
        },
        actor=Actor(platform="discord", user_id="200"),
    )

    assert result["success"] is True
    saved = service_state["config"]["governance"]["folder_policies"][0]
    assert saved["write_approval_users"] == ["discord:100"]


def test_tool_uses_task_local_gateway_identity_not_environment(service_state, monkeypatch):
    import tools.maia_admin_tool as tool

    monkeypatch.setenv("HERMES_SESSION_PLATFORM", "discord")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "100")
    monkeypatch.setenv("MAIA_USER_ID", "discord:999")
    monkeypatch.setattr(
        tool,
        "execute_governance_admin_action",
        lambda action, payload, actor: {
            "success": True,
            "actor": f"{actor.platform}:{actor.user_id}",
        },
    )
    tokens = set_session_vars(platform="discord", user_id="300", user_name="Viewer")
    try:
        result = json.loads(tool.maia_admin({"action": "inspect"}))
    finally:
        clear_session_vars(tokens)

    assert result["actor"] == "discord:300"


def test_tool_schema_exposes_no_requester_or_secret_fields():
    from tools.maia_admin_tool import _FILE_GRANT_SCHEMA, _PAYLOAD_KEYS

    assert "requester" not in _PAYLOAD_KEYS
    assert "actor" not in _PAYLOAD_KEYS
    assert "api_key" not in _PAYLOAD_KEYS
    assert "write_requires_approval" in _FILE_GRANT_SCHEMA["properties"]
    assert "write_approval_roles" in _FILE_GRANT_SCHEMA["properties"]
    assert "write_approval_users" in _FILE_GRANT_SCHEMA["properties"]

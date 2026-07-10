"""Gateway admission must be intersected with explicit Governance access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.governance import Actor, has_explicit_user_access
from gateway.config import Platform
from gateway.session import SessionSource
from gateway.platforms.base import MessageEvent


def _runner_with_governance(monkeypatch, governance):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.pairing_store = SimpleNamespace(is_approved=lambda *_args: False)

    def governed(source):
        return has_explicit_user_access(
            Actor(
                platform=source.platform.value,
                user_id=str(source.user_id or ""),
                user_name=str(source.user_name or ""),
            ),
            config=governance,
        )

    monkeypatch.setattr(
        GatewayRunner,
        "_has_governance_gateway_access",
        staticmethod(governed),
    )
    return runner


@pytest.mark.parametrize(
    ("platform", "env_key", "approved_id", "pending_id"),
    [
        (Platform.DISCORD, "DISCORD_ALLOWED_USERS", "111111111111111111", "222222222222222222"),
        (Platform.SLACK, "SLACK_ALLOWED_USERS", "U-APPROVED", "U-PENDING"),
        (Platform.MATRIX, "MATRIX_ALLOWED_USERS", "@approved:example.org", "@pending:example.org"),
    ],
)
def test_allowlist_never_bypasses_governance(
    monkeypatch, platform, env_key, approved_id, pending_id
):
    monkeypatch.setenv(env_key, f"{approved_id},{pending_id}")
    governance = {
        "default_role": "viewer",
        "users": {
            f"{platform.value}:{approved_id}": {"roles": ["operator"]},
        },
    }
    runner = _runner_with_governance(monkeypatch, governance)

    approved = SessionSource(platform=platform, chat_id="c1", user_id=approved_id)
    pending = SessionSource(platform=platform, chat_id="c1", user_id=pending_id)

    assert runner._is_user_authorized(approved) is True
    assert runner._is_user_authorized(pending) is False


def test_pairing_and_allow_all_still_require_governance(monkeypatch):
    from gateway.run import GatewayRunner

    governance = {"default_role": "viewer", "users": {}}
    runner = _runner_with_governance(monkeypatch, governance)
    runner.pairing_store = SimpleNamespace(is_approved=lambda *_args: True)
    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="c1",
        user_id="333333333333333333",
    )

    assert runner._is_user_authorized(source) is False

    runner.pairing_store = SimpleNamespace(is_approved=lambda *_args: False)
    monkeypatch.setenv("DISCORD_ALLOW_ALL_USERS", "true")
    assert runner._is_user_authorized(source) is False

    # The test fixture is deliberately overridden above; keep this assertion
    # here as a guard that the production method remains the one under test.
    assert GatewayRunner._is_user_authorized is not None


def test_default_role_does_not_create_gateway_membership():
    config = {"default_role": "viewer", "users": {}}
    actor = Actor(platform="discord", user_id="444444444444444444")

    assert has_explicit_user_access(actor, config=config) is False


def test_display_name_collision_does_not_create_gateway_membership():
    config = {
        "users": {
            "discord:Shared Display Name": {"roles": ["admin"]},
        }
    }
    actor = Actor(
        platform="discord",
        user_id="666666666666666666",
        user_name="Shared Display Name",
    )

    assert has_explicit_user_access(actor, config=config) is False


def test_system_integrations_bypass_human_governance_gate(monkeypatch):
    runner = _runner_with_governance(monkeypatch, {"users": {}})
    source = SessionSource(
        platform=Platform.HOMEASSISTANT,
        chat_id="automation",
        user_id="system",
    )

    assert runner._is_user_authorized(source) is True


@pytest.mark.asyncio
async def test_pending_governance_user_gets_no_pairing_code(monkeypatch):
    from gateway.run import GatewayRunner

    user_id = "555555555555555555"
    monkeypatch.setenv("DISCORD_ALLOWED_USERS", user_id)
    runner = _runner_with_governance(monkeypatch, {"users": {}})
    adapter = SimpleNamespace(send=AsyncMock())
    runner.adapters = {Platform.DISCORD: adapter}
    runner.pairing_store = MagicMock()
    runner.pairing_store.is_approved.return_value = False
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_args, **_kwargs: [])

    source = SessionSource(
        platform=Platform.DISCORD,
        chat_id="dm-1",
        chat_type="dm",
        user_id=user_id,
        user_name="Pending User",
    )
    event = MessageEvent(text="hello", source=source, message_id="m1")

    assert await runner._handle_message(event) is None
    adapter.send.assert_awaited_once()
    assert "pending Governance approval" in adapter.send.await_args.args[1]
    runner.pairing_store.generate_code.assert_not_called()

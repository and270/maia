from unittest.mock import patch

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _event(text: str, user_id: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.SLACK,
            chat_id="C123",
            chat_type="channel",
            user_id=user_id,
            user_name=user_id,
        ),
    )


def _runner():
    from gateway.run import GatewayRunner

    return object.__new__(GatewayRunner)


def _corporate_config():
    return {
        "dashboard": {
            "auth": {
                "enabled": True,
                "admin_roles": ["admin"],
            },
        },
        "governance": {
            "enabled": True,
            "role_hierarchy": ["viewer", "operator", "manager", "admin"],
            "users": {
                "slack:U_OPERATOR": {"roles": ["operator"]},
                "slack:U_ADMIN": {"roles": ["admin"]},
            },
        },
    }


def test_gateway_global_model_change_requires_admin_role():
    runner = _runner()
    with patch("gateway.run._load_gateway_config", return_value=_corporate_config()):
        denied = runner._gateway_admin_denial_for_command(
            "model",
            _event("/model gpt-5 --global", "U_OPERATOR"),
        )
        assert denied is not None
        assert "restricted to dashboard admin roles" in denied

        allowed = runner._gateway_admin_denial_for_command(
            "model",
            _event("/model gpt-5 --global", "U_ADMIN"),
        )
        assert allowed is None


def test_gateway_session_model_change_does_not_require_admin_role():
    runner = _runner()
    with patch("gateway.run._load_gateway_config", return_value=_corporate_config()):
        assert (
            runner._gateway_admin_denial_for_command(
                "model",
                _event("/model gpt-5", "U_OPERATOR"),
            )
            is None
        )


def test_gateway_home_channel_requires_admin_in_corporate_mode():
    runner = _runner()
    with patch("gateway.run._load_gateway_config", return_value=_corporate_config()):
        denied = runner._gateway_admin_denial_for_command(
            "sethome",
            _event("/sethome", "U_OPERATOR"),
        )
        assert denied is not None
        assert "change the gateway home channel" in denied


def test_gateway_admin_guard_is_inactive_for_personal_mode():
    runner = _runner()
    with patch("gateway.run._load_gateway_config", return_value={}):
        assert (
            runner._gateway_admin_denial_for_command(
                "sethome",
                _event("/sethome", "U_OPERATOR"),
            )
            is None
        )

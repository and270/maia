"""Tests for staged file-change approval cards in the gateway.

Covers the Slack Block Kit card + governance-gated click handler, the
GatewayRunner routing (button card vs text fallback, approver mentions),
and the platform mention formatting helpers.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the repo root is importable
# ---------------------------------------------------------------------------
_repo = str(Path(__file__).resolve().parents[2])
if _repo not in sys.path:
    sys.path.insert(0, _repo)


# ---------------------------------------------------------------------------
# Minimal Slack SDK mock so SlackAdapter can be imported
# ---------------------------------------------------------------------------
def _ensure_slack_mock():
    if "slack_bolt" in sys.modules:
        return
    slack_bolt = MagicMock()
    slack_bolt.async_app.AsyncApp = MagicMock
    sys.modules["slack_bolt"] = slack_bolt
    sys.modules["slack_bolt.async_app"] = slack_bolt.async_app
    handler_mod = MagicMock()
    handler_mod.AsyncSocketModeHandler = MagicMock
    sys.modules["slack_bolt.adapter"] = MagicMock()
    sys.modules["slack_bolt.adapter.socket_mode"] = MagicMock()
    sys.modules["slack_bolt.adapter.socket_mode.async_handler"] = handler_mod
    sdk_mod = MagicMock()
    sdk_mod.web = MagicMock()
    sdk_mod.web.async_client = MagicMock()
    sdk_mod.web.async_client.AsyncWebClient = MagicMock
    sys.modules["slack_sdk"] = sdk_mod
    sys.modules["slack_sdk.web"] = sdk_mod.web
    sys.modules["slack_sdk.web.async_client"] = sdk_mod.web.async_client


_ensure_slack_mock()

from gateway.platforms.base import SendResult
from gateway.platforms.base import MessageEvent
from gateway.platforms.slack import SlackAdapter
from gateway.config import Platform, PlatformConfig
from gateway.session import SessionSource


def _make_slack_adapter():
    config = PlatformConfig(enabled=True, token="xoxb-test-token")
    adapter = SlackAdapter(config)
    adapter._app = MagicMock()
    adapter._bot_user_id = "U_BOT"
    adapter._team_clients = {"T1": AsyncMock()}
    adapter._team_bot_user_ids = {"T1": "U_BOT"}
    adapter._channel_team = {"C1": "T1"}
    return adapter


# ===========================================================================
# Slack send_file_approval
# ===========================================================================

class TestSlackFileApprovalCard:
    @pytest.mark.asyncio
    async def test_sends_card_with_buttons_and_mentions(self):
        adapter = _make_slack_adapter()
        mock_client = adapter._team_clients["T1"]
        mock_client.chat_postMessage = AsyncMock(return_value={"ts": "1234.5678"})

        result = await adapter.send_file_approval(
            chat_id="C1",
            approval_id="abc123",
            path="/srv/finance/report.md",
            requested_by="slack:U_WRITER",
            diff="-old line\n+new line",
            mention_text="<@U_MANAGER>",
        )

        assert result.success is True
        kwargs = mock_client.chat_postMessage.call_args[1]
        blocks = kwargs["blocks"]

        header_text = blocks[0]["text"]["text"]
        assert "<@U_MANAGER>" in header_text
        assert "/srv/finance/report.md" in header_text
        assert "slack:U_WRITER" in header_text
        assert "conditional write access" in header_text
        assert "permissions will not change" in header_text
        assert "`approve` / `aprovo`" in header_text

        diff_text = blocks[1]["text"]["text"]
        assert "+new line" in diff_text

        actions = blocks[-1]
        assert actions["type"] == "actions"
        action_ids = [e["action_id"] for e in actions["elements"]]
        assert action_ids == ["hermes_file_approve", "hermes_file_deny"]
        for element in actions["elements"]:
            assert element["value"] == "abc123"

    @pytest.mark.asyncio
    async def test_sends_in_thread(self):
        adapter = _make_slack_adapter()
        mock_client = adapter._team_clients["T1"]
        mock_client.chat_postMessage = AsyncMock(return_value={"ts": "1.2"})

        await adapter.send_file_approval(
            chat_id="C1",
            approval_id="abc",
            path="x.md",
            metadata={"thread_id": "9999.0000"},
        )

        kwargs = mock_client.chat_postMessage.call_args[1]
        assert kwargs.get("thread_ts") == "9999.0000"

    @pytest.mark.asyncio
    async def test_not_connected(self):
        adapter = _make_slack_adapter()
        adapter._app = None
        result = await adapter.send_file_approval(
            chat_id="C1", approval_id="a", path="x.md"
        )
        assert result.success is False

    def test_format_user_mention(self):
        adapter = _make_slack_adapter()
        assert adapter.format_user_mention("U123") == "<@U123>"
        assert adapter.format_user_mention("") == ""


# ===========================================================================
# Slack _handle_file_approval_action
# ===========================================================================

def _click_body(user_id="U_MANAGER", user_name="boss"):
    return {
        "message": {
            "ts": "1234.5678",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "original"}},
                {"type": "actions", "elements": []},
            ],
        },
        "channel": {"id": "C1"},
        "user": {"name": user_name, "id": user_id},
    }


class TestSlackFileApprovalAction:
    @pytest.mark.asyncio
    async def test_approve_click_decides_and_updates_message(self, monkeypatch):
        monkeypatch.delenv("SLACK_ALLOWED_USERS", raising=False)
        adapter = _make_slack_adapter()
        mock_client = adapter._team_clients["T1"]
        mock_client.chat_update = AsyncMock()

        ack = AsyncMock()
        action = {"action_id": "hermes_file_approve", "value": "abc123"}

        with patch(
            "agent.file_change_approvals.decide_from_platform_click",
            return_value={"success": True, "approval": {"id": "abc123"}},
        ) as mock_decide:
            await adapter._handle_file_approval_action(ack, _click_body(), action)

        ack.assert_called_once()
        mock_decide.assert_called_once_with(
            "abc123",
            approve=True,
            platform="slack",
            user_id="U_MANAGER",
            user_name="boss",
        )
        update_kwargs = mock_client.chat_update.call_args[1]
        assert "Staged edit approved by boss" in update_kwargs["text"]
        assert "permissions unchanged" in update_kwargs["text"]

    @pytest.mark.asyncio
    async def test_unauthorized_click_gets_ephemeral_error(self, monkeypatch):
        monkeypatch.delenv("SLACK_ALLOWED_USERS", raising=False)
        adapter = _make_slack_adapter()
        mock_client = adapter._team_clients["T1"]
        mock_client.chat_update = AsyncMock()
        mock_client.chat_postEphemeral = AsyncMock()

        ack = AsyncMock()
        action = {"action_id": "hermes_file_approve", "value": "abc123"}

        with patch(
            "agent.file_change_approvals.decide_from_platform_click",
            return_value={
                "success": False,
                "error": "slack:U_INTRUDER cannot approve this file change.",
                "status_code": 403,
            },
        ):
            await adapter._handle_file_approval_action(
                ack, _click_body(user_id="U_INTRUDER", user_name="intruder"), action
            )

        mock_client.chat_update.assert_not_called()
        eph_kwargs = mock_client.chat_postEphemeral.call_args[1]
        assert eph_kwargs["user"] == "U_INTRUDER"
        assert "cannot approve" in eph_kwargs["text"]

    @pytest.mark.asyncio
    async def test_deny_click(self, monkeypatch):
        monkeypatch.delenv("SLACK_ALLOWED_USERS", raising=False)
        adapter = _make_slack_adapter()
        mock_client = adapter._team_clients["T1"]
        mock_client.chat_update = AsyncMock()

        ack = AsyncMock()
        action = {"action_id": "hermes_file_deny", "value": "abc123"}

        with patch(
            "agent.file_change_approvals.decide_from_platform_click",
            return_value={"success": True, "approval": {"id": "abc123"}},
        ) as mock_decide:
            await adapter._handle_file_approval_action(ack, _click_body(), action)

        assert mock_decide.call_args.kwargs["approve"] is False
        update_kwargs = mock_client.chat_update.call_args[1]
        assert "Staged edit rejected by boss" in update_kwargs["text"]
        assert "permissions unchanged" in update_kwargs["text"]


# ===========================================================================
# GatewayRunner routing — _send_file_approval_card / _file_approval_mentions
# ===========================================================================

class _CardAdapter:
    """Fake adapter that supports button cards."""

    def __init__(self):
        self.cards = []
        self.sends = []

    def format_user_mention(self, user_id: str) -> str:
        return f"<@{user_id}>"

    async def send_file_approval(self, **kwargs):
        self.cards.append(kwargs)
        return SendResult(success=True, message_id="1")

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sends.append({"chat_id": chat_id, "content": content, "metadata": metadata})
        return SendResult(success=True, message_id="2")


class _TextAdapter:
    """Fake adapter without button support — text fallback path."""

    def __init__(self):
        self.sends = []

    def format_user_mention(self, user_id: str) -> str:
        return ""

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sends.append({"chat_id": chat_id, "content": content, "metadata": metadata})
        return SendResult(success=True, message_id="3")


def _make_runner(adapter, platform=Platform.SLACK):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.adapters = {platform: adapter}
    return runner


def _request(platform="slack", chat_id="C1", thread_id=""):
    origin = {"platform": platform, "chat_id": chat_id}
    if thread_id:
        origin["thread_id"] = thread_id
    return {
        "id": "abc123",
        "path": "/srv/finance/report.md",
        "display_path": "/srv/finance/report.md",
        "diff": "-a\n+b",
        "requested_by": {"id": "slack:U_WRITER"},
        "origin": origin,
        "requirement": {"roles": ["manager"], "users": []},
    }


class TestGatewayCardRouting:
    @pytest.mark.asyncio
    async def test_card_sent_with_platform_filtered_mentions(self):
        adapter = _CardAdapter()
        runner = _make_runner(adapter)

        with patch(
            "agent.governance.eligible_file_change_approvers",
            return_value=["slack:U_MANAGER", "slack:U_ADMIN", "discord:999"],
        ), patch(
            "agent.file_change_approvals.record_file_change_approval_delivery"
        ) as record_delivery:
            await runner._send_file_approval_card(_request(thread_id="9.9"))

        assert len(adapter.cards) == 1
        card = adapter.cards[0]
        assert card["approval_id"] == "abc123"
        assert card["chat_id"] == "C1"
        assert card["metadata"] == {"thread_id": "9.9"}
        # Same-platform approvers mentioned; the discord one filtered out.
        assert "<@U_MANAGER>" in card["mention_text"]
        assert "<@U_ADMIN>" in card["mention_text"]
        assert "999" not in card["mention_text"]
        assert "slack:U_MANAGER" in card["approver_summary"]
        assert "slack:U_ADMIN" in card["approver_summary"]
        record_delivery.assert_called_once_with(
            "abc123",
            platform="slack",
            chat_id="C1",
            thread_id="9.9",
            message_id="1",
        )

    @pytest.mark.asyncio
    async def test_text_fallback_when_adapter_has_no_buttons(self):
        adapter = _TextAdapter()
        runner = _make_runner(adapter)

        with patch(
            "agent.governance.eligible_file_change_approvers",
            return_value=["slack:U_MANAGER"],
        ):
            await runner._send_file_approval_card(_request())

        assert len(adapter.sends) == 1
        content = adapter.sends[0]["content"]
        assert "Specific file edit awaiting approval" in content
        assert "/srv/finance/report.md" in content
        assert "role manager" in content
        assert "original file is unchanged" in content
        assert "dashboard" in content.lower()
        assert "does not change file-access permissions" in content

    @pytest.mark.asyncio
    async def test_no_origin_no_send(self):
        adapter = _CardAdapter()
        runner = _make_runner(adapter)
        request = _request()
        request["origin"] = {}  # CLI / dashboard staging — nothing to notify

        await runner._send_file_approval_card(request)

        assert adapter.cards == []
        assert adapter.sends == []

    @pytest.mark.asyncio
    async def test_unknown_platform_ignored(self):
        adapter = _CardAdapter()
        runner = _make_runner(adapter)
        request = _request(platform="carrier-pigeon")

        await runner._send_file_approval_card(request)

        assert adapter.cards == []

    @pytest.mark.asyncio
    async def test_notifier_registration_routes_staged_request(self):
        """End-to-end: registered notifier bridges the (worker-thread) staging
        callback onto the loop and delivers the card."""
        from agent import file_change_approvals as fca

        adapter = _CardAdapter()
        runner = _make_runner(adapter)
        runner._register_file_approval_notifier()
        try:
            with patch(
                "agent.governance.eligible_file_change_approvers",
                return_value=[],
            ):
                fca._fire_notifier(_request())
                await asyncio.sleep(0.05)
        finally:
            fca.set_file_approval_notifier(None)

        assert len(adapter.cards) == 1


# ===========================================================================
# GatewayRunner plain-language file-edit decisions
# ===========================================================================

def _decision_event(text: str, *, reply_to_message_id: str = "") -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.SLACK,
            user_id="U_MANAGER",
            chat_id="C1",
            thread_id="T1",
            user_name="Manager",
            chat_type="channel",
        ),
        message_id="M_DECISION",
        reply_to_message_id=reply_to_message_id or None,
    )


class TestGatewayTextFileApproval:
    @pytest.mark.asyncio
    async def test_handle_message_resolves_file_decision_before_agent_dispatch(self):
        runner = _make_runner(_CardAdapter())
        runner.session_store = None
        runner.config = SimpleNamespace(
            group_sessions_per_user=True,
            thread_sessions_per_user=False,
        )
        runner._update_prompt_pending = {}
        runner._is_user_authorized = lambda _source, **_kwargs: True
        runner._running_agents = {"slack:C1:U_MANAGER": object()}

        with patch.object(
            runner,
            "_maybe_handle_file_change_text_decision",
            AsyncMock(return_value="specific edit applied"),
        ) as decide:
            response = await runner._handle_message(_decision_event("aprovo"))

        assert response == "specific edit applied"
        decide.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_pending_edit_explains_that_permissions_do_not_change(self):
        runner = _make_runner(_CardAdapter())
        with patch(
            "agent.file_change_approvals.decide_file_change_from_text",
            return_value={
                "handled": True,
                "success": False,
                "code": "no_pending_file_change",
                "decision": "approve",
                "language": "pt",
            },
        ) as decide:
            response = await runner._maybe_handle_file_change_text_decision(
                _decision_event("aprovo")
            )

        assert "não concede acesso de escrita" in response
        assert "não altera políticas" in response
        decide.assert_called_once_with(
            "aprovo",
            platform="slack",
            chat_id="C1",
            thread_id="T1",
            user_id="U_MANAGER",
            user_name="Manager",
            reply_to_message_id="",
        )

    @pytest.mark.asyncio
    async def test_success_response_is_scoped_to_staged_edit(self):
        runner = _make_runner(_CardAdapter())
        with patch(
            "agent.file_change_approvals.decide_file_change_from_text",
            return_value={
                "handled": True,
                "success": True,
                "decision": "approve",
                "language": "pt",
                "path": "/srv/finance/report.md",
                "approval": {"status": "approved"},
            },
        ):
            response = await runner._maybe_handle_file_change_text_decision(
                _decision_event("aprovo", reply_to_message_id="M_APPROVAL")
            )

        assert "Edição específica aprovada e aplicada" in response
        assert "permissões de acesso não foram modificadas" in response


# ===========================================================================
# Telegram mention formatting
# ===========================================================================

class TestTelegramMention:
    def test_numeric_id_becomes_deep_link(self):
        from gateway.platforms.telegram import TelegramAdapter

        adapter = object.__new__(TelegramAdapter)
        assert 'tg://user?id=12345' in adapter.format_user_mention("12345")

    def test_username_passthrough(self):
        from gateway.platforms.telegram import TelegramAdapter

        adapter = object.__new__(TelegramAdapter)
        assert adapter.format_user_mention("alice") == "@alice"
        assert adapter.format_user_mention("@bob") == "@bob"

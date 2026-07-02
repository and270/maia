"""Tests for /resume gateway slash command.

Tests the _handle_resume_command handler (switch to a previously-named session)
across gateway messenger platforms.
"""

from unittest.mock import MagicMock

import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource, build_session_key


def _make_event(text="/resume", platform=Platform.TELEGRAM,
                user_id="12345", chat_id="67890"):
    """Build a MessageEvent for testing."""
    source = SessionSource(
        platform=platform,
        user_id=user_id,
        chat_id=chat_id,
        user_name="testuser",
    )
    return MessageEvent(text=text, source=source)


def _session_key_for_event(event):
    """Get the session key that build_session_key produces for an event."""
    return build_session_key(event.source)


def _make_runner(session_db=None, current_session_id="current_session_001",
                 event=None):
    """Create a bare GatewayRunner with a mock session_store and optional session_db."""
    from gateway.run import GatewayRunner
    runner = object.__new__(GatewayRunner)
    runner.adapters = {}
    runner._voice_mode = {}
    runner._session_db = session_db
    runner._running_agents = {}

    # Compute the real session key if an event is provided
    session_key = build_session_key(event.source) if event else "agent:main:telegram:dm"

    # Mock session_store that returns a session entry with a known session_id
    mock_session_entry = MagicMock()
    mock_session_entry.session_id = current_session_id
    mock_session_entry.session_key = session_key
    mock_store = MagicMock()
    mock_store.get_or_create_session.return_value = mock_session_entry
    mock_store.load_transcript.return_value = []
    mock_store.switch_session.return_value = mock_session_entry
    runner.session_store = mock_store

    return runner


# ---------------------------------------------------------------------------
# _handle_resume_command
# ---------------------------------------------------------------------------


class TestHandleResumeCommand:
    """Tests for GatewayRunner._handle_resume_command."""

    @pytest.mark.asyncio
    async def test_no_session_db(self):
        """Returns error when session database is unavailable."""
        runner = _make_runner(session_db=None)
        event = _make_event(text="/resume My Project")
        result = await runner._handle_resume_command(event)
        assert "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_list_named_sessions_when_no_arg(self, tmp_path):
        """With no argument, lists recently titled sessions."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("sess_001", "telegram", user_id="12345")
        db.create_session("sess_002", "telegram", user_id="12345")
        db.set_session_title("sess_001", "Research")
        db.set_session_title("sess_002", "Coding")

        event = _make_event(text="/resume")
        runner = _make_runner(session_db=db, event=event)
        result = await runner._handle_resume_command(event)
        assert "Research" in result
        assert "Coding" in result
        assert "Named Sessions" in result
        db.close()

    @pytest.mark.asyncio
    async def test_list_shows_usage_when_no_titled(self, tmp_path):
        """With no arg and no titled sessions, shows instructions."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("sess_001", "telegram", user_id="12345")  # No title

        event = _make_event(text="/resume")
        runner = _make_runner(session_db=db, event=event)
        result = await runner._handle_resume_command(event)
        assert "No named sessions" in result
        assert "/title" in result
        db.close()

    @pytest.mark.asyncio
    async def test_resume_by_name(self, tmp_path):
        """Resolves a title and switches to that session."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("old_session_abc", "telegram", user_id="12345")
        db.set_session_title("old_session_abc", "My Project")
        db.create_session("current_session_001", "telegram", user_id="12345")

        event = _make_event(text="/resume My Project")
        runner = _make_runner(session_db=db, current_session_id="current_session_001",
                              event=event)
        result = await runner._handle_resume_command(event)

        assert "Resumed" in result
        assert "My Project" in result
        # Verify switch_session was called with the old session ID
        runner.session_store.switch_session.assert_called_once()
        call_args = runner.session_store.switch_session.call_args
        assert call_args[0][1] == "old_session_abc"
        db.close()

    @pytest.mark.asyncio
    async def test_resume_nonexistent_name(self, tmp_path):
        """Returns error for unknown session name."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("current_session_001", "telegram", user_id="12345")

        event = _make_event(text="/resume Nonexistent Session")
        runner = _make_runner(session_db=db, event=event)
        result = await runner._handle_resume_command(event)
        assert "No session found" in result
        db.close()

    @pytest.mark.asyncio
    async def test_resume_already_on_session(self, tmp_path):
        """Returns friendly message when already on the requested session."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("current_session_001", "telegram", user_id="12345")
        db.set_session_title("current_session_001", "Active Project")

        event = _make_event(text="/resume Active Project")
        runner = _make_runner(session_db=db, current_session_id="current_session_001",
                              event=event)
        result = await runner._handle_resume_command(event)
        assert "Already on session" in result
        db.close()

    @pytest.mark.asyncio
    async def test_resume_auto_lineage(self, tmp_path):
        """Asking for 'My Project' when 'My Project #2' exists gets the latest."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("sess_v1", "telegram", user_id="12345")
        db.set_session_title("sess_v1", "My Project")
        db.create_session("sess_v2", "telegram", user_id="12345")
        db.set_session_title("sess_v2", "My Project #2")
        db.create_session("current_session_001", "telegram", user_id="12345")

        event = _make_event(text="/resume My Project")
        runner = _make_runner(session_db=db, current_session_id="current_session_001",
                              event=event)
        result = await runner._handle_resume_command(event)

        assert "Resumed" in result
        # Should resolve to #2 (latest in lineage)
        call_args = runner.session_store.switch_session.call_args
        assert call_args[0][1] == "sess_v2"
        db.close()

    @pytest.mark.asyncio
    async def test_resume_follows_compression_continuation(self, tmp_path):
        """Gateway /resume should reopen the live descendant after compression."""
        from hermes_state import SessionDB

        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("compressed_root", "telegram", user_id="12345")
        db.set_session_title("compressed_root", "Compressed Work")
        db.end_session("compressed_root", "compression")
        db.create_session("compressed_child", "telegram", user_id="12345", parent_session_id="compressed_root")
        db.append_message("compressed_child", "user", "hello from continuation")
        db.create_session("current_session_001", "telegram", user_id="12345")

        event = _make_event(text="/resume Compressed Work")
        runner = _make_runner(
            session_db=db,
            current_session_id="current_session_001",
            event=event,
        )
        runner.session_store.load_transcript.side_effect = (
            lambda session_id: [{"role": "user", "content": "hello from continuation"}]
            if session_id == "compressed_child"
            else []
        )

        result = await runner._handle_resume_command(event)

        assert "Resumed session" in result
        assert "(1 message)" in result
        call_args = runner.session_store.switch_session.call_args
        assert call_args[0][1] == "compressed_child"
        runner.session_store.load_transcript.assert_called_with("compressed_child")
        db.close()

    @pytest.mark.asyncio
    async def test_resume_clears_running_agent(self, tmp_path):
        """Switching sessions clears any cached running agent."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("old_session", "telegram", user_id="12345")
        db.set_session_title("old_session", "Old Work")
        db.create_session("current_session_001", "telegram", user_id="12345")

        event = _make_event(text="/resume Old Work")
        runner = _make_runner(session_db=db, current_session_id="current_session_001",
                              event=event)
        # Simulate a running agent using the real session key
        real_key = _session_key_for_event(event)
        runner._running_agents[real_key] = MagicMock()

        await runner._handle_resume_command(event)

        assert real_key not in runner._running_agents
        db.close()

    @pytest.mark.asyncio
    async def test_resume_evicts_cached_agent(self, tmp_path):
        """Gateway /resume evicts the cached AIAgent so the next message
        rebuilds with the correct session_id end-to-end — mirrors /branch
        and /reset. Without this, the cached agent's memory provider keeps
        writing into the wrong session. See #6672.
        """
        import threading
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("old_session", "telegram", user_id="12345")
        db.set_session_title("old_session", "Old Work")
        db.create_session("current_session_001", "telegram", user_id="12345")

        event = _make_event(text="/resume Old Work")
        runner = _make_runner(session_db=db, current_session_id="current_session_001",
                              event=event)
        # Seed the cache with a fake agent
        real_key = _session_key_for_event(event)
        runner._agent_cache = {real_key: (MagicMock(), object())}
        runner._agent_cache_lock = threading.RLock()

        await runner._handle_resume_command(event)

        assert real_key not in runner._agent_cache
        db.close()


# ---------------------------------------------------------------------------
# /resume ownership guard (IDOR) — ported from upstream c4f278c02
# ---------------------------------------------------------------------------


class TestResumeOwnershipGuard:
    """A session id/title is a routing handle, not authority: /resume and the
    titled-session listing must be scoped to the caller's own origin."""

    @pytest.mark.asyncio
    async def test_resume_other_users_session_blocked(self, tmp_path):
        """A caller cannot resume a persisted session owned by another user."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("victim_sess", "telegram", user_id="99999")
        db.set_session_title("victim_sess", "Victim Project")

        event = _make_event(text="/resume Victim Project", user_id="12345")
        runner = _make_runner(session_db=db, event=event)
        result = await runner._handle_resume_command(event)
        assert "blocked" in result
        assert not runner.session_store.switch_session.called
        db.close()

    @pytest.mark.asyncio
    async def test_resume_unowned_row_fails_closed(self, tmp_path):
        """An identity-bearing caller cannot bind to a NULL-owner row."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("legacy_sess", "telegram")  # no user_id recorded
        db.set_session_title("legacy_sess", "Legacy")

        event = _make_event(text="/resume Legacy", user_id="12345")
        runner = _make_runner(session_db=db, event=event)
        result = await runner._handle_resume_command(event)
        assert "blocked" in result
        db.close()

    @pytest.mark.asyncio
    async def test_resume_cross_platform_blocked(self, tmp_path):
        """A caller on one platform cannot resume another platform's session."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("slack_sess", "slack", user_id="12345")
        db.set_session_title("slack_sess", "Slack Work")

        event = _make_event(text="/resume Slack Work", user_id="12345",
                            platform=Platform.TELEGRAM)
        runner = _make_runner(session_db=db, event=event)
        result = await runner._handle_resume_command(event)
        assert "blocked" in result
        db.close()

    @pytest.mark.asyncio
    async def test_listing_hides_other_users_sessions(self, tmp_path):
        """The no-arg listing must not enumerate other users' titles/previews."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("mine", "telegram", user_id="12345")
        db.set_session_title("mine", "My Research")
        db.create_session("theirs", "telegram", user_id="99999")
        db.set_session_title("theirs", "Secret Plans")

        event = _make_event(text="/resume", user_id="12345")
        runner = _make_runner(session_db=db, event=event)
        result = await runner._handle_resume_command(event)
        assert "My Research" in result
        assert "Secret Plans" not in result
        db.close()

    @pytest.mark.asyncio
    async def test_live_origin_other_dm_blocked(self, tmp_path):
        """When the target is live in another user's DM, resume is blocked
        even if the DB row would be ambiguous."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("live_sess", "telegram", user_id="12345")
        db.set_session_title("live_sess", "Hijack Me")

        event = _make_event(text="/resume Hijack Me", user_id="12345")
        runner = _make_runner(session_db=db, event=event)
        runner.config = MagicMock(group_sessions_per_user=True,
                                  thread_sessions_per_user=False)
        other_origin = SessionSource(
            platform=Platform.TELEGRAM, user_id="99999", chat_id="55555",
            user_name="other", chat_type="dm",
        )
        runner.session_store.origin_for_session_id = lambda sid: other_origin
        result = await runner._handle_resume_command(event)
        assert "blocked" in result
        db.close()

    @pytest.mark.asyncio
    async def test_admin_all_override(self, tmp_path, monkeypatch):
        """A configured governance admin may cross origins with --all."""
        from hermes_state import SessionDB
        import agent.governance as governance
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("victim_sess", "telegram", user_id="99999")
        db.set_session_title("victim_sess", "Victim Project")

        monkeypatch.setattr(governance, "load_governance_config", lambda: {
            "enabled": True,
            "role_hierarchy": ["viewer", "operator", "manager", "admin"],
            "users": {"telegram:12345": {"roles": ["admin"]}},
        })

        event = _make_event(text="/resume --all Victim Project", user_id="12345")
        runner = _make_runner(session_db=db, event=event)
        runner._evict_cached_agent = MagicMock()
        runner._release_running_agent_state = MagicMock()
        runner._clear_session_boundary_security_state = MagicMock()
        result = await runner._handle_resume_command(event)
        assert "blocked" not in result
        db.close()

    @pytest.mark.asyncio
    async def test_non_admin_all_flag_still_blocked(self, tmp_path):
        """--all from a non-admin caller must not bypass the guard."""
        from hermes_state import SessionDB
        db = SessionDB(db_path=tmp_path / "state.db")
        db.create_session("victim_sess", "telegram", user_id="99999")
        db.set_session_title("victim_sess", "Victim Project")

        event = _make_event(text="/resume --all Victim Project", user_id="12345")
        runner = _make_runner(session_db=db, event=event)
        result = await runner._handle_resume_command(event)
        assert "blocked" in result
        db.close()

"""Bare `maia` opens the dashboard on desktops; everything else stays chat."""

import sys

import pytest


@pytest.fixture()
def _tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)


def _force_browser_capable(monkeypatch, capable: bool):
    from hermes_cli import main as main_mod

    monkeypatch.setattr(main_mod, "_browser_capable_environment", lambda: capable)


class TestBareMaiaOpensDashboard:
    def test_bare_interactive_desktop_diverts(self, monkeypatch, _tty):
        from hermes_cli import main as main_mod

        monkeypatch.setattr(sys, "argv", ["maia"])
        monkeypatch.delenv("MAIA_NO_DASHBOARD", raising=False)
        monkeypatch.delenv("HERMES_TUI", raising=False)
        _force_browser_capable(monkeypatch, True)

        assert main_mod._bare_maia_opens_dashboard() is True

    def test_any_argument_keeps_terminal_chat(self, monkeypatch, _tty):
        from hermes_cli import main as main_mod

        monkeypatch.setattr(sys, "argv", ["maia", "-c"])
        _force_browser_capable(monkeypatch, True)

        assert main_mod._bare_maia_opens_dashboard() is False

    def test_env_opt_out_keeps_terminal_chat(self, monkeypatch, _tty):
        from hermes_cli import main as main_mod

        monkeypatch.setattr(sys, "argv", ["maia"])
        monkeypatch.setenv("MAIA_NO_DASHBOARD", "1")
        _force_browser_capable(monkeypatch, True)

        assert main_mod._bare_maia_opens_dashboard() is False

    def test_hermes_tui_env_keeps_terminal_chat(self, monkeypatch, _tty):
        from hermes_cli import main as main_mod

        monkeypatch.setattr(sys, "argv", ["maia"])
        monkeypatch.delenv("MAIA_NO_DASHBOARD", raising=False)
        monkeypatch.setenv("HERMES_TUI", "1")
        _force_browser_capable(monkeypatch, True)

        assert main_mod._bare_maia_opens_dashboard() is False

    def test_headless_keeps_terminal_chat(self, monkeypatch, _tty):
        from hermes_cli import main as main_mod

        monkeypatch.setattr(sys, "argv", ["maia"])
        monkeypatch.delenv("MAIA_NO_DASHBOARD", raising=False)
        monkeypatch.delenv("HERMES_TUI", raising=False)
        _force_browser_capable(monkeypatch, False)

        assert main_mod._bare_maia_opens_dashboard() is False

    def test_non_tty_keeps_terminal_chat(self, monkeypatch):
        from hermes_cli import main as main_mod

        monkeypatch.setattr(sys, "argv", ["maia"])
        monkeypatch.delenv("MAIA_NO_DASHBOARD", raising=False)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
        _force_browser_capable(monkeypatch, True)

        assert main_mod._bare_maia_opens_dashboard() is False

    def test_reuses_running_dashboard_instead_of_rebinding(self, monkeypatch, capsys):
        from hermes_cli import main as main_mod

        opened: list[str] = []
        monkeypatch.setattr(main_mod, "_find_stale_dashboard_pids", lambda: [1234])
        monkeypatch.setattr(main_mod, "_open_url_in_browser", opened.append)
        started: list[object] = []
        monkeypatch.setattr(main_mod, "cmd_dashboard", started.append)

        main_mod._launch_dashboard_from_bare_maia()

        assert opened == ["http://127.0.0.1:9119"]
        assert started == []
        assert "already running" in capsys.readouterr().out

    def test_starts_dashboard_with_chat_defaults(self, monkeypatch):
        from hermes_cli import main as main_mod

        monkeypatch.setattr(main_mod, "_find_stale_dashboard_pids", lambda: [])
        started: list = []
        monkeypatch.setattr(main_mod, "cmd_dashboard", started.append)

        main_mod._launch_dashboard_from_bare_maia()

        assert len(started) == 1
        ns = started[0]
        assert ns.host == "127.0.0.1"
        assert ns.port == 9119
        assert ns.no_chat is False
        assert ns.no_open is False

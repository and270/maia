"""Tests for the onboarding first-run state endpoint."""

import os

import pytest


class TestOnboardingState:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, _isolate_hermes_home):
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi/starlette not installed")

        import hermes_state
        from hermes_constants import get_hermes_home
        from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

        monkeypatch.setattr(
            hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db"
        )

        # Ambient provider keys or gateway tokens on the developer machine
        # must not leak into the "fresh install" assertions.
        for var in list(os.environ):
            if var.endswith(("_API_KEY", "_TOKEN", "_BOT_TOKEN")) or var in (
                "WHATSAPP_ENABLED",
                "MATRIX_PASSWORD",
                "GH_TOKEN",
                "GITHUB_TOKEN",
            ):
                monkeypatch.delenv(var, raising=False)

        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def _state(self):
        resp = self.client.get("/api/onboarding/state")
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_fresh_install_reports_nothing_configured(self):
        data = self._state()
        assert data["provider_configured"] is False
        assert data["gateway_configured"] is False
        assert data["governance_configured"] is False
        assert data["dashboard_auth_configured"] is False

    def test_catalog_lists_key_providers_with_env_vars(self):
        catalog = self._state()["providers_catalog"]
        by_slug = {p["slug"]: p for p in catalog}

        assert by_slug["anthropic"]["env_key"] == "ANTHROPIC_API_KEY"
        assert by_slug["anthropic"]["auth_type"] == "api_key"
        # openrouter predates PROVIDER_REGISTRY; the endpoint fills the gap.
        assert by_slug["openrouter"]["env_key"] == "OPENROUTER_API_KEY"
        # Nous Research's subscription provider belongs to upstream Hermes,
        # not Maia, and must never appear in the onboarding catalog.
        assert "nous" not in by_slug
        # OAuth providers are listed but carry no key env (handled elsewhere).
        assert by_slug["openai-codex"]["auth_type"] != "api_key"

    def test_nous_is_absent_from_maia_oauth_catalog(self):
        from hermes_cli.web_server import _OAUTH_PROVIDER_CATALOG

        assert "nous" not in {entry["id"] for entry in _OAUTH_PROVIDER_CATALOG}

    def test_saving_a_key_flips_provider_configured_without_restart(self):
        assert self._state()["provider_configured"] is False

        resp = self.client.put(
            "/api/env", json={"key": "DEEPSEEK_API_KEY", "value": "sk-test-123"}
        )
        assert resp.status_code == 200, resp.text

        assert self._state()["provider_configured"] is True

    def test_gateway_token_flips_gateway_configured(self):
        assert self._state()["gateway_configured"] is False

        resp = self.client.put(
            "/api/env", json={"key": "SLACK_BOT_TOKEN", "value": "xoxb-test"}
        )
        assert resp.status_code == 200, resp.text

        assert self._state()["gateway_configured"] is True

    def test_default_governance_does_not_complete_onboarding(self):
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("governance", {})["enabled"] = True
        save_config(cfg)

        assert self._state()["governance_configured"] is False

    def test_bootstrap_admin_does_not_complete_governance_onboarding(self):
        from hermes_cli.config import save_config, save_env_value

        save_env_value("SLACK_ALLOWED_USERS", "UADMIN")
        save_config(
            {
                "governance": {
                    "users": {
                        "slack:UADMIN": {
                            "name": "Ana Admin",
                            "roles": ["admin"],
                        }
                    },
                    "folder_policies": [
                        {
                            "path": "/srv/company",
                            "read_users": ["slack:UADMIN"],
                        }
                    ],
                }
            }
        )

        assert self._state()["governance_configured"] is False

    def test_non_admin_without_file_access_remains_pending(self):
        from hermes_cli.config import save_config, save_env_value

        save_env_value("SLACK_ALLOWED_USERS", "UADMIN,UOPERATOR")
        save_config(
            {
                "governance": {
                    "users": {
                        "slack:UADMIN": {"roles": ["admin"]},
                        "slack:UOPERATOR": {"roles": ["operator"]},
                    }
                }
            }
        )

        assert self._state()["governance_configured"] is False

    def test_governed_non_admin_with_direct_file_access_completes_onboarding(self):
        from hermes_cli.config import save_config, save_env_value

        save_env_value("SLACK_ALLOWED_USERS", "UADMIN,UOPERATOR")
        save_config(
            {
                "governance": {
                    "users": {
                        "slack:UADMIN": {"roles": ["admin"]},
                        "slack:UOPERATOR": {"roles": ["operator"]},
                    },
                    "folder_policies": [
                        {
                            "path": "/srv/company",
                            "read_users": ["slack:UOPERATOR"],
                        }
                    ],
                }
            }
        )

        assert self._state()["governance_configured"] is True

    def test_governed_non_admin_with_team_file_access_completes_onboarding(self):
        from hermes_cli.config import save_config, save_env_value

        save_env_value("DISCORD_ALLOWED_USERS", "111111111111111111,222222222222222222")
        save_config(
            {
                "governance": {
                    "users": {
                        "discord:111111111111111111": {"roles": ["admin"]},
                        "discord:222222222222222222": {
                            "roles": ["viewer"],
                            "teams": ["support"],
                        },
                    },
                    "teams": {"support": {}},
                    "folder_policies": [
                        {
                            "path": "/srv/support",
                            "read_teams": ["support"],
                        }
                    ],
                }
            }
        )

        assert self._state()["governance_configured"] is True

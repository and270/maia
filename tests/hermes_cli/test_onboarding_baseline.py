"""Tests for the onboarding governance-baseline endpoint."""

import pytest


class TestGovernanceBaseline:
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
        self.client = TestClient(app)
        self.client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    def test_apply_writes_the_combo_and_returns_gaps(self):
        resp = self.client.post(
            "/api/onboarding/apply-governance-baseline",
            json={
                "terminal_allowed_roles": ["operator"],
                "terminal_approver_roles": ["manager"],
                "smart_approvals": True,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert "governance.default_file_policy" not in data["applied"]
        assert data["applied"]["approvals.mode"] == "smart"

        # Config on disk reflects the combo.
        from hermes_cli.config import load_config

        cfg = load_config()
        gov = cfg["governance"]
        assert gov["enabled"] is True
        assert "default_file_policy" not in gov
        assert gov["terminal"]["allowed_roles"] == ["operator"]
        assert gov["terminal"]["approver_roles"] == ["manager"]
        assert cfg["observability"]["audit_log_enabled"] is True
        assert cfg["approvals"]["mode"] == "smart"

        # No folder policies configured yet → the response surfaces that gap.
        codes = {w["code"] for w in data["warnings"]}
        assert "no_folder_policies" in codes
        # ...but the terminal gap is closed by the baseline.
        assert "terminal_ungoverned" not in codes

    def test_apply_preserves_existing_users_and_policies(self):
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        cfg.setdefault("governance", {})
        cfg["governance"]["users"] = {"slack:U1": {"roles": ["manager"]}}
        cfg["governance"]["folder_policies"] = [
            {"path": "/srv/x", "read_roles": ["manager"]}
        ]
        save_config(cfg)

        resp = self.client.post(
            "/api/onboarding/apply-governance-baseline", json={}
        )
        assert resp.status_code == 200, resp.text

        cfg2 = load_config()
        assert cfg2["governance"]["users"] == {"slack:U1": {"roles": ["manager"]}}
        assert cfg2["governance"]["folder_policies"] == [
            {"path": "/srv/x", "read_roles": ["manager"]}
        ]
        # With a policy present, that gap is gone.
        codes = {w["code"] for w in resp.json()["warnings"]}
        assert "no_folder_policies" not in codes

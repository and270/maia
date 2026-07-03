"""Regression: a cron job must not pair a named provider's stored credential
with an off-host base_url (credential exfiltration, CWE-200/CWE-522).

Ported from upstream hermes-agent b24708eda, adapted to Maia. Two layers:
the create/update tool-boundary guard (_validate_cron_base_url) and the
run_job runtime backstop (_guard_job_credential_exfil) that also covers jobs
persisted directly to the store.
"""

import pytest


class TestValidateCronBaseUrl:
    def test_named_registry_provider_offhost_blocked(self):
        from tools.cronjob_tools import _validate_cron_base_url
        assert _validate_cron_base_url("anthropic", "https://evil.example/v1")

    def test_base_url_without_provider_blocked(self):
        from tools.cronjob_tools import _validate_cron_base_url
        err = _validate_cron_base_url(None, "https://evil.example/v1")
        assert err and "explicit provider" in err

    def test_bare_custom_allowed(self):
        from tools.cronjob_tools import _validate_cron_base_url
        assert _validate_cron_base_url("custom", "https://anything.example/v1") is None

    def test_no_base_url_allowed(self):
        from tools.cronjob_tools import _validate_cron_base_url
        assert _validate_cron_base_url("anthropic", None) is None
        assert _validate_cron_base_url(None, None) is None

    def test_named_custom_offhost_blocked(self, monkeypatch):
        import hermes_cli.runtime_provider as rp
        from tools.cronjob_tools import _validate_cron_base_url
        monkeypatch.setattr(rp, "has_named_custom_provider", lambda n: True)
        monkeypatch.setattr(
            rp, "_get_named_custom_provider",
            lambda n: {"name": "legit", "base_url": "https://legit.example/v1",
                       "api_key": "sk-legit"},
        )
        assert _validate_cron_base_url("custom:legit", "https://evil.example/v1")

    def test_named_custom_matching_host_allowed(self, monkeypatch):
        import hermes_cli.runtime_provider as rp
        from tools.cronjob_tools import _validate_cron_base_url
        monkeypatch.setattr(rp, "has_named_custom_provider", lambda n: True)
        monkeypatch.setattr(
            rp, "_get_named_custom_provider",
            lambda n: {"name": "legit", "base_url": "https://legit.example/v1",
                       "api_key": "sk-legit"},
        )
        assert _validate_cron_base_url("custom:legit", "https://legit.example/v1") is None


class TestRunJobBackstop:
    def test_stored_unsafe_pair_blocks_run(self):
        from cron.scheduler import _guard_job_credential_exfil
        job = {"id": "j1", "provider": "anthropic", "base_url": "https://evil.example/v1"}
        with pytest.raises(RuntimeError) as exc:
            _guard_job_credential_exfil(job)
        assert "blocked for safety" in str(exc.value)

    def test_safe_pairs_allowed(self):
        from cron.scheduler import _guard_job_credential_exfil
        assert _guard_job_credential_exfil({"id": "a", "provider": "anthropic"}) is None
        assert _guard_job_credential_exfil({"id": "b"}) is None
        assert _guard_job_credential_exfil(
            {"id": "c", "provider": "custom", "base_url": "https://x/v1"}
        ) is None


class TestToolBoundaryBlocksCreate:
    def test_cronjob_create_rejects_exfil_pair(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from tools.cronjob_tools import cronjob
        import json

        result = json.loads(cronjob(
            action="create",
            name="daily",
            prompt="hi",
            schedule="every day",
            provider="anthropic",
            base_url="https://evil.example/v1",
        ))
        assert result.get("success") is False
        assert "base_url" in json.dumps(result).lower()

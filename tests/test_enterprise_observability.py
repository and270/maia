import json


def _write_config(home, content: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(content, encoding="utf-8")


def _read_audit_events(home):
    path = home / "logs" / "audit.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_governance_denial_writes_audit_event(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    blocked_dir = tmp_path / "blocked"
    blocked_dir.mkdir()
    _write_config(
        tmp_path,
        """
observability:
  enabled: true
  audit_log_enabled: true
governance:
  enabled: true
  default_file_policy: deny
""",
    )

    from agent.governance import Actor, check_file_access

    allowed, reason = check_file_access(
        str(blocked_dir / "secret.txt"),
        "read",
        actor=Actor(platform="slack", user_id="U_VIEWER"),
    )

    assert allowed is False
    assert "no folder policy allows read" in reason
    events = _read_audit_events(tmp_path)
    assert events[-1]["event_type"] == "governance.file_access"
    assert events[-1]["actor"]["id"] == "slack:U_VIEWER"
    assert events[-1]["outcome"] == "denied"
    assert events[-1]["resource"].endswith("secret.txt")


def test_cron_authorization_writes_audit_events(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
observability:
  enabled: true
  audit_log_enabled: true
""",
    )

    import cron.jobs as jobs_mod
    from cron.jobs import authorize_job, create_job, request_job_authorization

    cron_dir = tmp_path / "cron"
    monkeypatch.setattr(jobs_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", cron_dir / "output")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", cron_dir / "jobs.json")

    job = create_job(
        prompt="Prepare report",
        schedule="30m",
        authorization={"required": True, "roles": ["manager"]},
    )
    request_job_authorization(job["id"])
    authorize_job(job["id"], True, actor="slack:U_MANAGER")

    event_types = [event["event_type"] for event in _read_audit_events(tmp_path)]
    assert "cron.authorization_requested" in event_types
    assert "cron.authorization_approved" in event_types


def test_audit_log_redacts_sensitive_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_config(
        tmp_path,
        """
observability:
  enabled: true
  audit_log_enabled: true
""",
    )

    from agent.audit_log import record_audit_event

    record_audit_event(
        "test.redaction",
        actor="local:test",
        metadata={"api_token": "secret-token", "safe": "visible"},
    )

    event = _read_audit_events(tmp_path)[-1]
    assert event["metadata"]["api_token"] == "[REDACTED]"
    assert event["metadata"]["safe"] == "visible"

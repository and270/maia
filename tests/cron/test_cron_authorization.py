from datetime import datetime, timedelta, timezone


def test_scheduler_pauses_authorized_job_before_execution(tmp_path, monkeypatch):
    import cron.jobs as jobs_mod
    import cron.scheduler as scheduler_mod
    from cron.jobs import create_job, get_job

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cron_dir = tmp_path / "cron"
    monkeypatch.setattr(jobs_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", cron_dir / "output")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", cron_dir / "jobs.json")

    delivered = []
    executed = []
    monkeypatch.setattr(
        scheduler_mod,
        "_deliver_result",
        lambda job, message, adapters=None, loop=None: delivered.append((job, message)),
    )
    monkeypatch.setattr(
        scheduler_mod,
        "run_job",
        lambda job: executed.append(job) or (True, "", "", None),
    )

    run_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    job = create_job(
        prompt="Send the finance report",
        schedule=run_at,
        authorization={"required": True, "roles": ["manager"]},
    )

    assert scheduler_mod.tick(verbose=False) == 0

    stored = get_job(job["id"])
    assert stored["state"] == "awaiting_authorization"
    assert stored["enabled"] is False
    assert stored["next_run_at"] is None
    assert stored["authorization"]["status"] == "pending"
    assert stored["authorization"]["requested_at"]
    assert executed == []
    assert len(delivered) == 1
    assert f"Job ID: {job['id']}" in delivered[0][1]
    assert "cronjob(action='authorize'" in delivered[0][1]


def test_authorized_recurring_job_requires_fresh_approval_after_run(tmp_path, monkeypatch):
    import cron.jobs as jobs_mod
    from cron.jobs import authorize_job, create_job, get_job, mark_job_run, request_job_authorization

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cron_dir = tmp_path / "cron"
    monkeypatch.setattr(jobs_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", cron_dir / "output")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", cron_dir / "jobs.json")

    job = create_job(
        prompt="Send the finance report",
        schedule="every 5m",
        authorization={"required": True, "roles": ["manager"]},
    )
    request_job_authorization(job["id"])
    approved = authorize_job(job["id"], True, actor="slack:U_MANAGER")

    assert approved["authorization"]["status"] == "approved"

    mark_job_run(job["id"], success=True)

    stored = get_job(job["id"])
    assert stored["authorization"]["status"] == "pending"
    assert stored["authorization"]["approved_by"] is None
    assert stored["authorization"]["approved_at"] is None
    assert stored["enabled"] is True

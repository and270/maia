---
title: "Cron Authorization Panel"
description: "Create scheduled jobs with role or user approval checkpoints in Maia."
---

# Cron Authorization Panel

Maia cron jobs can require human approval before each due run.

In the dashboard Cron page:

1. Create a scheduled job.
2. Enable **Require authorization checkpoint**.
3. Enter approver roles such as `manager, admin`, approver users such as `slack:U123`, or both.

Equivalent tool call:

```python
cronjob(
  action="create",
  name="Legal weekly review",
  prompt="Review the legal folder and prepare a weekly risk summary.",
  schedule="0 10 * * MON",
  workdir="/srv/company/legal",
  authorization={"required": True, "roles": ["manager"]},
)
```

When due, the job pauses with `state: awaiting_authorization`. Approve from the dashboard or run:

```python
cronjob(action="authorize", job_id="abc123")
```

Deny with:

```python
cronjob(action="deny", job_id="abc123", reason="Close process is not complete")
```

Recurring jobs require fresh approval after each successful run.

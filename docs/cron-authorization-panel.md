# Cron Authorization Panel

Coorporate Hermes cron jobs can require a human authorization checkpoint before each due run. This is designed for scheduled work that touches governed folders, sends messages externally, or produces outputs that require a manager or admin review.

## Create an Authorized Job

In the dashboard:

1. Open **Cron**.
2. Create a job with a prompt and schedule.
3. Enable **Require authorization checkpoint**.
4. Enter approver roles such as `manager, admin`, approver users such as `slack:U123`, or both.
5. Save the job.

The same configuration can be created from the tool API:

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

## Approval Flow

When the job becomes due, the scheduler changes it to:

```yaml
state: awaiting_authorization
enabled: false
authorization:
  status: pending
  roles: [manager]
```

An authorized user can approve from the dashboard Cron page or with:

```python
cronjob(action="authorize", job_id="abc123")
```

To deny:

```python
cronjob(action="deny", job_id="abc123", reason="Close process is not complete")
```

Denied jobs remain disabled with `state: authorization_denied`.

## Role and User Checks

Authorization is granted when either condition is true:

- the actor matches one of the configured `authorization.users`;
- the actor has one of the configured `authorization.roles`, including role hierarchy inheritance.

If a job omits roles and users, Coorporate Hermes falls back to:

```yaml
governance:
  cron:
    default_authorizer_roles: [admin]
```

## Recurring Jobs

Recurring jobs reset approval status after each successful run. The next due run requires fresh approval.

## Audit Events

Authorization requests, approvals, and denials are written to:

```text
<HERMES_HOME>/logs/audit.jsonl
```

Use `coorporate logs audit` or the dashboard Logs page to review them.

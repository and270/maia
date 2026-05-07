# Enterprise Governance

Coorporate Hermes is an AmpliIA distribution that adds a governance layer for private one-tenant company deployments. It is intentionally configuration-driven so the same assistant can be used by different departments without hardcoding people or folder paths.

## Identity

Gateway users are identified by `platform:user_id`, for example:

- `slack:U123456`
- `discord:99887766`
- `telegram:987654321`

Add users to `config.yaml`:

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U123456":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
```

`roles` drive authorization. `teams` drive shared knowledge injection for team memory and skills.

## Memory and Skill Governance

Coorporate Hermes keeps user memory/skills, but adds approved corporate and team layers above them:

- corporate memory and skills apply to every conversation;
- team memory and skills apply to actors assigned to that team;
- user memory and skills remain profile-level.

```yaml
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
```

Corporate/team changes are staged as approval requests and applied only after an authorized human approves them in the dashboard Knowledge panel or API. This prevents a model or ordinary user from directly changing tenant-wide operating instructions.

See [Knowledge governance](knowledge-governance.md).

## Folder Policies

Folder policies apply to `read_file`, `search_files`, `write_file`, `patch`, and lower-level file operations. In production, use default deny:

```yaml
governance:
  enabled: true
  default_file_policy: deny
  folder_policies:
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [operator]
    - path: "/srv/company/finance"
      read_roles: [manager]
      write_roles: [manager]
```

Most-specific path wins. Policies are recursive by default; set `recursive: false` for exact-path policies.

## Gateway Threads

The gateway already supports multiple messaging platforms. Governance keeps the corporate defaults explicit:

```yaml
governance:
  gateway:
    group_sessions_per_user: true
    thread_sessions_per_user: false
```

This means normal group/channel conversations are isolated per participant, while explicit threads/topics are shared by all participants in that thread.

## Cron Authorization Nodes

Scheduled jobs can pause before execution:

```python
cronjob(
  action="create",
  name="Finance weekly close",
  prompt="Review the finance folder and prepare a close summary.",
  schedule="0 9 * * MON",
  workdir="/srv/company/finance",
  authorization={"required": True, "roles": ["manager"]},
)
```

When due, the job becomes `awaiting_authorization` and is disabled until an authorized user approves:

```python
cronjob(action="authorize", job_id="abc123")
```

or denies:

```python
cronjob(action="deny", job_id="abc123", reason="Close not ready")
```

Recurring jobs reset the authorization status after each run, so every future run requires a fresh approval.

The dashboard Cron page exposes the same checkpoint: enable the authorization option when creating a job, then approve or deny pending jobs from the scheduled job list.

## Observability

Governance denials and cron authorization requests, approvals, and denials are written to `<HERMES_HOME>/logs/audit.jsonl` when `observability.audit_log_enabled` is true.
Knowledge approval requests, approvals, and denials are also written to the audit trail.

```bash
coorporate logs audit
```

For SIEM export, set `observability.siem_webhook_url` after confirming the collector is approved for governance metadata.

## Controls Mapping

The implementation maps to enterprise AI-agent controls commonly called out in NIST AI RMF, CSA AI Controls Matrix, and Microsoft Entra agent identity guidance:

- identity and access management for agents and human operators;
- least-privilege file access by role and folder;
- separation of corporate, team, and user memory/skill authority;
- human approval for tenant-wide and team-wide knowledge changes;
- human approval for sensitive autonomous workflows;
- auditability through persisted cron authorization metadata;
- auditability through append-only JSONL events;
- session isolation rules for shared gateway conversations.

References:

- https://www.nist.gov/itl/ai-risk-management-framework
- https://cloudsecurityalliance.org/artifacts/ai-controls-matrix
- https://learn.microsoft.com/en-us/entra/agent-id/identity-professional/security-for-ai

Related Coorporate Hermes docs:

- [Admin onboarding](admin-onboarding.md)
- [Migration from upstream Hermes](migration-from-hermes.md)
- [Knowledge governance](knowledge-governance.md)
- [Cron authorization panel](cron-authorization-panel.md)
- [Observability](observability.md)

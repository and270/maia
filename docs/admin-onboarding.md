# Admin Onboarding

Coorporate Hermes is an AmpliIA distribution for private, one-tenant company deployments. The administrator configures the tenant, gateway users, role mapping, folder access, cron approvals, and audit retention before broad rollout.

## 1. Set the Tenant Baseline

Start from default-deny file access in production:

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  default_file_policy: deny
```

Use `viewer` for read-only users, `operator` for normal write work, `manager` for sensitive department approval, and `admin` for platform administrators.

## 2. Add Users and Roles

Gateway users are mapped by `platform:user_id`:

```yaml
governance:
  users:
    "slack:U123":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
    "telegram:987654":
      name: Platform Admin
      roles: [admin]
```

Prefer stable platform IDs over display names. Display names can change and may collide.

`teams` controls which approved team memory and skills are injected for that user. A user can belong to more than one team.

## 3. Configure Knowledge Layers

Coorporate Hermes has corporate, team, and user memory/skill layers:

```yaml
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
```

Corporate memory and skills apply to every conversation. Team memory and skills apply to users assigned to that team. User memory and skills remain profile-level and follow the original Hermes behavior.

Shared corporate/team changes are proposal-first. The agent can stage a memory or skill change, but an authorized human approves it in the dashboard **Knowledge** panel before the file is changed. See [Knowledge governance](knowledge-governance.md).

## 4. Define Folder Policies

Folder policies apply to `read_file`, `search_files`, `write_file`, `patch`, and lower-level file operations.

```yaml
governance:
  folder_policies:
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [operator]
    - path: "/srv/company/finance"
      read_roles: [manager]
      write_roles: [manager]
    - path: "/srv/company/security"
      read_roles: [admin]
      write_roles: [admin]
```

Most-specific path wins. Use `deny_users` for exceptions that must override a role.

## 5. Configure Cron Approvals

Use cron authorization checkpoints for jobs that touch governed folders, send external messages, or produce financial, legal, HR, or security outputs.

```python
cronjob(
  action="create",
  name="Weekly finance package",
  prompt="Review /srv/company/finance and draft the weekly summary.",
  schedule="0 9 * * MON",
  workdir="/srv/company/finance",
  authorization={"required": True, "roles": ["manager"]},
)
```

Admins can also create these jobs from the dashboard Cron page by enabling the authorization checkpoint and entering approver roles or users.

## 6. Enable Observability

The audit trail is enabled by default:

```yaml
observability:
  enabled: true
  audit_log_enabled: true
  audit_log_path: ""
  redact_sensitive_values: true
  siem_webhook_url: ""
  retention_days: 180
```

The default path is `<HERMES_HOME>/logs/audit.jsonl`. Configure `siem_webhook_url` only after validating that the collector is private and authorized for the event data. Knowledge approvals, governance file denials, and cron authorization decisions are audit events.

## 7. Migrate Carefully

Use guarded migration mode for upstream Hermes exports:

```bash
coorporate import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

This stages memories and skills for review, imports MCP servers disabled by default, and preserves the existing Coorporate Hermes governance settings. Promote imported memories or skills into corporate/team layers only through the Knowledge approval flow.

## Launch Checklist

- Governance is enabled.
- `default_file_policy` is `deny` in production.
- Every gateway user who needs access has a stable `platform:user_id` mapping.
- Team users have `governance.users.*.teams` assigned.
- Corporate/team memory and skills have approver roles configured.
- Sensitive folders have explicit read/write policies.
- Cron jobs that cross department or compliance boundaries require approval.
- Audit logs are retained and, if required, exported to a SIEM.
- Migrated skills, secrets, and MCP servers have been reviewed before activation.

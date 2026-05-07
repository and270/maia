---
title: "Admin Onboarding"
description: "Configure Coorporate Hermes tenant governance, users, roles, knowledge layers, folder policies, cron approvals, migration, and audit logging."
---

# Admin Onboarding

Coorporate Hermes is an AmpliIA distribution for private, one-tenant company deployments. The administrator configures tenant identity, gateway users, role mapping, knowledge layers, folder access, cron approvals, and audit retention before broad rollout.

## Baseline

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  default_file_policy: deny
```

Use stable gateway IDs such as `slack:U123` or `telegram:987654`:

```yaml
governance:
  users:
    "slack:U123":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
```

`teams` controls which approved team memory and skills are injected for a user.

## Knowledge Layers

```yaml
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
```

Corporate memory/skills apply to every conversation. Team memory/skills apply by team membership. User memory/skills remain profile-level. Shared corporate/team changes must be approved in the dashboard Knowledge panel before files are changed.

## Folder Access

```yaml
governance:
  folder_policies:
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [operator]
    - path: "/srv/company/finance"
      read_roles: [manager]
      write_roles: [manager]
```

Most-specific path wins. Use `deny_users` for explicit exceptions.

## Cron Approval

```python
cronjob(
  action="create",
  name="Weekly finance package",
  prompt="Review the finance folder and draft the weekly summary.",
  schedule="0 9 * * MON",
  workdir="/srv/company/finance",
  authorization={"required": True, "roles": ["manager"]},
)
```

The dashboard Cron page exposes the same authorization checkpoint fields.

## Observability

```yaml
observability:
  enabled: true
  audit_log_enabled: true
  audit_log_path: ""
  redact_sensitive_values: true
  siem_webhook_url: ""
  retention_days: 180
```

Review audit events with `coorporate logs audit` or the dashboard Logs page. Knowledge approvals, governance denials, and cron authorization decisions are audit events.

## Migration

```bash
coorporate import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

This stages memories and skills for review, imports MCP servers disabled by default, and preserves Coorporate Hermes guardrails. Promote reviewed content into corporate/team layers only through the Knowledge approval flow.

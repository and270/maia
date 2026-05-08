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

Practical flow:

1. Ask the user to DM the bot and run `/whoami`.
2. Copy the returned `platform:user_id` key.
3. Add that key under `governance.users` from the dashboard Config page or reviewed YAML.
4. Assign roles and teams.
5. Keep channel-level bot allowlists enabled where the platform supports them.
6. Ask the user to run `/whoami` again to verify the mapping.
7. If dashboard access is needed, ask them to run `/dashboard` in a private/direct chat.

The channel provider authenticates who sent the message. Coorporate Hermes authorizes that identity through `governance.users`.

## Dashboard Access

The dashboard is a server administration surface for config, secrets, folder policies, cron jobs, and approval decisions. There is one dashboard application; the logged-in identity decides which controls are available. It binds to `127.0.0.1` by default:

```bash
coorporate dashboard
```

Before serving it on an intranet or public host, enable protected mode. Token mode is best for bootstrap and platform-admin access:

```yaml
dashboard:
  auth:
    enabled: true
    token_env: COORPORATE_DASHBOARD_TOKEN
    local_token_roles: [admin]
    read_roles: [auditor, manager, admin]
    manage_roles: [manager, admin]
    admin_roles: [admin]
```

```bash
export COORPORATE_DASHBOARD_TOKEN="$(openssl rand -base64 32)"
coorporate dashboard --host 0.0.0.0 --no-open
```

For SSO, put Coorporate Hermes behind a TLS reverse proxy that strips spoofed headers, set trusted identity headers, and keep the dashboard bound to `127.0.0.1` behind that proxy:

```yaml
dashboard:
  auth:
    enabled: true
    trusted_user_header: X-Auth-Request-User
    trusted_name_header: X-Auth-Request-Name
    trusted_platform: sso
    read_roles: [auditor, manager, admin]
    manage_roles: [manager, admin]
    admin_roles: [admin]

governance:
  users:
    "sso:ana@company.com":
      name: Ana Marketing Lead
      roles: [manager]
      teams: [marketing]
```

System admins see global configuration, secrets, plugin settings, delegated roots, and all file policies. Team leaders usually log in through SSO/trusted headers; they see approval queues allowed by role and can save File Access policies only under delegated team roots. Operators normally use CLI or gateway channels and stay inside the configured policy.

When SSO is not available, authenticated channel users can request one-time dashboard tokens:

```yaml
dashboard:
  auth:
    enabled: true
    channel_tokens:
      enabled: true
      ttl_minutes: 10
      dashboard_url: "https://hermes.company.example"
      require_dm: true
```

The user sends `/dashboard` in a private/direct chat with the bot. Coorporate Hermes checks their channel identity, such as `discord:99887766`, `telegram:987654321`, or `whatsapp:+15551234567`, against `governance.users`. If their roles satisfy `dashboard.auth.read_roles`, the bot returns a short-lived one-time token for the normal dashboard login form.

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

## File Access

Use **Dashboard -> File Access** for normal file authorization. The dashboard saves these settings to `<HERMES_HOME>/config.yaml` under `governance`; the YAML below is the backing shape, not a separate repo file. Direct YAML edits are for the server operator, infrastructure-as-code, backup restore, or break-glass recovery.

System admin workflow:

1. Ask users to run `/whoami` in their channel and copy the exact actor keys.
2. Open **Dashboard -> Config** and map those keys under `governance.users` with roles and teams.
3. Open **File Access**.
4. Set **Default file policy** to `deny`.
5. Add shared folders with **Read roles** / **Write roles** only when the whole tenant should have access.
6. Add department folders with **Read teams** / **Write teams** or named **Read users** / **Write users**.
7. Add **Delegated team roots** when a team leader should manage one bounded folder.
8. Save, test as real mapped users, and review `governance.file_access` audit events.

Team leader workflow:

1. The team leader opens the same dashboard URL and logs in through SSO/trusted headers or a private `/dashboard` channel token.
2. **File Access** shows only delegated roots for teams they manage.
3. They click **Add policy** and set a **Server path** below the delegated root.
4. They use **Read teams** / **Write teams** for the managed team or **Read users** / **Write users** for named users assigned to that team.
5. They keep **Recursive directory policy** on for folders and turn it off for one exact file.
6. They save and ask the affected user to retry.

Team leaders cannot change `default_file_policy`, edit another team's root, grant role-wide rules such as `read_roles: [viewer]`, or reference users outside the managed team unless they also have system-admin dashboard access.

Marketing example:

```yaml
governance:
  enabled: true
  default_file_policy: deny
  users:
    "sso:ana@company.com":
      name: Ana Marketing Lead
      roles: [manager]
      teams: [marketing]
    "sso:bruno@company.com":
      name: Bruno Marketing Analyst
      roles: [operator]
      teams: [marketing]
    "sso:carla@company.com":
      name: Carla Marketing Viewer
      roles: [viewer]
      teams: [marketing]
  team_file_roots:
    marketing:
      path: "/srv/company/marketing"
      manager_roles: [manager]
      managers: ["sso:ana@company.com"]
  folder_policies:
    - path: "/srv/company/marketing"
      read_teams: [marketing]
      write_users: ["sso:ana@company.com"]
    - path: "/srv/company/marketing/campaigns"
      read_teams: [marketing]
      write_teams: [marketing]
    - path: "/srv/company/marketing/brand-guidelines.pdf"
      recursive: false
      read_teams: [marketing]
      write_users: ["sso:ana@company.com"]
    - path: "/srv/company/marketing/private-budget.xlsx"
      recursive: false
      read_users: ["sso:ana@company.com"]
      write_users: ["sso:ana@company.com"]
```

Decision rules:

1. Most-specific path wins.
2. Policies are recursive unless `recursive: false`.
3. `deny_users` and `deny_teams` override grants.
4. Reads/searches require `read_users`, `read_teams`, or `read_roles`.
5. Writes/patches/deletes require `write_users`, `write_teams`, or `write_roles`.
6. If no policy matches and `default_file_policy` is `deny`, access is denied and audited.

| Dashboard field | YAML field | Typical owner |
|---|---|---|
| Default file policy | `default_file_policy` | System admin only. |
| Delegated team roots | `team_file_roots` | System admin only. |
| Server path | `folder_policies[].path` | Admin; team leader below delegated root. |
| Recursive directory policy | `recursive` | Admin or delegated team leader. |
| Read teams / Write teams | `read_teams`, `write_teams` | Admin; team leader for managed team only. |
| Read users / Write users | `read_users`, `write_users` | Admin; team leader for users in managed team only. |
| Deny users / Deny teams | `deny_users`, `deny_teams` | Admin; team leader inside managed team. |
| Read roles / Write roles | `read_roles`, `write_roles` | System admin only. |

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

Review audit events with `coorporate logs audit` or the dashboard Logs page. Knowledge approvals, governance denials, cron authorization decisions, dashboard logins, dashboard denials, and mutating dashboard API calls are audit events.

## Migration

```bash
coorporate import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

This stages memories and skills for review, imports MCP servers disabled by default, and preserves Coorporate Hermes guardrails. Promote reviewed content into corporate/team layers only through the Knowledge approval flow.

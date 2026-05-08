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

## 2. Protect the Dashboard

The dashboard can change config, secrets, server folder policies, cron jobs, and approval decisions. There is one dashboard application; the logged-in identity decides which controls are available. Keep it local during first setup:

```bash
coorporate dashboard
```

For intranet or public access, configure protected mode first. Token mode is best for bootstrap and platform-admin access from the server environment:

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

Use a reverse proxy with TLS for public access. If the proxy performs SSO, configure trusted headers and bind Coorporate Hermes to `127.0.0.1` behind the proxy so clients cannot spoof identity headers:

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

The trusted proxy authenticates the human, strips any inbound `X-Auth-Request-*` headers supplied by clients, and then injects the authenticated user header. Coorporate Hermes turns that into an actor key such as `sso:ana@company.com` and looks it up in `governance.users`.

Dashboard access levels:

- `read_roles` can inspect operational state, logs, sessions, analytics, cron lists, and pending knowledge.
- `manage_roles` can approve or deny cron checkpoints and knowledge approvals, and can save delegated File Access policies when a team root is assigned.
- `admin_roles` can change config, secrets, folder policies, plugin settings, and model settings.

Team leaders normally use SSO/trusted-header login so Coorporate Hermes knows exactly which person is editing a delegated team policy. When SSO is not available, channel-issued dashboard tokens can reuse the identity already authenticated by Discord, Telegram, Slack, WhatsApp, or another gateway platform.

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

The user sends `/dashboard` in a private/direct chat with the bot. Coorporate Hermes checks the actor key, such as `discord:99887766` or `whatsapp:+15551234567`, against `governance.users`. If their roles satisfy `dashboard.auth.read_roles`, the bot replies with a one-time token. The token is hashed on disk, expires quickly, is consumed on first use, and is accepted by the normal dashboard login form. Operators normally use the CLI or gateway channels and do not need dashboard access unless the company grants it.

## 3. Add Users and Roles

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

Practical user onboarding:

1. Ask the user to DM the bot and run `/whoami`.
2. Copy the returned `platform:user_id` key.
3. Add that key under `governance.users` from the dashboard Config page or from reviewed YAML on the server.
4. Assign roles and teams.
5. Keep channel-level bot allowlists enabled where the platform supports them, so only approved accounts can talk to the bot at all.
6. Ask the user to run `/whoami` again to confirm roles and teams.
7. If they need dashboard access, ask them to run `/dashboard` in a private/direct chat.

The platform authenticates the channel account. Coorporate Hermes authorizes what that account can do. These are separate controls: a Discord or WhatsApp sender ID proves who sent the message, while `governance.users` decides whether that sender is a viewer, operator, manager, admin, auditor, or team member.

## 4. Configure Knowledge Layers

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

## 5. Set File Authorization

Use **Dashboard -> File Access** for normal file authorization. The dashboard saves the same data to `<HERMES_HOME>/config.yaml` under `governance`, where `HERMES_HOME` defaults to `~/.hermes` on the server. Direct YAML edits are for the server operator, infrastructure-as-code, backup restore, or break-glass recovery.

File policies are checked before reads, searches, writes, patches, deletes, cron jobs, and dashboard-triggered actions. In production, start with default deny and add only the server folders the assistant should be allowed to touch.

System admin workflow:

1. Ask users to run `/whoami` from Slack, Discord, Telegram, WhatsApp, or the channel they use. Copy the returned actor keys.
2. Open **Dashboard -> Config** and map those keys under `governance.users` with roles and teams.
3. Open **Dashboard -> File Access**.
4. Set **Default file policy** to `deny`.
5. Add shared folders with **Read roles** / **Write roles** only when the whole tenant should have access.
6. Add department folders with **Read teams** / **Write teams** or named **Read users** / **Write users**.
7. Save and test with real users, then review `governance.file_access` audit events.

Example baseline:

```yaml
governance:
  enabled: true
  default_file_policy: deny
  users:
    "slack:U_FINANCE_LEAD":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
    "slack:U_MARKETING_LEAD":
      name: Marketing Lead
      roles: [manager]
      teams: [marketing]
  folder_policies:
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [admin]
    - path: "/srv/company/finance"
      read_teams: [finance]
      write_roles: [manager]
    - path: "/srv/company/security"
      read_roles: [admin]
      write_roles: [admin]
```

## 6. Delegate Team File Administration

Use **Delegated team roots** on the File Access page when a team leader should manage access inside one team folder without becoming a system admin.

System admin setup:

1. In **Config**, make sure the team leader has a `governance.users` entry with the correct team.
2. In **File Access**, add a delegated team root.
3. Fill **Team** with the team id, such as `marketing`.
4. Fill **Server root** with the maximum folder the team leader may manage, such as `/srv/company/marketing`.
5. Fill **Manager roles** with roles allowed to manage that root, usually `manager`.
6. Optionally fill **Manager users** with exact actor keys, such as `sso:ana@company.com`, when only named people should manage the root.

Team leader workflow:

1. The team leader opens the same dashboard URL and logs in through SSO/trusted headers or a private `/dashboard` channel token.
2. **File Access** shows only delegated roots they manage.
3. They click **Add policy** and choose a **Server path** below the delegated root.
4. They use **Read teams** / **Write teams** for the managed team or **Read users** / **Write users** for named users assigned to that team.
5. They keep **Recursive directory policy** on for folders and turn it off for one exact file.
6. They save and ask the affected user to retry the file operation.

Team leaders cannot change `default_file_policy`, edit another team's root, grant role-wide rules such as `read_roles: [viewer]`, or reference users outside the managed team unless they also have system-admin dashboard access.

Marketing example, as saved in `<HERMES_HOME>/config.yaml`:

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
3. `deny_users` and `deny_teams` override broader grants.
4. Reads/searches require `read_users`, `read_teams`, or `read_roles`.
5. Writes/patches/deletes require `write_users`, `write_teams`, or `write_roles`.

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

## 7. Configure Cron Approvals

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

## 8. Enable Observability

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

The default path is `<HERMES_HOME>/logs/audit.jsonl`. Configure `siem_webhook_url` only after validating that the collector is private and authorized for the event data. Knowledge approvals, governance file denials, cron authorization decisions, dashboard logins, dashboard denials, and mutating dashboard API calls are audit events.

## 9. Migrate Carefully

Use guarded migration mode for upstream Hermes exports:

```bash
coorporate import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

This stages memories and skills for review, imports MCP servers disabled by default, and preserves the existing Coorporate Hermes governance settings. Promote imported memories or skills into corporate/team layers only through the Knowledge approval flow.

## Launch Checklist

- Governance is enabled.
- Dashboard protected mode is enabled before binding to any non-loopback interface.
- Dashboard channel tokens have a real intranet/public `dashboard_url` or are disabled.
- `default_file_policy` is `deny` in production.
- Every gateway user who needs access has a stable `platform:user_id` mapping.
- Users can run `/whoami` to verify their mapped identity, roles, and teams.
- Team users have `governance.users.*.teams` assigned.
- Corporate/team memory and skills have approver roles configured.
- Sensitive folders have explicit read/write policies.
- Team roots are delegated only to the correct team leaders.
- Cron jobs that cross department or compliance boundaries require approval.
- Audit logs are retained and, if required, exported to a SIEM.
- Migrated skills, secrets, and MCP servers have been reviewed before activation.

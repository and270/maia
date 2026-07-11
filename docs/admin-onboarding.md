# Admin Onboarding

Maia is an AmpliIA distribution for private, one-tenant company deployments. The administrator configures the tenant, gateway users, role mapping, folder access, cron approvals, and audit retention before broad rollout.

## 1. Set the Tenant Baseline

Start from default-deny file access in production:

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  teams: {}
```

Use `viewer` for read-only users, `operator` for normal write work, `manager` for sensitive department approval, and `admin` for platform administrators.

## 2. Protect the Dashboard

The dashboard can change config, secrets, server folder policies, cron jobs, and approval decisions. There is one dashboard application; the logged-in identity decides which controls are available. Keep it local during first setup:

```bash
maia dashboard
```

For intranet or public access, configure protected mode first. Token mode is best for bootstrap and platform-admin access from the server environment:

```yaml
dashboard:
  auth:
    enabled: true
    token_env: MAIA_DASHBOARD_TOKEN
    local_token_roles: [admin]
    read_roles: [auditor, manager, admin]
    manage_roles: [manager, admin]
    admin_roles: [admin]
```

```bash
export MAIA_DASHBOARD_TOKEN="$(openssl rand -base64 32)"
maia dashboard --host 0.0.0.0 --no-open
```

Default built-in flow for team leaders:

1. Configure a gateway the team leader already uses, such as Slack, Discord, Telegram, or WhatsApp.
2. Enable dashboard protected mode and `dashboard.auth.channel_tokens`.
3. Set `dashboard.auth.channel_tokens.dashboard_url` to the URL the user will open.
4. Keep `dashboard.auth.channel_tokens.approval_required: true`.
5. Ask the team leader to send `/dashboard` in a private/direct chat with the bot.
6. Maia creates a pending request in **Dashboard Access**.
7. Open **Dashboard Access**, review the actor key, assign roles and teams, then approve or deny the request.
8. If the team leader should manage files, add a delegated `team_file_roots` entry in **File Access**.
9. Ask the team leader to send `/dashboard` again.
10. They paste the one-time token into the dashboard login form.

```yaml
dashboard:
  auth:
    enabled: true
    read_roles: [auditor, manager, admin]
    manage_roles: [manager, admin]
    admin_roles: [admin]
    channel_tokens:
      enabled: true
      ttl_minutes: 10
      dashboard_url: "https://maia.company.example"
      require_dm: true
      approval_required: true

governance:
  users:
    "discord:99887766":
      name: Ana Marketing Lead
      roles: [manager]
      teams: [marketing]
  team_file_roots:
    marketing:
      path: "/srv/company/marketing"
      manager_roles: [manager]
      managers: ["discord:99887766"]
```

The first `/dashboard` message is an access request, not a token issuance. It is available only after the actor key, such as `discord:99887766` or `whatsapp:+15551234567`, already has a Governance role. Approval in **Dashboard Access** authorizes dashboard login and may update that existing user record. The second `/dashboard` message issues the short-lived one-time token only if the request is approved, the actor is not revoked, and the current roles satisfy `dashboard.auth.read_roles`. The token is hashed on disk, expires quickly, is consumed on first use, and is accepted by the normal dashboard login form.

Revocation is also in **Dashboard Access**. Click **Revoke** beside an approved actor or enter an actor key manually. Revocation blocks future token issuance, removes unused channel tokens, and drops active dashboard sessions for that actor. Click **Restore** if access should be allowed again.

Maia does not provide SSO, VPN, zero-trust networking, or a reverse proxy. If the company already operates that infrastructure, Maia can integrate with it through trusted headers. For public access, use a company-managed TLS reverse proxy or private network boundary. If that proxy performs SSO, configure trusted headers and bind Maia to `127.0.0.1` behind the proxy so clients cannot spoof identity headers:

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

The external proxy authenticates the human, strips any inbound `X-Auth-Request-*` headers supplied by clients, and then injects the authenticated user header. Maia turns that into an actor key such as `sso:ana@company.com` and looks it up in `governance.users`.

Dashboard access levels:

- `read_roles` can inspect operational state, logs, sessions, analytics, cron lists, and pending knowledge.
- `manage_roles` can approve or deny cron checkpoints and knowledge approvals, and can save delegated File Access policies when a team root is assigned.
- `admin_roles` can change config, secrets, folder policies, plugin settings, and model settings.

Operators normally use the CLI or gateway channels and do not need dashboard access unless the company grants it.

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

1. Add the stable platform ID to the channel allowlist in **Gateway**.
2. Add the same `platform:user_id` under `governance.users` in **Config / Governance**, with at least one role and any team assignments. Allowlisting, role-based channel admission, pairing, and allow-all flags never create this record.
3. Start or restart the gateway. The user can now talk to Maia and run `/whoami` to verify the mapping.
4. If the user also needs the admin dashboard, ask them to run `/dashboard` in a private chat.
5. Open **Dashboard Access**, review the now-governed user's request, and approve or deny dashboard login.
6. Ask the user to run `/dashboard` again to receive the one-time dashboard login token.

On a completely fresh installation, the Gateway editor bootstraps only the first saved user as `admin`. Every later allowlisted user is shown as **Pending Governance** and remains unable to use the bot until step 2 is complete.

The platform authenticates the channel account. Maia authorizes what that account can do. These are separate controls: a Discord or WhatsApp sender ID proves who sent the message, while the approved Dashboard Access record and `governance.users` decide whether that sender is a viewer, operator, manager, admin, auditor, or team member.

## 4. Configure Knowledge Layers

Maia has corporate, team, and user memory/skill layers:

```yaml
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
```

Corporate memory and skills apply to every conversation. Team memory and skills apply to users assigned to that team. Each human gateway identity gets isolated personal memory and skills under an opaque `<MAIA_HOME>/users/<platform-hash>/` directory; CLI/local sessions retain the legacy profile-wide paths.

Shared corporate/team changes are proposal-first. The agent can stage a memory or skill change, but an authorized human approves it in the dashboard **Knowledge** panel before the file is changed. See [Knowledge governance](knowledge-governance.md).

## 5. Set File Authorization

Use **Dashboard -> File Access** for normal file authorization. The dashboard saves the same data to `<MAIA_HOME>/config.yaml` under `governance`, where `MAIA_HOME` defaults to `~/.maia` on the server. Direct YAML edits are for the server operator, infrastructure-as-code, backup restore, or break-glass recovery.

File policies are checked before reads, searches, writes, patches, deletes, cron jobs, and dashboard-triggered actions. Unmatched paths are always denied; add only the server folders the assistant should be allowed to touch.

System admin workflow:

1. Ask users who need dashboard or delegated file administration to run `/dashboard` from Slack, Discord, Telegram, WhatsApp, or the channel they use.
2. Create teams under **Governance → Teams**, then add each actor under **People** with roles and select-only team membership.
3. Use **People** for individual paths and **Teams** for team paths and delegated roots.
4. Open **File Access** for advanced role, deny, and write-approval rules.
5. Save and test with real users, then review `governance.file_access` audit events.

Example baseline:

```yaml
governance:
  enabled: true
  teams:
    finance: {}
    marketing: {}
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

1. In **Dashboard Access**, approve the team leader with the correct role and team.
2. In **File Access**, add a delegated team root.
3. Fill **Team** with the team id, such as `marketing`.
4. Fill **Server root** with the maximum folder the team leader may manage, such as `/srv/company/marketing`.
5. Fill **Manager roles** with roles allowed to manage that root, usually `manager`.
6. Optionally fill **Manager users** with exact actor keys, such as `sso:ana@company.com`, when only named people should manage the root.

Team leader workflow:

1. The team leader sends `/dashboard` in a private channel. If already approved, the bot returns a one-time token for the dashboard login form.
2. **File Access** shows only delegated roots they manage.
3. They click **Add policy** and choose a **Server path** below the delegated root.
4. They use **Read teams** / **Write teams** for the managed team or **Read users** / **Write users** for named users assigned to that team.
5. They keep **Recursive directory policy** on for folders and turn it off for one exact file.
6. They save and ask the affected user to retry the file operation.

Team leaders cannot edit another team's root, grant role-wide rules such as `read_roles: [viewer]`, or reference users outside the managed team unless they also have system-admin dashboard access.

Marketing example, as saved in `<MAIA_HOME>/config.yaml`:

```yaml
governance:
  enabled: true
  teams:
    marketing: {}
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
| Team registry | `teams` | System admin only. |
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

The default path is `<MAIA_HOME>/logs/audit.jsonl`. Configure `siem_webhook_url` only after validating that the collector is private and authorized for the event data. Knowledge approvals, governance file denials, cron authorization decisions, dashboard logins, dashboard denials, and mutating dashboard API calls are audit events.

## 9. Migrate Carefully

Use guarded migration mode for upstream Hermes exports:

```bash
maia import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

This stages memories and skills for review, imports MCP servers disabled by default, and preserves the existing Maia governance settings. Promote imported memories or skills into corporate/team layers only through the Knowledge approval flow.

## Launch Checklist

- Governance is enabled.
- Dashboard protected mode is enabled before binding to any non-loopback interface.
- Dashboard channel tokens have a real intranet/public `dashboard_url`, `require_dm: true`, and approval required.
- Unmatched paths are always denied and every allowed operation has an explicit grant.
- Every dashboard user was approved through **Dashboard Access** or reviewed YAML.
- Users can run `/whoami` to verify their mapped identity, roles, and teams.
- Team users have `governance.users.*.teams` assigned.
- Corporate/team memory and skills have approver roles configured.
- Sensitive folders have explicit read/write policies.
- Team roots are delegated only to the correct team leaders.
- Cron jobs that cross department or compliance boundaries require approval.
- Audit logs are retained and, if required, exported to a SIEM.
- Migrated skills, secrets, and MCP servers have been reviewed before activation.

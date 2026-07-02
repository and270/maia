---
title: "Enterprise Governance"
description: "Identity, roles, dashboard access, folder policies, gateway isolation, cron approval checkpoints, and audit controls."
---

# Enterprise Governance

Maia adds a governance layer for private one-tenant deployments. The policy lives in `<MAIA_HOME>/config.yaml` (`~/.maia/config.yaml` by default). Normal administration happens through the protected dashboard; direct YAML edits are for server operators, reviewed deployment automation, backup restore, or break-glass recovery.

Most employees do not need the dashboard. They interact with Maia through a messaging gateway such as Discord, Slack, Mattermost, Matrix, WhatsApp, or Telegram. The dashboard is the admin surface for configuring the deployment, approving dashboard access, assigning governance roles, reviewing logs, and managing policies; protect it like any other admin console.

## Identity and Roles

Gateway users are identified by stable `platform:user_id` keys. Gateway allowlists such as `DISCORD_ALLOWED_USERS` decide who may talk to the bot; `governance.users` decides the Maia roles, teams, and policy behavior attached to that identity. Adding a Discord ID to the gateway allowlist does not automatically make that person a dashboard admin.

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U123456":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
```

Roles drive authorization. Teams drive approved team memory and skill injection.

The normal dashboard path does not require manually copying `/whoami` output into YAML. A user sends `/dashboard` in a private/direct chat, Maia records the exact actor key in **Dashboard Access**, and a system admin approves the request with roles and teams. `/whoami` is still useful for troubleshooting because it shows the channel identity and current mapping.

## Dashboard Access

The dashboard can change config, secrets, server folder policies, cron jobs, approval decisions, plugins, and model settings. It binds to localhost by default:

```bash
maia dashboard
```

For intranet or public serving, configure protected mode first. Maia refuses non-loopback binding without dashboard auth unless `--insecure` is explicitly used.

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

1. The team leader sends `/dashboard` in a private/direct gateway chat.
2. Maia creates a pending request in **Dashboard Access**.
3. A system admin opens **Dashboard Access**, reviews the actor key, assigns roles and teams, and approves or denies the request.
4. On approval, Maia writes the actor under `governance.users`.
5. The team leader sends `/dashboard` again to receive a short-lived one-time dashboard token.
6. The admin can revoke or restore that dashboard access from the same page.

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

Maia does not provide SSO, VPN, zero-trust networking, or an identity-aware proxy. If the company already operates that access layer, Maia can sit behind it and consume trusted headers from it:

```yaml
dashboard:
  auth:
    enabled: true
    trusted_user_header: X-Auth-Request-User
    trusted_name_header: X-Auth-Request-Name
    trusted_platform: sso
```

Use `trusted_user_header` only behind a TLS reverse proxy or SSO layer that strips spoofed client headers. Prefer binding Maia to `127.0.0.1` behind that proxy.

There is one dashboard application. A system admin sees global config, secrets, plugins, all folder policies, delegated roots, approvals, and audit evidence. A team leader sees only the approval surfaces allowed by role and the File Access roots delegated to their team. Operators normally work through CLI or gateway channels inside the same server-side policy.

### Channel-issued dashboard tokens

The built-in channel-token flow uses the authenticated gateway identity:

```yaml
dashboard:
  auth:
    enabled: true
    channel_tokens:
      enabled: true
      ttl_minutes: 10
      dashboard_url: "https://maia.company.example"
      require_dm: true
      approval_required: true
```

First `/dashboard` request:

1. If the actor is not approved, Maia creates a pending **Dashboard Access** request.
2. The bot tells the user the request is pending.
3. A system admin reviews the request, assigns roles and teams, and approves or denies it.

After approval:

1. The user sends `/dashboard` again.
2. Maia checks that access is approved, not revoked, and that roles satisfy `dashboard.auth.read_roles`.
3. The bot sends a one-time token for the dashboard login form.
4. The token is short-lived, consumed on first use, stored hashed on disk, and audited when audit logging is enabled.

## File Authorization By Team And User

Use **Dashboard -> File Access** for normal file authorization. The dashboard writes the same values to `<MAIA_HOME>/config.yaml` on the server under `governance`; this YAML is not a separate repo file. Direct YAML edits are for server operators, reviewed infrastructure-as-code, backup restore, or break-glass recovery.

Before creating policies:

1. Ask users who need dashboard or delegated file administration to run `/dashboard` in a private channel chat.
2. Approve those requests in **Dashboard Access** with the right roles and teams.
3. Keep `governance.default_file_policy: deny` in production.
4. Open **File Access** and save policies from the dashboard.

System admins can change the global default, shared folders, sensitive folders, role-wide grants, and delegated team roots. Team leaders use the same page after approved `/dashboard` access and a private channel token, or trusted-header login from an existing company identity layer, but they see only the team roots delegated to them.

System admin workflow:

1. Open **File Access** as a role allowed by `dashboard.auth.admin_roles`.
2. Set **Default file policy** to `deny`.
3. Add shared folders only when the whole tenant should access them.
4. Add department folders using **Read teams** / **Write teams** or named **Read users** / **Write users**.
5. Add a **Delegated team root** when a team leader should manage one bounded folder.
6. Save and review `governance.file_access` audit events for denied attempts.

Team leader workflow:

1. Send `/dashboard` in a private channel. If access is not approved yet, a system admin approves the pending request in **Dashboard Access** first.
2. Confirm **File Access** shows the expected managed team badge and root.
3. Click **Add policy** and set a **Server path** under the delegated root.
4. Use **Read teams** / **Write teams** for the managed team or **Read users** / **Write users** for named users assigned to that team.
5. Leave **Recursive directory policy** on for folders; turn it off for one exact file.
6. Save and ask the affected user to retry.

Team leaders cannot change the global default, edit another team's root, grant role-wide rules such as `read_roles: [viewer]`, or reference users outside the managed team unless they also have system-admin dashboard access.

Practical marketing example, as saved in `<MAIA_HOME>/config.yaml`:

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
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [admin]
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

| Dashboard field | YAML field | Who can normally set it |
|---|---|---|
| Default file policy | `default_file_policy` | System admin only. |
| Delegated team roots | `team_file_roots` | System admin only. |
| Server path | `folder_policies[].path` | Admin; team leader below delegated root. |
| Recursive directory policy | `recursive` | Admin or delegated team leader. |
| Read teams / Write teams | `read_teams`, `write_teams` | Admin; team leader for managed team only. |
| Read users / Write users | `read_users`, `write_users` | Admin; team leader for users assigned to managed team only. |
| Deny users / Deny teams | `deny_users`, `deny_teams` | Admin; team leader inside managed team. |
| Read roles / Write roles | `read_roles`, `write_roles` | System admin only. |

## Knowledge Authority

Corporate memory/skills apply to every conversation. Team memory/skills apply by `governance.users.*.teams`. User memory/skills remain profile-level. Corporate and team edits are staged for approval and applied only by an authorized human in the dashboard Knowledge panel or API.

## Cron Authorization

Sensitive scheduled jobs can pause before execution:

```python
cronjob(
  action="create",
  name="Finance weekly close",
  prompt="Review /srv/company/finance and prepare a close summary.",
  schedule="0 9 * * MON",
  authorization={"required": True, "roles": ["manager"]},
)
```

When due, the job enters `awaiting_authorization` until an allowed user or role approves it from the dashboard Cron page or the cron tool/API.

## Audit Trail

Audit events are written to `<MAIA_HOME>/logs/audit.jsonl` when observability audit logging is enabled. Coverage includes governance file denials, knowledge approval requests/decisions, cron authorization requests/decisions, dashboard access requests/approvals/revocations, dashboard login/logout, dashboard authorization denials, and mutating dashboard API calls.

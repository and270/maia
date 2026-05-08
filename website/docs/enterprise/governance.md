---
title: "Enterprise Governance"
description: "Identity, roles, dashboard access, folder policies, gateway isolation, cron approval checkpoints, and audit controls."
---

# Enterprise Governance

Coorporate Hermes adds a governance layer for private one-tenant deployments. The policy lives in `<HERMES_HOME>/config.yaml` (`~/.hermes/config.yaml` by default). Normal administration happens through the protected dashboard; direct YAML edits are for server operators, reviewed deployment automation, backup restore, or break-glass recovery.

## Identity and Roles

Gateway users are identified by stable `platform:user_id` keys:

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

Ask a user to DM the bot and run `/whoami` to discover the exact key Coorporate Hermes sees, such as `discord:99887766`, `telegram:987654321`, or `whatsapp:+15551234567`. The messaging platform authenticates the sender account; Coorporate Hermes authorizes that sender by looking up the key in `governance.users`.

## Dashboard Access

The dashboard can change config, secrets, server folder policies, cron jobs, approval decisions, plugins, and model settings. It binds to localhost by default:

```bash
coorporate dashboard
```

For intranet or public serving, configure protected mode first. Coorporate Hermes refuses non-loopback binding without dashboard auth unless `--insecure` is explicitly used.

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

Use `trusted_user_header` only behind a TLS reverse proxy or SSO layer that strips spoofed client headers. Prefer binding Coorporate Hermes to `127.0.0.1` behind that proxy.

Token mode is mainly for bootstrap and platform-admin access. Team leaders should normally log in through SSO/trusted headers so Coorporate Hermes knows which human is changing a delegated policy:

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

There is one dashboard application. A system admin sees global config, secrets, plugins, all folder policies, delegated roots, approvals, and audit evidence. A team leader sees only the approval surfaces allowed by role and the File Access roots delegated to their team. Operators normally work through CLI or gateway channels inside the same server-side policy.

### Channel-issued dashboard tokens

When SSO is unavailable, a mapped channel user can request dashboard access from the same authenticated channel identity:

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

The user runs `/dashboard` in a private/direct chat. Coorporate Hermes checks their `platform:user_id` against `governance.users`, requires a role allowed by `dashboard.auth.read_roles`, and sends a one-time token for the dashboard login form. The token is short-lived, consumed on first use, stored hashed on disk, and audited when audit logging is enabled.

## File Authorization By Team And User

Use **Dashboard -> File Access** for normal file authorization. The dashboard writes the same values to `<HERMES_HOME>/config.yaml` on the server under `governance`; this YAML is not a separate repo file. Direct YAML edits are for server operators, reviewed infrastructure-as-code, backup restore, or break-glass recovery.

Before creating policies:

1. Ask users to run `/whoami` in their channel so you have exact actor keys like `discord:99887766`, `slack:U123456`, or `whatsapp:+15551234567`.
2. Map those keys in **Dashboard -> Config** under `governance.users` with roles and teams.
3. Keep `governance.default_file_policy: deny` in production.
4. Open **File Access** and save policies from the dashboard.

System admins can change the global default, shared folders, sensitive folders, role-wide grants, and delegated team roots. Team leaders use the same page after SSO/trusted-header login or a private `/dashboard` token, but they see only the team roots delegated to them.

System admin workflow:

1. Open **File Access** as a role allowed by `dashboard.auth.admin_roles`.
2. Set **Default file policy** to `deny`.
3. Add shared folders only when the whole tenant should access them.
4. Add department folders using **Read teams** / **Write teams** or named **Read users** / **Write users**.
5. Add a **Delegated team root** when a team leader should manage one bounded folder.
6. Save and review `governance.file_access` audit events for denied attempts.

Team leader workflow:

1. Open the same dashboard URL.
2. Confirm **File Access** shows the expected managed team badge and root.
3. Click **Add policy** and set a **Server path** under the delegated root.
4. Use **Read teams** / **Write teams** for the managed team or **Read users** / **Write users** for named users assigned to that team.
5. Leave **Recursive directory policy** on for folders; turn it off for one exact file.
6. Save and ask the affected user to retry.

Team leaders cannot change the global default, edit another team's root, grant role-wide rules such as `read_roles: [viewer]`, or reference users outside the managed team unless they also have system-admin dashboard access.

Practical marketing example, as saved in `<HERMES_HOME>/config.yaml`:

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

Audit events are written to `<HERMES_HOME>/logs/audit.jsonl` when observability audit logging is enabled. Coverage includes governance file denials, knowledge approval requests/decisions, cron authorization requests/decisions, dashboard login/logout, dashboard authorization denials, and mutating dashboard API calls.

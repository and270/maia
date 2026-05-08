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

## Folder Policies

Folder policies are the maximum server filesystem access any channel user, cron job, or dashboard-triggered action can receive.

Use dashboard **File Access** for normal setup:

1. A system admin logs in with a role allowed by `dashboard.auth.admin_roles`.
2. The admin sets `governance.default_file_policy: deny`.
3. The admin adds shared company roots and sensitive department roots.
4. The admin defines `team_file_roots` for team leaders who should manage their own area.
5. Team leaders log into the same dashboard through SSO/trusted headers and can edit only policies under their delegated roots.

```yaml
governance:
  enabled: true
  default_file_policy: deny
  team_file_roots:
    marketing:
      path: "/srv/company/marketing"
      manager_roles: [manager]
      managers: ["slack:U123456"]
  folder_policies:
    - path: "/srv/company"
      read_roles: [viewer]
      write_roles: [operator]
    - path: "/srv/company/finance"
      read_teams: [finance]
      write_roles: [manager]
    - path: "/srv/company/security"
      read_users: ["slack:U999"]
      write_roles: [admin]
      deny_users: ["discord:111222333"]
    - path: "/srv/company/marketing/brand-guidelines.pdf"
      recursive: false
      read_teams: [marketing]
      write_users: ["slack:U123456"]
```

Most-specific path wins. Policies are recursive by default; set `recursive: false` for exact-path policies. `deny_users` and `deny_teams` override broader grants. OS filesystem permissions still apply and should limit the Coorporate Hermes service account.

System admins use dashboard **File Access** or direct YAML to set the global baseline and team roots. Team leaders use the same dashboard page after login, but can edit only policies under their delegated team root. A marketing lead can grant read-only or write access for marketing team members under `/srv/company/marketing`; they cannot edit finance folders, change the global default, grant role-wide access, or reference users outside the managed team unless they also have system-admin dashboard access.

Practical marketing example:

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

| Field | Meaning | Who can normally set it |
|---|---|---|
| `path` | Absolute server folder or file path. | Admin; team leader below delegated root. |
| `recursive` | `true` for folders, `false` for one exact file. | Admin or delegated team leader. |
| `read_teams`, `write_teams` | Grants to users assigned to a team. | Admin; team leader for managed team only. |
| `read_users`, `write_users` | Grants to named actor keys such as `sso:ana@company.com` or `slack:U123`. | Admin; team leader for users assigned to managed team only. |
| `deny_users`, `deny_teams` | Explicit block that overrides broader grants. | Admin or delegated team leader. |
| `read_roles`, `write_roles` | Broad tenant-wide grants by role. | System admin only. |
| `team_file_roots` | Delegated roots that decide what a team leader can manage. | System admin only. |

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

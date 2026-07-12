---
title: "Admin Onboarding"
description: "Configure Maia tenant governance, users, roles, knowledge layers, folder policies, cron approvals, migration, and audit logging."
---

# Admin Onboarding

Maia is an AmpliIA distribution for private, one-tenant company deployments. The administrator configures tenant identity, gateway users, role mapping, knowledge layers, folder access, cron approvals, and audit retention before broad rollout.

## Baseline

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  teams: {}
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

1. Add the stable platform ID to the channel allowlist in **Gateway**.
2. Add the same `platform:user_id` under `governance.users` in **Config / Governance**, with at least one role and any teams. Pairing and allow-all flags do not replace this step.
3. Start or restart the gateway, then ask the user to run `/whoami` to verify the mapping.
4. If dashboard access is needed, ask the now-governed user to run `/dashboard` in a private chat.
5. Review that login request in **Dashboard Access**, then approve or deny it.
6. Ask the user to run `/dashboard` again to receive the one-time dashboard login token.

On a fresh installation only the first user saved in Gateway is bootstrapped as `admin`. Later allowlisted users show **Pending Governance** and cannot talk to Maia until step 2 is complete.

The channel provider authenticates who sent the message. Maia requires both gateway admission and an explicit `governance.users` role before that human identity can reach the bot.

## Dashboard Access

The dashboard is a server administration surface for config, secrets, folder policies, cron jobs, and approval decisions. There is one dashboard application; the logged-in identity decides which controls are available. It binds to `127.0.0.1` by default:

```bash
maia dashboard
```

Before serving it on an intranet or public host, enable protected mode. Token mode is best for bootstrap and platform-admin access:

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

1. Enable `dashboard.auth.channel_tokens`.
2. Set `dashboard.auth.channel_tokens.dashboard_url` to the URL the user will open.
3. Keep `dashboard.auth.channel_tokens.approval_required: true`.
4. Ask the team leader to send `/dashboard` in a private/direct chat.
5. Maia creates a pending request in **Dashboard Access**.
6. Open **Dashboard Access**, review the actor key, assign roles and teams, then approve or deny the request.
7. If the team leader should manage files, add a delegated root under **Governance → Teams**.
8. Ask the team leader to send `/dashboard` again.
9. They paste the one-time token into the dashboard login form.

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

The first `/dashboard` message is an access request, not a token issuance, and it is available only after the actor already has a Governance role. Approval in **Dashboard Access** authorizes dashboard login and may update that existing user record. The second `/dashboard` message issues a short-lived one-time token only if the request is approved, the actor is not revoked, and current roles satisfy `dashboard.auth.read_roles`.

Revocation is also in **Dashboard Access**. Click **Revoke** beside an approved actor or enter an actor key manually. Revocation blocks future token issuance, removes unused channel tokens, and drops active dashboard sessions for that actor. Click **Restore** if access should be allowed again.

Maia does not provide SSO, VPN, zero-trust networking, or an identity-aware proxy. If the company already has that layer and chooses this optional integration, Maia can consume trusted identity headers from it. The external TLS reverse proxy must strip spoofed headers, set trusted identity headers, and be the only network path to the dashboard:

```yaml
dashboard:
  auth:
    enabled: true
    trusted_user_header: X-Auth-Request-User
    trusted_name_header: X-Auth-Request-Name
    trusted_platform: sso
```

System admins see global configuration, secrets, plugin settings, delegated roots, and all file policies. Team leaders see approval queues allowed by role and can save File Access policies only under delegated team roots. Operators normally use CLI or gateway channels and stay inside the configured policy.

## Knowledge Layers

```yaml
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
```

Corporate memory/skills apply to every conversation. Team memory/skills apply by team membership. Each human gateway identity has isolated personal memory and skills under an opaque `<MAIA_HOME>/users/<platform-hash>/` path; local CLI sessions retain profile-level compatibility. Shared corporate/team changes must be approved in the dashboard Knowledge panel before files are changed.

## File Access

Use **Dashboard -> File Access** for normal file authorization. The dashboard saves these settings to `<MAIA_HOME>/config.yaml` under `governance`; the YAML below is the backing shape, not a separate repo file. Direct YAML edits are for the server operator, infrastructure-as-code, backup restore, or break-glass recovery.

The Governance tabs are **People → Teams → File access → Approvals → Settings**. Governance cannot be disabled: a role admits the identity to Maia but grants no files. Unmatched paths are always denied; there is no global allow switch. Gateway shell and code execution are also isolated to the explicitly granted paths and fail closed if the Docker sandbox is unavailable.

System admin workflow:

1. Ask users who need dashboard or delegated file administration to run `/dashboard` in a private channel.
2. Create required teams in **Governance → Teams**.
3. Open **Dashboard Access** and approve each request with the right roles and registered teams.
4. Use **People** for individual paths and **Teams** for team paths and delegated roots.
5. Open **File Access** for advanced role, deny, and write-approval rules.
8. Save, test as real approved users, and review `governance.file_access` audit events.

Team leader workflow:

1. The team leader sends `/dashboard` in a private channel. If already approved, the bot returns a one-time token for the dashboard login form.
2. **File Access** shows only delegated roots for teams they manage.
3. They click **Add policy** and set a **Server path** below the delegated root.
4. They use **Read teams** / **Write teams** for the managed team or **Read users** / **Write users** for named users assigned to that team.
5. They keep **Recursive directory policy** on for folders and turn it off for one exact file.
6. They save and ask the affected user to retry.

Team leaders cannot edit another team's root, grant role-wide rules such as `read_roles: [viewer]`, or reference users outside the managed team unless they also have system-admin dashboard access.

Marketing example:

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
3. `deny_users` and `deny_teams` override grants.
4. Reads/searches require `read_users`, `read_teams`, or `read_roles`.
5. Writes/patches/deletes require `write_users`, `write_teams`, or `write_roles`.
6. If no policy matches, access is denied and audited.
7. A matching policy without an applicable read/write grant is also denied.

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

Review audit events with `maia logs audit` or the dashboard Logs page. Knowledge approvals, governance denials, cron authorization decisions, dashboard logins, dashboard denials, and mutating dashboard API calls are audit events.

## Migration

```bash
maia import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

This stages memories and skills for review, imports MCP servers disabled by default, and preserves Maia guardrails. Promote reviewed content into corporate/team layers only through the Knowledge approval flow.

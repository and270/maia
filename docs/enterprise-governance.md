# Enterprise Governance

Coorporate Hermes is an AmpliIA distribution that adds a governance layer for private one-tenant company deployments. It is intentionally configuration-driven so the same assistant can be used by different departments without hardcoding people or folder paths.

## Identity

Gateway users are identified by `platform:user_id`, for example:

- `slack:U123456`
- `discord:99887766`
- `telegram:987654321`
- `whatsapp:+15551234567`

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

The easiest way to discover a user's exact key is to ask them to message the bot and run:

```text
/whoami
```

The command returns the channel identity, current governance roles, and current teams. A system admin copies that `platform:user_id` key into `governance.users`. Channel identity and Coorporate Hermes authorization are separate: Discord, Telegram, Slack, WhatsApp, or another provider authenticates the sender account; Coorporate Hermes maps that sender to company roles and teams.

## Dashboard Access

The dashboard is a server administration surface. It can read and change `config.yaml`, `.env`, governed folder policies, cron jobs, knowledge approvals, and plugin settings.

By default it binds only to `127.0.0.1`:

```bash
coorporate dashboard
```

For intranet or public access, enable `dashboard.auth` before binding to a non-loopback interface. Coorporate Hermes refuses network binding unless protected mode is configured, unless the operator explicitly uses `--insecure` for temporary trusted-network testing.

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

Dashboard login uses one of two patterns:

- `local_token`: the server operator sets `COORPORATE_DASHBOARD_TOKEN` or `dashboard.auth.token_hash`; a successful login receives `dashboard.auth.local_token_roles`.
- `trusted_header`: a reverse proxy or SSO layer authenticates the user and passes a configured identity header such as `X-Auth-Request-User`. Use this only behind a proxy that strips spoofed client headers. Prefer binding Coorporate Hermes to `127.0.0.1` behind that proxy.

Token mode is mainly for bootstrap and platform-admin access. It does not identify individual team leaders unless a deployment creates separate protected entrypoints. For normal team-leader access, use trusted-header/SSO mode and map identities under `governance.users`:

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

There is one dashboard application. The logged-in actor determines the available controls:

| Actor | How they normally log in | What they can do |
|---|---|---|
| System admin | Local admin token or SSO identity with `admin` role. | Global config, secrets, plugins, model settings, all folder policies, delegated roots, approvals, and audit review. |
| Team leader | SSO/trusted-header identity mapped to `manager` and a team. | Approval queues allowed by role, and File Access only under delegated team roots. |
| Operator | Usually CLI or gateway channel identity, not dashboard. | Agent work within configured tool, folder, memory, and cron policy. |
| Auditor | SSO/trusted-header identity mapped to `auditor`. | Read operational evidence without changing execution policy. |

Dashboard role gates are intentionally coarse:

| Gate | Typical pages | Default roles |
|---|---|---|
| Read | sessions, logs, analytics, cron list, knowledge review | `auditor`, `manager`, `admin` |
| Manage | cron authorization decisions, team/corporate approval decisions, and delegated File Access updates | `manager`, `admin` |
| Admin | config, secrets, folder policies, plugin install/remove, model settings | `admin` |

All mutating dashboard API calls are written to the audit trail as `dashboard.api_action` when observability audit logging is enabled. Login, logout, and denied role checks are recorded as dashboard auth/authorization events.

### Channel-issued dashboard tokens

If the company does not have SSO in front of the dashboard, Coorporate Hermes can let authenticated channel users request a one-time dashboard token:

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

The user runs `/dashboard` in a private/direct chat with the bot. The gateway already knows the sender as `discord:99887766`, `telegram:987654321`, `whatsapp:+15551234567`, and so on. Coorporate Hermes checks that actor against `governance.users` and only issues a token when the actor satisfies `dashboard.auth.read_roles`. The dashboard login form accepts the token, creates a normal dashboard session for that actor, and then applies the same read/manage/admin gates.

Operational rules:

- Keep `require_dm: true` unless the platform can guarantee private ephemeral replies.
- Set `dashboard_url` to the real intranet, VPN, or protected public dashboard URL; `127.0.0.1` is useful only on the server.
- Tokens are one-time, short-lived, and stored hashed under `<HERMES_HOME>/dashboard/channel_login_tokens.json`.
- Token issuance and dashboard login are audit events when audit logging is enabled.
- Removing or downgrading a user in `governance.users` prevents future token issuance and prevents an unused token from becoming a useful session unless the user's remaining roles still satisfy `read_roles`.

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

Folder policies are the server-side maximum for file access. A Slack, Discord, Telegram, CLI, cron, or dashboard user can never exceed what the server policy allows, even if a prompt asks for a different path.

Normal administrators configure this from the protected dashboard **File Access** page. The dashboard writes the same values to `<HERMES_HOME>/config.yaml` on the server. The default `HERMES_HOME` is `~/.hermes`. Direct YAML edits are for the server operator, reviewed infrastructure-as-code, backup restore, or break-glass recovery.

Folder policies apply to `read_file`, `search_files`, `write_file`, `patch`, and lower-level file operations. In production, use default deny:

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
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [operator]
    - path: "/srv/company/marketing"
      read_teams: [marketing]
      write_users: ["slack:U123456"]
```

Use this as the "maximum accessible root" for the company assistant. Add broad shared folders only when the whole tenant should have them; then narrow sensitive folders by team, role, or user:

```yaml
governance:
  default_file_policy: deny
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
    - path: "/srv/company/marketing/campaign-brief.pdf"
      recursive: false
      read_users: ["slack:U222222", "slack:U333333"]
      write_users: ["slack:U123456"]
```

Most-specific path wins. Policies are recursive by default; set `recursive: false` for exact-path policies. `deny_users` and `deny_teams` override broader grants. Keep the Coorporate Hermes service account itself limited at the operating-system level; governance cannot safely grant access to a folder the OS account cannot read, and OS permissions remain the last line of defense if configuration is wrong.

### Admins vs team leaders

System admins use the dashboard **File Access** page or direct YAML to set the global baseline:

- `governance.default_file_policy`;
- top-level shared folders;
- sensitive corporate folders;
- `governance.team_file_roots`, which delegates a bounded root to a team.

Team leaders use the same dashboard page after logging in. They can edit only policies under the team roots delegated to them. A marketing lead, for example, can grant `read_teams: [marketing]`, `write_users: ["sso:ana@company.com"]`, or read-only exact-file policies for marketing members under `/srv/company/marketing`. They cannot grant access to `/srv/company/finance`, cannot change the global default, cannot grant role-wide access such as `read_roles: [viewer]`, and cannot reference users outside the managed team unless they are also a system admin.

Team-lead delegation is based on the same identity model as the gateway and dashboard login. The dashboard actor is matched to `governance.users` by keys such as `slack:U123456`, `sso:alice@example.com`, or a deployment-specific dashboard identity.

### Practical file-access runbook

1. A system admin starts with `governance.default_file_policy: deny`.
2. The admin maps real users in `governance.users`.
3. The admin adds broad shared folders only when all authenticated users should have them.
4. The admin adds department folders by team or explicit user.
5. The admin delegates a bounded root with `team_file_roots` when a team leader should manage day-to-day access.
6. The team leader logs into the same dashboard through SSO/trusted headers.
7. The team leader opens **File Access**, sees only their delegated root, and adds folder or exact-file policies.
8. Denied attempts are reviewed in the audit log to discover missing grants or attempted boundary crossing.

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

Field guide:

| Field | Meaning | Who can normally set it |
|---|---|---|
| `path` | Absolute server folder or file path. | Admin; team leader below delegated root. |
| `recursive` | `true` for folders, `false` for one exact file. | Admin or delegated team leader. |
| `read_teams`, `write_teams` | Grants to users assigned to a team. | Admin; team leader for managed team only. |
| `read_users`, `write_users` | Grants to named actor keys such as `sso:ana@company.com` or `slack:U123`. | Admin; team leader for users assigned to managed team only. |
| `deny_users`, `deny_teams` | Explicit block that overrides broader grants. | Admin or delegated team leader. |
| `read_roles`, `write_roles` | Broad tenant-wide grants by role. | System admin only. |
| `team_file_roots` | Delegated roots that decide what a team leader can manage. | System admin only. |

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

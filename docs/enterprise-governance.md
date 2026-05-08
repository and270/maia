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

## File Authorization By Team And User

File authorization is configured in one place for normal operators: **Dashboard -> File Access**. The backing file is `<HERMES_HOME>/config.yaml` on the server, where `HERMES_HOME` defaults to `~/.hermes`. The YAML examples below are the exact data the dashboard saves under `governance`; they are not a file inside this repository. Direct YAML edits are for the server operator, reviewed infrastructure-as-code, backup restore, or break-glass recovery.

The policy is checked before `read_file`, `search_files`, `write_file`, `patch`, delete/move operations, cron jobs, and dashboard-triggered actions. A prompt cannot grant itself a path. If the operating-system service account cannot read a folder, Coorporate Hermes cannot read it either; OS permissions remain the last line of defense.

### What To Do First

1. Ask each real user to run `/whoami` in their channel, such as Slack, Discord, Telegram, or WhatsApp. That returns the exact actor key, for example `discord:99887766`, `slack:U123456`, or `whatsapp:+15551234567`.
2. In **Dashboard -> Config**, map those keys under `governance.users` with roles and teams. You can also edit `<HERMES_HOME>/config.yaml` directly on the server.
3. Keep `governance.default_file_policy: deny` in production.
4. Open **Dashboard -> File Access** to create the actual folder policies.

### System Admin Flow

Use this when you are deciding the maximum server folders Coorporate Hermes may ever touch.

1. Log into the dashboard with the local admin token, SSO, trusted proxy identity, or a channel-issued `/dashboard` token whose role satisfies `dashboard.auth.admin_roles`.
2. Open **File Access**.
3. Set **Default file policy** to `deny`.
4. Add a policy for a shared folder only if all authenticated users should read it. Use **Read roles** / **Write roles** for broad tenant-wide grants; only admins can use role-wide fields.
5. Add narrower policies for department folders. Use **Read teams** / **Write teams** for team-wide grants and **Read users** / **Write users** for named people.
6. Add **Delegated team roots** when a team leader should manage day-to-day access inside one bounded folder. Fill **Team**, **Server root**, **Manager roles**, and optionally **Manager users**.
7. Save, test with real mapped users, and review `governance.file_access` audit events for denials.

### Team Leader Flow

Team leaders use the same dashboard URL, but the File Access page is filtered by their identity.

1. The team leader logs in through SSO/trusted headers or asks the bot for `/dashboard` from a private/direct channel.
2. The dashboard matches that identity to `governance.users`.
3. **File Access** shows only delegated roots for teams the user manages, such as `/srv/company/marketing`.
4. The team leader clicks **Add policy** and sets a **Server path** under the delegated root.
5. They use **Read teams** / **Write teams** for their managed team or **Read users** / **Write users** for named users inside that team.
6. They use **Recursive directory policy** for folders. They turn it off for one exact file, such as a read-only PDF.
7. They save and ask the affected user to retry the file operation.

Team leaders cannot change the global default, cannot edit another team's root, cannot grant role-wide access such as `read_roles: [viewer]`, and cannot reference users outside the managed team unless they also have system-admin dashboard access.

### Complete Marketing Example

Goal:

- Ana manages marketing file access.
- Bruno and Carla can read the marketing folder.
- Only Ana can write the marketing root and private budget file.
- The whole marketing team can write campaign drafts.
- Finance users cannot read marketing unless they are also explicitly added to marketing.

Dashboard actions:

1. **Config**: add Ana, Bruno, and Carla to `governance.users`.
2. **File Access -> Delegated team roots**: add team `marketing` with server root `/srv/company/marketing` and manager user `sso:ana@company.com`.
3. **File Access -> Add policy**: add `/srv/company/marketing` with `read_teams: marketing` and `write_users: sso:ana@company.com`.
4. **File Access -> Add policy**: add `/srv/company/marketing/campaigns` with `read_teams: marketing` and `write_teams: marketing`.
5. **File Access -> Add policy**: add `/srv/company/marketing/private-budget.xlsx`, turn off recursive policy, and set `read_users` / `write_users` to Ana only.

Backing YAML in `<HERMES_HOME>/config.yaml`:

```yaml
dashboard:
  auth:
    enabled: true
    read_roles: [auditor, manager, admin]
    manage_roles: [manager, admin]
    admin_roles: [admin]

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
    "sso:felipe@company.com":
      name: Felipe Finance Analyst
      roles: [operator]
      teams: [finance]
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

### How Decisions Are Made

1. Coorporate Hermes resolves the actor key from the channel, CLI, cron, or dashboard session.
2. It finds that actor in `governance.users` and reads their roles and teams.
3. It resolves the requested path and finds the most-specific matching policy.
4. `deny_users` and `deny_teams` win over grants.
5. For reads/searches, the actor must match `read_users`, `read_teams`, or `read_roles`.
6. For writes/patches/deletes, the actor must match `write_users`, `write_teams`, or `write_roles`.
7. If no policy matches and `default_file_policy` is `deny`, access is denied and audited.

### Field Guide

| Dashboard field | YAML field | Meaning | Who can set it |
|---|---|---|---|
| Default file policy | `default_file_policy` | What happens when no folder policy matches. Use `deny` in production. | System admin only. |
| Delegated team roots -> Team | `team_file_roots.<team>` | Team that may manage a bounded server root. | System admin only. |
| Delegated team roots -> Server root | `team_file_roots.<team>.path` | Maximum path a team leader can administer. | System admin only. |
| Delegated team roots -> Manager roles | `team_file_roots.<team>.manager_roles` | Roles within the team that can manage the root. | System admin only. |
| Delegated team roots -> Manager users | `team_file_roots.<team>.managers` | Specific identities that can manage the root. | System admin only. |
| Server path | `folder_policies[].path` | Absolute server folder or exact file path. | Admin; team leader only below delegated root. |
| Recursive directory policy | `recursive` | `true` for folders; `false` for one exact file. | Admin or delegated team leader. |
| Read teams / Write teams | `read_teams`, `write_teams` | Grant everyone assigned to a team. | Admin; team leader only for managed team. |
| Read users / Write users | `read_users`, `write_users` | Grant named actor keys such as `sso:ana@company.com` or `slack:U123`. | Admin; team leader only for users in managed team. |
| Deny users / Deny teams | `deny_users`, `deny_teams` | Block a specific user or team even if a broader rule would allow them. | Admin; team leader only inside managed team. |
| Read roles / Write roles | `read_roles`, `write_roles` | Broad tenant-wide grants by role. | System admin only. |

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

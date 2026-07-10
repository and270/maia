# Enterprise Governance

Maia is an AmpliIA distribution that adds a governance layer for private one-tenant company deployments. It is intentionally configuration-driven so the same assistant can be used by different departments without hardcoding people or folder paths.

## Identity

Gateway users are identified by `platform:user_id`, for example:

- `slack:U123456`
- `discord:99887766`
- `telegram:987654321`
- `whatsapp:+15551234567`

Gateway admission and Maia membership are two required gates:

1. An admin adds the stable ID to the platform allowlist in **Gateway**.
2. An admin creates the exact `platform:user_id` under `governance.users` with at least one role.
3. Only then can the user talk to Maia. If dashboard access is also needed, the governed user sends `/dashboard` in a private/direct chat.
4. Maia records a pending dashboard-login request; a system admin reviews and approves or denies it in **Dashboard Access**.
5. The user sends `/dashboard` again to receive a short-lived one-time login token.

Allowlists, allowed platform roles, pairing approvals, and allow-all flags are admission filters only. They do not synthesize a default Governance role. On a completely fresh installation, the Gateway editor bootstraps the first saved identity as `admin`; later identities remain blocked as **Pending Governance** until explicitly provisioned.

The YAML below is the backing data saved in `<MAIA_HOME>/config.yaml`; direct editing is for server operators, reviewed infrastructure-as-code, backup restore, or break-glass recovery.

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

The `/whoami` command is still useful for troubleshooting because it shows the exact channel identity and current mapping:

```text
/whoami
```

Channel identity and Maia authorization are separate: Discord, Telegram, Slack, WhatsApp, or another provider authenticates the sender account; Maia requires both gateway admission and an explicit Governance role before a human sender can reach the bot.

## Dashboard Access

The dashboard is a server administration surface. It can read and change `config.yaml`, `.env`, governed folder policies, cron jobs, knowledge approvals, and plugin settings.

By default it binds only to `127.0.0.1`:

```bash
maia dashboard
```

For intranet or public access, enable `dashboard.auth` before binding to a non-loopback interface. Maia refuses network binding unless protected mode is configured, unless the operator explicitly uses `--insecure` for temporary trusted-network testing.

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

Dashboard login uses three supported patterns:

- `local_token`: the server operator sets `MAIA_DASHBOARD_TOKEN` or `dashboard.auth.token_hash`; a successful login receives `dashboard.auth.local_token_roles`.
- `channel_token`: a gateway user requests dashboard access with `/dashboard` in a private/direct channel. By default, the first request appears in **Dashboard Access** for admin approval. After approval, `/dashboard` issues a short-lived one-time token when the user satisfies `dashboard.auth.read_roles`. This is the default built-in path for team leaders.
- `trusted_header`: Maia does not provide SSO, VPN, zero-trust networking, or an identity-aware proxy. It can sit behind a company-operated reverse proxy or SSO layer that authenticates the user and passes a configured identity header such as `X-Auth-Request-User`.

### Default Built-In Team-Leader Login

Use this path when team leaders already talk to Maia through Slack, Discord, Telegram, WhatsApp, or another gateway.

1. Enable protected dashboard auth and channel tokens.
2. Set `dashboard.auth.channel_tokens.dashboard_url` to the URL team leaders will open.
3. Keep `dashboard.auth.channel_tokens.approval_required: true`.
4. A team leader sends `/dashboard` in a private/direct chat with the bot.
5. Maia creates a pending request in **Dashboard Access** with the actor key, display name, platform, and request time.
6. A system admin logs in with the local admin token and opens **Dashboard Access**.
7. The admin reviews **Name**, **Roles**, and **Teams**, then clicks **Approve**. The user already has a minimum Governance role to reach `/dashboard`; approval can update that existing `governance.users.<actor_key>` record and separately authorizes dashboard login.
8. If the team leader should manage files, the admin also defines a `team_file_roots` entry in **File Access**.
9. The team leader sends `/dashboard` again. Maia verifies the approved request and current roles, then sends a one-time token.
10. The dashboard session is limited by `read_roles`, `manage_roles`, `admin_roles`, and delegated File Access roots.
11. The admin can later click **Revoke** in **Dashboard Access**. Revocation blocks future channel-token logins, removes unused tokens, and drops active dashboard sessions for that actor.

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

Dashboard fields and what they save:

| Dashboard field | Saved under `governance.users.<actor_key>` | Example |
| --- | --- | --- |
| Name | `name` | `Ana Marketing Lead` |
| Roles | `roles` | `[manager]` |
| Teams | `teams` | `[marketing]` |

The actor key itself comes from the authenticated channel event, not from a free-form browser field. Admins can revoke dashboard login access from **Dashboard Access** without deleting the user from `governance.users`, which lets a person keep normal channel permissions while losing dashboard access.

### Optional company SSO/proxy integration

Use this only if the company already operates SSO, VPN, zero-trust access, or an identity-aware reverse proxy. Maia only consumes the trusted identity header; it does not provide that external access layer.

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

The external proxy must authenticate the human, strip any client-supplied identity headers, and inject only its own authenticated identity header. Prefer binding Maia to `127.0.0.1` behind that proxy. Use `allow_trusted_headers_on_public_bind: true` only when the proxy is the only network path to the dashboard.

There is one dashboard application. The logged-in actor determines the available controls:

| Actor | How they normally log in | What they can do |
|---|---|---|
| System admin | Local admin token, channel-issued `/dashboard` token with `admin`, or trusted header from existing company SSO/proxy. | Global config, secrets, plugins, model settings, all folder policies, delegated roots, approvals, and audit review. |
| Team leader | Channel-issued `/dashboard` token, or trusted header from existing company SSO/proxy. | Approval queues allowed by role, and File Access only under delegated team roots. |
| Operator | Usually CLI or gateway channel identity, not dashboard. | Agent work within configured tool, folder, memory, and cron policy. |
| Auditor | Channel-issued `/dashboard` token, or trusted header from existing company SSO/proxy. | Read operational evidence without changing execution policy. |

Dashboard role gates are intentionally coarse:

| Gate | Typical pages | Default roles |
|---|---|---|
| Read | sessions, logs, analytics, cron list, knowledge review | `auditor`, `manager`, `admin` |
| Manage | cron authorization decisions, team/corporate approval decisions, and delegated File Access updates | `manager`, `admin` |
| Admin | config, secrets, folder policies, plugin install/remove, model settings | `admin` |

All mutating dashboard API calls are written to the audit trail as `dashboard.api_action` when observability audit logging is enabled. Login, logout, and denied role checks are recorded as dashboard auth/authorization events.

### Channel-issued dashboard tokens

If the company does not have SSO in front of the dashboard, Maia can let authenticated channel users request dashboard access and, after approval, one-time dashboard tokens:

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

The user runs `/dashboard` in a private/direct chat with the bot. The gateway already knows the sender as `discord:99887766`, `telegram:987654321`, `whatsapp:+15551234567`, and so on.

First request:

1. If the actor has not been approved, Maia creates a pending **Dashboard Access** request.
2. The bot tells the user the request is pending and to retry `/dashboard` after approval.
3. A system admin reviews the request in the dashboard, assigns roles and teams, and approves or denies it.

Approved request:

1. The user sends `/dashboard` again.
2. Maia checks that dashboard access is approved, not revoked, and that current roles satisfy `dashboard.auth.read_roles`.
3. The bot sends a short-lived one-time token.
4. The dashboard login form consumes that token, creates a normal dashboard session for that actor, and applies the same read/manage/admin gates.

Operational rules:

- Keep `require_dm: true` unless the platform can guarantee private ephemeral replies.
- Set `dashboard_url` to the real intranet, VPN, or protected public dashboard URL; `127.0.0.1` is useful only on the server.
- Tokens are one-time, short-lived, and stored hashed under `<MAIA_HOME>/dashboard/channel_login_tokens.json`.
- Access requests, approvals, denials, revocations, token issuance, and dashboard login are audit events when audit logging is enabled.
- Revoking a user in **Dashboard Access** blocks future token issuance and invalidates active dashboard sessions for that actor.

## Memory and Skill Governance

Maia keeps user memory/skills, but adds approved corporate and team layers above them:

- corporate memory and skills apply to every conversation;
- team memory and skills apply to actors assigned to that team;
- each human gateway identity has isolated personal memory and skills under `<MAIA_HOME>/users/<platform-hash>/`;
- CLI/local sessions retain profile-level `<MAIA_HOME>/memories/` and `<MAIA_HOME>/skills/` compatibility.

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

File authorization is configured in one place for normal operators: **Dashboard -> File Access**. The backing file is `<MAIA_HOME>/config.yaml` on the server, where `MAIA_HOME` defaults to `~/.maia`. The YAML examples below are the exact data the dashboard saves under `governance`; they are not a file inside this repository. Direct YAML edits are for the server operator, reviewed infrastructure-as-code, backup restore, or break-glass recovery.

The policy is checked before `read_file`, `search_files`, `write_file`, `patch`, delete/move operations, cron jobs, and dashboard-triggered actions. A prompt cannot grant itself a path. If the operating-system service account cannot read a folder, Maia cannot read it either; OS permissions remain the last line of defense.

### What To Do First

1. Ask each real user who needs dashboard or delegated file administration to run `/dashboard` in a private channel chat.
2. Provision each `platform:user_id` in **Config / Governance** with the right roles and teams. This creates the `governance.users` mapping used by file policies; Dashboard Access is a later, separate login grant.
3. Keep `governance.default_file_policy: deny` in production.
4. Open **Dashboard -> File Access** to create the actual folder policies.

### System Admin Flow

Use this when you are deciding the maximum server folders Maia may ever touch.

1. Log into the dashboard with the local admin token, a channel-issued `/dashboard` token whose role satisfies `dashboard.auth.admin_roles`, or a trusted header from an existing company SSO/proxy.
2. Open **File Access**.
3. Set **Default file policy** to `deny`.
4. Add a policy for a shared folder only if all authenticated users should read it. Use **Read roles** / **Write roles** for broad tenant-wide grants; only admins can use role-wide fields.
5. Add narrower policies for department folders. Use **Read teams** / **Write teams** for team-wide grants and **Read users** / **Write users** for named people.
6. Add **Delegated team roots** when a team leader should manage day-to-day access inside one bounded folder. Fill **Team**, **Server root**, **Manager roles**, and optionally **Manager users**.
7. Save, test with real approved users, and review `governance.file_access` audit events for denials.

### Team Leader Flow

Team leaders use the same dashboard URL, but the File Access page is filtered by their identity.

1. The team leader asks the bot for `/dashboard` from a private/direct channel. If access is not approved yet, a system admin approves the pending request in **Dashboard Access** first.
2. The dashboard matches the approved identity to `governance.users`.
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

1. **Config / Governance**: add Ana, Bruno, and Carla with the right roles and `marketing` team. This creates `governance.users` before any of them can access the bot.
2. **File Access -> Delegated team roots**: add team `marketing` with server root `/srv/company/marketing` and manager user `sso:ana@company.com`.
3. **File Access -> Add policy**: add `/srv/company/marketing` with `read_teams: marketing` and `write_users: sso:ana@company.com`.
4. **File Access -> Add policy**: add `/srv/company/marketing/campaigns` with `read_teams: marketing` and `write_teams: marketing`.
5. **File Access -> Add policy**: add `/srv/company/marketing/private-budget.xlsx`, turn off recursive policy, and set `read_users` / `write_users` to Ana only.

Backing YAML in `<MAIA_HOME>/config.yaml`:

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

1. Maia resolves the actor key from the channel, CLI, cron, or dashboard session.
2. It finds that actor in `governance.users` and reads their roles and teams.
3. It resolves the requested path and finds the most-specific matching policy.
4. `deny_users` and `deny_teams` win over grants.
5. For reads/searches, the actor must match `read_users`, `read_teams`, or `read_roles`.
6. For writes/patches/deletes, the actor must match `write_users`, `write_teams`, or `write_roles`.
7. If no policy matches and `default_file_policy` is `deny`, access is denied and audited.
8. If the nearest matching policy that declares `write_approval_roles` / `write_approval_users` has a non-empty requirement, a write by a grant-holder is **staged for approval** instead of applied (see below). Actors who satisfy the requirement themselves write directly.

### Staged Write Approvals (`write_approval_roles` / `write_approval_users`)

Folder policies can require a human sign-off on every modification, on top of the
write grant itself:

```yaml
governance:
  folder_policies:
    - path: "/srv/company/finance"
      write_users: ["sso:felipe@company.com"]   # Felipe MAY write...
      write_approval_roles: [manager]           # ...but each change needs a manager
```

How it works:

1. When a grant-holding actor writes (write/patch) to such a path, the file tools
   stage the FINAL proposed content — nothing touches disk. The staged request
   (with a unified diff and the requester's identity) lands in
   `<MAIA_HOME>/file_changes/approvals.json`.
2. Approvers see it in the dashboard **File Approvals** panel. If the request
   came from a chat session, an approval card is also posted to that channel,
   @mentioning eligible approvers on that platform (Slack, Discord, Telegram get
   Approve/Deny buttons; other platforms get a text notice). Button clicks are
   validated against the approver requirement — a non-approver clicking gets a
   private error.
3. Approving applies the exact reviewed content atomically and audits it. If the
   file changed on disk after staging, the request is marked `stale` instead of
   applied and must be re-staged. Denying discards the change. The requester's
   write grant is re-checked at apply time, so revoking access also invalidates
   pending requests.
4. A child policy can opt its subtree out of an ancestor's requirement by
   declaring the keys empty (`write_approval_roles: []`).

Unlike dangerous-command prompts, staged approvals are asynchronous and durable:
the agent finishes its turn immediately and nothing expires.

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
| Write approval roles / users | `write_approval_roles`, `write_approval_users` | Stage every write by a grant-holder for approval by these roles/users before it applies. Empty lists on a child policy opt out of an ancestor's requirement. | Admin; team leader only inside managed team. |

## Terminal Governance

Folder policies gate the file tools, but shell commands and sandboxed code run
with the host process's OS permissions — a terminal command can touch paths its
requester holds no grant for. Two optional controls close that gap:

```yaml
governance:
  terminal:
    allowed_roles: [operator]      # who may run terminal/execute_code at all
    allowed_users: []              # exact actor keys, additive to roles
    approver_roles: [manager]      # who may APPROVE flagged commands
    approver_users: []
```

- `allowed_roles` / `allowed_users` — actors outside the list cannot use the
  terminal or execute_code tools at all. Denials are audited
  (`governance.terminal_access`). Unset means no restriction (backward
  compatible).
- `approver_roles` / `approver_users` — when set, dangerous-command approvals
  raised in gateway sessions by an actor who does not satisfy the requirement
  can only be APPROVED by someone who does: the approval prompt pings the
  eligible approvers in the channel with @mentions, and the requester's own
  Approve clicks or `/approve` commands are rejected with an explanation.
  Deny stays open to everyone in the session (fail-safe direction), timeouts
  still deny, and actors who satisfy the requirement themselves keep the
  normal self-approval flow.
- Responder identity: the `/approve` and `/deny` text commands carry the
  responder's identity on every platform; approval BUTTONS carry it on
  Slack, Discord, and Telegram. Button surfaces that cannot identify the
  responder fail closed under a requirement — an approver there decides via
  `/approve` instead.

Hardline commands (root filesystem wipes, mkfs, raw device writes, shutdown)
remain blocked for everyone regardless of these settings, and containerized
terminal backends keep bypassing the dangerous-command layer by design.

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

Governance denials and cron authorization requests, approvals, and denials are written to `<MAIA_HOME>/logs/audit.jsonl` when `observability.audit_log_enabled` is true.
Knowledge approval requests, approvals, and denials are also written to the audit trail.

```bash
maia logs audit
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

Related Maia docs:

- [Admin onboarding](admin-onboarding.md)
- [Migration from upstream Hermes](migration-from-hermes.md)
- [Knowledge governance](knowledge-governance.md)
- [Cron authorization panel](cron-authorization-panel.md)
- [Observability](observability.md)

---
title: "Enterprise Governance"
description: "Identity, roles, dashboard access, folder policies, gateway isolation, cron approval checkpoints, and audit controls."
---

# Enterprise Governance

Maia adds a governance layer for private one-tenant deployments. The policy lives in `<MAIA_HOME>/config.yaml` (`~/.maia/config.yaml` by default). Normal administration happens through the protected dashboard; direct YAML edits are for server operators, reviewed deployment automation, backup restore, or break-glass recovery.

Most employees do not need the dashboard. They interact with Maia through a messaging gateway such as Discord, Slack, Mattermost, Matrix, WhatsApp, or Telegram. The dashboard is the admin surface for configuring the deployment, approving dashboard access, assigning governance roles, reviewing logs, and managing policies; protect it like any other admin console.

## Identity and Roles

Gateway users are identified by stable `platform:user_id` keys. Human access is the intersection of two gates: a platform allowlist, allowed role, pairing approval, or allow-all flag admits the identity to the gateway; an explicit `governance.users` record with at least one role admits that identity to Maia. A user who passes only the first gate remains blocked as **Pending Governance**.

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

Roles drive authorization. Teams are first-class Governance records used for membership, approved team knowledge, delegated roots, and group file grants.

Provision the stable ID in **Gateway**, then add the same `platform:user_id` with a role in **Governance**. On a completely fresh installation, the Gateway editor bootstraps only the first saved identity as `admin`; every later identity requires this explicit grant. After provisioning, `/whoami` shows the current mapping and `/dashboard` can create a separate dashboard-login request for users who need the admin surface.

## Govern Maia Through Messages

An authorized admin can ask Maia in a private gateway conversation to admit a user, assign roles or teams, manage direct file grants, create delegated roots, or update folder policies. Maia uses the structured `maia_admin` tool, derives the requester from the authenticated message, and rechecks Governance for each operation. Team managers are limited to their delegated roots and members; provider secrets and dashboard login credentials cannot be changed through this tool. Successes and denials are audit events.

This is the normal alternative when you do not want to publish the dashboard. Existing message approval controls also let authorized managers decide governed write requests without opening the web UI.

## Dashboard Access

The dashboard can change config, secrets, server folder policies, cron jobs, approval decisions, plugins, and model settings. Both `maia` and `maia dashboard` bind it to `127.0.0.1` by default, so it is reachable only from that computer:

```bash
maia dashboard
```

For intranet or public serving, configure protected mode first. Maia refuses non-loopback binding without dashboard auth unless `--insecure` is explicitly used.

For private remote access, consider [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve). For an identity-aware public endpoint, consider [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/) together with [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/choose-application-type/). Keep Maia's dashboard auth enabled behind either service, use TLS, and never make `--insecure` permanent.

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
4. On approval, Maia authorizes dashboard login and may update the actor's already-provisioned `governance.users` record.
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

The Governance workspace is organized as **People → Teams → File access → Approvals → Settings**. People and Teams cover the common assignment workflows; File access is the advanced policy list and opens directly on existing governed paths with **Add policy** beside the list.

Use **Dashboard -> File Access** for normal file authorization. The dashboard writes the same values to `<MAIA_HOME>/config.yaml` on the server under `governance`; this YAML is not a separate repo file. Direct YAML edits are for server operators, reviewed infrastructure-as-code, backup restore, or break-glass recovery.

Before creating policies:

1. Ask users who need dashboard or delegated file administration to run `/dashboard` in a private channel chat.
2. Create the required teams under **Governance → Teams**.
3. Approve dashboard requests and assign only registered teams.
4. Add direct user/team paths from **People** or **Teams**, or open **File Access** for advanced policies.

Governance is always active. Adding a person and assigning a role admits that identity to Maia but does not grant any files. Unmatched paths are always denied. File tools enforce the policy directly; gateway `terminal` and `execute_code` sessions run through Docker or Podman with only granted paths mounted, and delegated agents inherit that boundary. If isolation is unavailable, Maia enters Restricted mode: chat and path-checked file tools continue, command automation returns `secure_execution_unavailable`, and nothing falls back to the host. Operators can run `maia secure-runtime status` or `maia secure-runtime setup`.

The gateway includes only the current requester's readable policy paths in the agent's session context. A user with an exact grant for `finance/financas.xlsx` can therefore refer to "the finance spreadsheet" without knowing its full server path. If `search_files` starts at `.` or another broad parent that is not granted, Maia searches only that user's readable grants within the requested scope. It authorizes every returned filename, content match, and count again, so denied siblings and more-specific denied child paths remain invisible.

System admins manage people, teams, direct grants, sensitive folders, role-wide grants, and delegated team roots. Team leaders use File Access after approved `/dashboard` access but see only the roots delegated to them.

System admin workflow:

1. Open **People** to grant roles and optional direct file/folder access.
2. Open **Teams**, create the team, add governed people, and grant the team paths.
3. Add a **Delegated management root** on the team when a team leader should manage one bounded folder.
4. Open **File Access** for advanced role, deny, and write-approval policy fields.
5. Save and review `governance.file_access` audit events for denied attempts.

Direct grants use three write modes: no write, direct write, or write after
approval. For a folder, keep **Include files and subfolders** enabled; disabling
it creates an exact-path grant and does not cover files inside that folder.

When write after approval is selected, a file-tool call by the conditional
writer changes nothing and returns the eligible authorized writers. The model
can finish planning and tag one of them in the same shared thread. Their later
message is an ordinary natural-language turn under their own authenticated
identity, so they may agree, reject, or revise the edit. If they ask Maia to
proceed, the tool rechecks that sender and a direct writer can execute. Maia
does not use approval keywords, create a staged edit/card, grant access, or
change a file policy. Gateway threads are shared by default; non-thread groups
must use a thread or set `group_sessions_per_user: false` for this handoff.

Team leader workflow:

1. Send `/dashboard` in a private channel. If access is not approved yet, a system admin approves the pending request in **Dashboard Access** first.
2. Confirm **File Access** shows the expected managed team badge and root.
3. Click **Add policy** and set a **Server path** under the delegated root.
4. Use **Read teams** / **Write teams** for the managed team or **Read users** / **Write users** for named users assigned to that team.
5. Leave **Recursive directory policy** on for folders; turn it off for one exact file.
6. Save and ask the affected user to retry.

Team leaders cannot edit another team's root, grant role-wide rules such as `read_roles: [viewer]`, or reference users outside the managed team unless they also have system-admin dashboard access.

Practical marketing example, as saved in `<MAIA_HOME>/config.yaml`:

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
6. If no policy matches, access is denied and audited.
7. A matching policy with no applicable read/write grant also denies access.

| Dashboard field | YAML field | Who can normally set it |
|---|---|---|
| Team registry | `teams` | System admin only. |
| Delegated team roots | `team_file_roots` | System admin only. |
| Server path | `folder_policies[].path` | Admin; team leader below delegated root. |
| Recursive directory policy | `recursive` | Admin or delegated team leader. |
| Read teams / Write teams | `read_teams`, `write_teams` | Admin; team leader for managed team only. |
| Read users / Write users | `read_users`, `write_users` | Admin; team leader for users assigned to managed team only. |
| Deny users / Deny teams | `deny_users`, `deny_teams` | Admin; team leader inside managed team. |
| Read roles / Write roles | `read_roles`, `write_roles` | System admin only. |

## Knowledge Authority

Corporate memory/skills apply to every conversation. Team memory/skills apply by `governance.users.*.teams`. Each human gateway identity has isolated personal memory and skills under `<MAIA_HOME>/users/<platform-hash>/`; CLI/local sessions keep the profile-wide legacy paths. Corporate and team edits are staged for approval and applied only by an authorized human in the dashboard Knowledge panel or API.

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

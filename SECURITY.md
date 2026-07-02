# Maia Security Policy

Maia is an AmpliIA distribution intended for a private, one-tenant corporate assistant deployment. It assumes company-controlled operators, configured gateway users, governed filesystem roots, and audited scheduled workflows.

## Trust Model

- **Single tenant:** One organization owns the assistant instance, data directory, gateway credentials, model credentials, logs, and cron state.
- **User identity:** Gateway users are identified as `platform:user_id` and mapped to roles under `governance.users`.
- **Role hierarchy:** Later roles inherit earlier roles in `governance.role_hierarchy`; the default hierarchy is `viewer < operator < manager < admin`.
- **Knowledge hierarchy:** Corporate memory/skills apply to every conversation, team memory/skills apply by `governance.users.*.teams`, and user memory/skills remain profile-level.
- **Gateway sessions:** Regular group/channel conversations are isolated per user by default. Explicit threads/topics are shared by default for multi-user operational workflows.
- **Filesystem access:** Folder policies are enforced by the file tools and lower-level file operations. For production, set `governance.default_file_policy: deny` and explicitly allow company folders. Reads/searches require read grants; writes/patches/deletes require write grants.
- **Team file delegation:** `governance.team_file_roots` lets a team leader manage policies only under their team's configured root from the dashboard.
- **Dashboard access:** The dashboard is localhost-only by default. Intranet or public serving requires `dashboard.auth` unless an operator explicitly uses `--insecure` for temporary trusted-network testing.
- **Dashboard identity:** Local token mode is for bootstrap/system-admin access. Team leaders request dashboard access through `/dashboard`; admins approve, deny, revoke, or restore that access in **Dashboard Access**. If the company already has SSO or an identity-aware proxy, Maia can also consume trusted headers mapped through `governance.users`.
- **Channel dashboard tokens:** Authenticated gateway users can request dashboard access with `/dashboard`. By default the first request creates a pending approval; after approval, `/dashboard` issues a short-lived one-use token. Tokens are hashed on disk and should be requested from private/direct chats.
- **Shared knowledge approval:** Corporate and team memory/skill edits are proposal-first and require an authorized human approval before files under `<MAIA_HOME>/corporate/` or `<MAIA_HOME>/teams/` are changed.
- **Cron authorization:** Scheduled workflows can require role or user approval before execution. Approval and denial metadata is persisted in the cron job record.
- **Audit trail:** Governance denials, knowledge approvals, and cron authorization decisions are written to `<MAIA_HOME>/logs/audit.jsonl` when observability is enabled.

## Governance Controls

Dashboard protected mode:

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

Set `MAIA_DASHBOARD_TOKEN` from the server environment or use `dashboard.auth.token_hash` with a `sha256:<hex>` hash. Maia does not provide SSO, VPN, zero-trust networking, or a reverse proxy. If the company already has that layer, configure `trusted_user_header` only behind a proxy that strips spoofed client headers, and prefer binding Maia to `127.0.0.1` behind that proxy.

System admins can edit global folder policy, role-wide grants, and `team_file_roots`. Team leaders can save policies only under delegated roots, cannot change `default_file_policy`, cannot grant role-wide access, and cannot reference users outside the managed team.

Channel dashboard token baseline:

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

Default channel access flow:

1. The user sends `/dashboard` in a private/direct chat.
2. Maia creates a pending **Dashboard Access** request with the gateway actor key.
3. A system admin approves the request in the dashboard and assigns roles and teams.
4. The user sends `/dashboard` again to receive a one-time login token.
5. Admins can revoke access from **Dashboard Access**. Revocation blocks future token issuance and invalidates active dashboard sessions for that actor.

Do not set `require_dm: false` unless the platform reply is guaranteed private.

Example production baseline:

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  default_file_policy: deny
  team_file_roots:
    marketing:
      path: "/srv/company/marketing"
      manager_roles: [manager]
      managers: ["slack:U123"]
  users:
    "slack:U123": {roles: [manager], teams: [marketing]}
    "telegram:987654": {roles: [admin]}
  folder_policies:
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [admin]
    - path: "/srv/company/finance"
      read_teams: [finance]
      write_roles: [manager]
    - path: "/srv/company/marketing"
      read_teams: [marketing]
      write_users: ["slack:U123"]
  cron:
    default_authorizer_roles: [admin]
```

Shared knowledge baseline:

```yaml
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
```

Use the dashboard Knowledge panel to approve or deny shared memory/skill changes. Do not write directly to corporate/team knowledge directories in production.

Cron jobs that include:

```yaml
authorization:
  required: true
  roles: [manager]
```

pause at `awaiting_authorization` until an authorized user runs `cronjob(action="authorize", job_id="...")`. Denials use `cronjob(action="deny", job_id="...", reason="...")`.

## Deployment Hardening

- Run the gateway and API server behind VPN, private network ingress, or an identity-aware proxy.
- Keep `maia dashboard` bound to `127.0.0.1` unless `dashboard.auth` is enabled. For public dashboard access, use TLS and a reverse proxy; do not use `--insecure` outside short-lived tests.
- Use a container, VM, or dedicated service account for production workloads. Avoid broad host access from `terminal.backend: local`.
- Set filesystem ownership and mode so only the service account can read secrets and job state.
- Keep API keys in the environment or `.env`; do not store secrets in prompts, docs, or `config.yaml`.
- Keep `approvals.mode: manual` or `smart` for interactive use. Treat `approvals.mode: off` as break-glass only.
- Limit `terminal.docker_volumes`, `terminal.env_passthrough`, and MCP server environment blocks to the minimum needed.
- Review Skills Guard output before enabling third-party skills.
- Review corporate/team knowledge approval requests before promotion; imported upstream memories and skills should not be copied into shared layers directly.
- Enable logging retention and external SIEM export if the deployment handles regulated data.

## Observability Baseline

```yaml
observability:
  enabled: true
  audit_log_enabled: true
  audit_log_path: ""
  redact_sensitive_values: true
  siem_webhook_url: ""
  retention_days: 180
```

Use `maia logs audit` or the dashboard Logs page to review audit events. Configure `siem_webhook_url` only for private, approved collectors. The audit log is for governance decisions, knowledge approvals, cron authorization, dashboard access requests/approvals/revocations, dashboard login/logout, dashboard role denials, and mutating dashboard API calls; runtime debugging remains in `agent.log`, `errors.log`, and `gateway.log`.

## Guarded Migration

Use `maia import <archive> --from-hermes-export` for upstream Hermes tar/tar.gz exports. This stages imported skills and memories for review, imports MCP servers disabled by default, and does not activate old secrets or overwrite Maia guardrails. Promote reviewed memories or skills into corporate/team layers only through the Knowledge approval flow.

## Enterprise References

The security posture is aligned with:

- NIST AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework
- Cloud Security Alliance AI Controls Matrix: https://cloudsecurityalliance.org/artifacts/ai-controls-matrix
- Microsoft Entra guidance for securing AI agents as governed identities: https://learn.microsoft.com/en-us/entra/agent-id/identity-professional/security-for-ai

## Vulnerability Reporting

For this private distribution, report issues through the owning organization's internal security process. Include:

- affected file path and line range;
- `maia version`, commit SHA, OS, and Python version;
- reproduction steps;
- impact and trust boundary crossed;
- whether governance, approval, or folder-policy controls were bypassed.

For vulnerabilities inherited from upstream Hermes Agent components, also preserve upstream coordinated-disclosure expectations when reporting externally.

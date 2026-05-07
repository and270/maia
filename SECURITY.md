# Coorporate Hermes Security Policy

Coorporate Hermes is an AmpliIA distribution intended for a private, one-tenant corporate assistant deployment. It assumes company-controlled operators, configured gateway users, governed filesystem roots, and audited scheduled workflows.

## Trust Model

- **Single tenant:** One organization owns the assistant instance, data directory, gateway credentials, model credentials, logs, and cron state.
- **User identity:** Gateway users are identified as `platform:user_id` and mapped to roles under `governance.users`.
- **Role hierarchy:** Later roles inherit earlier roles in `governance.role_hierarchy`; the default hierarchy is `viewer < operator < manager < admin`.
- **Knowledge hierarchy:** Corporate memory/skills apply to every conversation, team memory/skills apply by `governance.users.*.teams`, and user memory/skills remain profile-level.
- **Gateway sessions:** Regular group/channel conversations are isolated per user by default. Explicit threads/topics are shared by default for multi-user operational workflows.
- **Filesystem access:** Folder policies are enforced by the file tools and lower-level file operations. For production, set `governance.default_file_policy: deny` and explicitly allow company folders.
- **Shared knowledge approval:** Corporate and team memory/skill edits are proposal-first and require an authorized human approval before files under `<HERMES_HOME>/corporate/` or `<HERMES_HOME>/teams/` are changed.
- **Cron authorization:** Scheduled workflows can require role or user approval before execution. Approval and denial metadata is persisted in the cron job record.
- **Audit trail:** Governance denials, knowledge approvals, and cron authorization decisions are written to `<HERMES_HOME>/logs/audit.jsonl` when observability is enabled.

## Governance Controls

Example production baseline:

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  default_file_policy: deny
  users:
    "slack:U123": {roles: [manager], teams: [finance]}
    "telegram:987654": {roles: [admin]}
  folder_policies:
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [operator]
    - path: "/srv/company/finance"
      read_roles: [manager]
      write_roles: [manager]
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

Use `coorporate logs audit` or the dashboard Logs page to review audit events. Configure `siem_webhook_url` only for private, approved collectors. The audit log is for governance decisions, knowledge approvals, and cron authorization; runtime debugging remains in `agent.log`, `errors.log`, and `gateway.log`.

## Guarded Migration

Use `coorporate import <archive> --from-hermes-export` for upstream Hermes tar/tar.gz exports. This stages imported skills and memories for review, imports MCP servers disabled by default, and does not activate old secrets or overwrite Coorporate Hermes guardrails. Promote reviewed memories or skills into corporate/team layers only through the Knowledge approval flow.

## Enterprise References

The security posture is aligned with:

- NIST AI Risk Management Framework: https://www.nist.gov/itl/ai-risk-management-framework
- Cloud Security Alliance AI Controls Matrix: https://cloudsecurityalliance.org/artifacts/ai-controls-matrix
- Microsoft Entra guidance for securing AI agents as governed identities: https://learn.microsoft.com/en-us/entra/agent-id/identity-professional/security-for-ai

## Vulnerability Reporting

For this private distribution, report issues through the owning organization's internal security process. Include:

- affected file path and line range;
- `coorporate version`, commit SHA, OS, and Python version;
- reproduction steps;
- impact and trust boundary crossed;
- whether governance, approval, or folder-policy controls were bypassed.

For vulnerabilities inherited from upstream Hermes Agent components, also preserve upstream coordinated-disclosure expectations when reporting externally.

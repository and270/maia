# Coorporate Hermes

Private one-tenant corporate AI assistant by [AmpliIA](https://ampliia.com/en/), based on the upstream Hermes Agent codebase and refit for company use: role-aware gateway conversations, governed folder access, corporate/team/user knowledge layers, guarded migration from upstream Hermes exports, human-in-the-loop cron authorization, and corporate observability.

The installed commands are renamed so operators do not use the upstream `hermes` command name:

```bash
coorporate              # interactive assistant
coorporate gateway      # messaging gateway
coorporate cron list    # scheduled workflows
coorporate model        # model/provider selection
coorporate doctor       # diagnostics
coorporate-acp          # ACP editor integration
coorporate-agent        # direct agent runner
```

## Install

```bash
git clone https://github.com/and270/coorporate-hermes.git
cd coorporate-hermes
./setup-coorporate.sh
coorporate setup
coorporate
```

Manual development install:

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
coorporate --help
```

## Dashboard Access

Local setup:

```bash
coorporate dashboard
```

The dashboard binds to `127.0.0.1` by default. It can edit `.env`, `config.yaml`, folder policies, cron jobs, knowledge approvals, plugins, and model settings, so configure protected mode before serving it on an intranet or public interface:

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

Use a TLS reverse proxy or private network boundary for public access. Coorporate Hermes refuses non-loopback dashboard binding unless `dashboard.auth` is configured, unless `--insecure` is explicitly used for temporary trusted-network testing.

Use the local token for bootstrap and system-admin access. For team leaders, put the dashboard behind SSO or a trusted reverse proxy and map identities such as `sso:ana@company.com` in `governance.users`; the same dashboard then shows only the pages and File Access roots allowed by that user's roles and teams.

If SSO is not available, mapped gateway users can request a short-lived dashboard token from the same channel identity:

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

Users run `/whoami` to show their exact `platform:user_id`, then an admin maps that key under `governance.users`. Users with roles allowed by `dashboard.auth.read_roles` can run `/dashboard` in a private/direct chat and paste the one-time token into the dashboard login form.

## Corporate Governance

Coorporate Hermes keeps the existing gateway, tool, memory, and cron capabilities, but adds a `governance` section in `<HERMES_HOME>/config.yaml`. Users can run `/whoami` in Slack, Discord, Telegram, WhatsApp, or another gateway to reveal the exact `platform:user_id` key an admin should map.

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U_FINANCE":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
    "slack:U_MARKETING":
      name: Marketing Lead
      roles: [manager]
      teams: [marketing]
    "telegram:987654":
      name: Platform Admin
      roles: [admin]
  default_file_policy: deny
  team_file_roots:
    marketing:
      path: "/srv/company/marketing"
      manager_roles: [manager]
      managers: ["slack:U_MARKETING"]
  folder_policies:
    - path: "/srv/company/shared"
      read_roles: [viewer]
      write_roles: [operator]
    - path: "/srv/company/finance"
      read_teams: [finance]
      write_roles: [manager]
    - path: "/srv/company/marketing"
      read_teams: [marketing]
      write_users: ["slack:U_MARKETING"]
    - path: "/srv/company/security"
      read_roles: [admin]
      write_roles: [admin]
  gateway:
    group_sessions_per_user: true
    thread_sessions_per_user: false
  cron:
    default_authorizer_roles: [admin]
```

What this enforces today:

- Gateway users can be mapped to roles by `platform:user_id`.
- Shared gateway threads remain multi-user by default, while non-thread group chats stay isolated per participant.
- `read_file`, `search_files`, `write_file`, `patch`, and the lower-level file operation layer check configured folder policies. These policies are the server-side maximum directories Coorporate Hermes may access for any channel, cron job, or dashboard-triggered action.
- Admins manage global file access from dashboard **File Access** or server-side YAML. Team leaders use the same page after dashboard login, but only for delegated roots such as `/srv/company/marketing`, and only for users or teams assigned to that managed team.
- Corporate memory/skills are injected into every conversation; team memory/skills are injected by team membership; user memory/skills stay profile-level.
- Corporate and team memory/skill edits are staged for approval and applied only by authorized humans in the Knowledge panel/API.
- Cron jobs can pause at an authorization node until an allowed user or role approves them.

Create a scheduled flow with an approval gate:

```python
cronjob(
  action="create",
  name="Quarterly finance package",
  prompt="Review the finance folder and draft the quarterly summary.",
  schedule="0 9 * * MON",
  workdir="/srv/company/finance",
  authorization={"required": True, "roles": ["manager"]},
)
```

When the job becomes due, it is paused with `state: awaiting_authorization`. An authorized manager can continue it:

```python
cronjob(action="authorize", job_id="abc123")
```

or reject it:

```python
cronjob(action="deny", job_id="abc123", reason="Close not complete yet")
```

## Security Baseline

The governance design follows current enterprise AI-agent guidance:

- NIST AI RMF emphasizes governing, mapping, measuring, and managing AI risks across the AI lifecycle: https://www.nist.gov/itl/ai-risk-management-framework
- CSA AI Controls Matrix provides a vendor-neutral AI controls framework mapped to standards including ISO 42001, ISO 27001, and NIST AI RMF: https://cloudsecurityalliance.org/artifacts/ai-controls-matrix
- Microsoft Entra guidance treats agents as governed identities with authentication, authorization, lifecycle controls, and monitoring: https://learn.microsoft.com/en-us/entra/agent-id/identity-professional/security-for-ai

For deployment details, see [SECURITY.md](SECURITY.md).
For configuration details, see [docs/enterprise-governance.md](docs/enterprise-governance.md).

## Admin Onboarding

Start with the administrator flow:

- [docs/admin-onboarding.md](docs/admin-onboarding.md) — tenant, roles, gateway identities, folder access, cron approvals, and audit retention.
- [docs/knowledge-governance.md](docs/knowledge-governance.md) — corporate, team, and user memory/skill layers plus the approval flow.
- [docs/migration-from-hermes.md](docs/migration-from-hermes.md) — guarded import for upstream Hermes tar/tar.gz exports.
- [docs/cron-authorization-panel.md](docs/cron-authorization-panel.md) — dashboard and tool approval checkpoints per role or user.
- [docs/observability.md](docs/observability.md) — runtime logs, audit JSONL, SIEM webhook export, and current telemetry coverage.

The dashboard also includes an **Onboarding** page with the same admin checklist.

## Migrating From Upstream Hermes

Use guarded migration mode for a Hermes export archive:

```bash
coorporate import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

This stages memories and skills for review, imports MCP servers disabled by default, copies secrets only into the migration review folder, and preserves Coorporate Hermes governance guardrails. Promote reviewed content into corporate or team knowledge only through the Knowledge approval workflow.

## Observability

Operational logs are available through `coorporate logs` and the dashboard Logs page. Corporate audit events are written to `<HERMES_HOME>/logs/audit.jsonl` and include governance file denials, knowledge approvals, cron authorization requests/decisions, dashboard login/logout, dashboard role denials, and mutating dashboard API calls.

```bash
coorporate logs audit
```

## License

Coorporate Hermes is an AmpliIA distribution that includes upstream Hermes Agent components under the MIT License. Nous Research is credited for the upstream Hermes Agent code as required by the preserved MIT notice in [LICENSE](LICENSE).

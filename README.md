<div align="center">

<img src="assets/maia-banner.svg" alt="Maia: the enterprise AI agent by AmpliIA" width="100%"/>

**An AI agent for the enterprise. Open source. Free.**

Role-aware conversations, governed file access, human-in-the-loop approvals, and corporate audit, on top of the Hermes Agent runtime.

[About Maia](https://ampliia.com/en/maia/) · [Documentation](https://ampliia.com/en/maia/docs/) · [Install](#install) · [Governance](#corporate-governance) · [Security](SECURITY.md)

[![License: MIT](https://img.shields.io/badge/license-MIT-0C0A92)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-0C0A92)
[![Lint](https://github.com/and270/maia/actions/workflows/lint.yml/badge.svg)](https://github.com/and270/maia/actions/workflows/lint.yml)
![Model agnostic](https://img.shields.io/badge/LLM-model--agnostic-0C0A92)
[![Based on Hermes Agent](https://img.shields.io/badge/based%20on-Hermes%20Agent-555555)](LICENSE)

</div>

Maia is a private one-tenant corporate AI assistant by [AmpliIA](https://ampliia.com/en/), based on the upstream Hermes Agent codebase and refit for company use: role-aware gateway conversations, governed folder access, corporate/team/user knowledge layers, guarded migration from upstream Hermes exports, human-in-the-loop cron authorization, and corporate observability.

## Why Maia

| | |
|---|---|
| 🗂️ **Governed file access:** folder policies by role, team, or user; default-deny for production; delegated roots that team leads manage themselves. | ✅ **Human-in-the-loop approvals:** file changes staged as reviewable diffs, flagged commands routed to approver roles, knowledge and cron approvals with chat buttons and @mentions. |
| 🧠 **Layered knowledge:** corporate, team, and user memories/skills with explicit precedence; shared layers change only through approval. | 💬 **Multi-channel gateway:** Slack, Discord, Mattermost, Matrix, Telegram, WhatsApp, and more, with per-user sessions and `platform:user_id` identity mapping. |
| 🔁 **Model agnostic:** major cloud APIs, OpenAI-compatible endpoints, or fully local models on your servers, with multi-provider fallback. | 📜 **Audit & observability:** append-only audit JSONL for every allow, deny, and approval, plus optional SIEM webhook export. |

## How a request is governed

```mermaid
flowchart LR
    U["Employee<br/>(Slack · Discord · Teams · WhatsApp)"] --> G["Maia governance<br/>identity → roles & teams"]
    G -->|"cleared to see"| R["Read<br/>company docs & memory"]
    G -->|"protected folder"| E["Edit<br/>staged as a diff"]
    G -->|"flagged command"| C["Command<br/>held for an approver"]
    E --> M["Manager approves<br/>in dashboard or chat"]
    C --> M
    R --> A["Audit log"]
    M --> A
```

Every allow, deny, and approval is recorded; anything outside the actor's policy is blocked. Requesters can never approve their own gated changes.

## Model agnostic by design

Maia treats the LLM as a replaceable component: switching providers is a configuration change (`maia model`), not a rewrite. The same conversations, skills, memories, approvals, and policies keep working when the model changes.

| Cloud APIs | Local / self-hosted | Resilience |
|---|---|---|
| Anthropic, OpenAI, Google Gemini, Mistral, DeepSeek, xAI, OpenRouter, and any OpenAI-compatible endpoint. | Ollama, LM Studio, or any compatible inference server on your own hardware: **no data leaves the company**, a natural fit for sensitive documents, LGPD/GDPR, and air-gapped networks. | Multi-provider fallback keeps operations running through provider outages, account blocks, model deprecations, or price changes. No vendor lock-in: governance, audit trails, and corporate knowledge stay yours. |

Provider keys live in the managed `.env` credential flow, never in prompts, memories, skills, or docs.

## Commands

The installed commands are renamed so operators do not use the upstream `hermes` command name:

```bash
maia              # open Maia: dashboard + chat in the browser (terminal chat: maia --tui)
maia gateway      # messaging gateway
maia cron list    # scheduled workflows
maia model        # model/provider selection
maia doctor       # diagnostics
maia update       # update to the latest version
maia uninstall    # remove Maia (can keep configs/data)
maia-acp          # ACP editor integration
maia-agent        # direct agent runner
```

## Install

### Quick install (macOS / Linux / WSL2)

```bash
curl -fsSL https://ampliia.com/maia/install.sh | bash
```

The installer checks and installs dependencies (uv, Python 3.11, Git, Node.js), clones the repository into `~/.maia/maia`, creates an isolated virtual environment with lockfile-verified dependencies, links the `maia` command into `~/.local/bin`, seeds config templates and bundled skills, and builds the dashboard. It then offers to open the dashboard in your browser, which walks you through setup in order: model provider and API key, messaging gateway, governance and dashboard access, with a chat tab to talk to Maia right away.

If you skipped that step:

```bash
source ~/.bashrc   # or: source ~/.zshrc
maia               # opens the dashboard: onboarding, governance, and the chat tab
maia --tui         # terminal chat instead (bare `maia` stays terminal chat over SSH)
maia setup         # terminal setup wizard
```

Useful installer options and environment variables:

```bash
curl -fsSL https://ampliia.com/maia/install.sh | bash -s -- --skip-setup   # no wizard
curl -fsSL https://ampliia.com/maia/install.sh | bash -s -- --branch dev   # other branch
MAIA_HOME=/srv/maia-data  # data directory override (default: ~/.maia)
MAIA_REPO_URL=...         # corporate mirror or SSH clone URL (see below)
```

If the repository requires authorization (private repo or corporate mirror), point the installer at a clone URL you have access to:

```bash
curl -fsSL https://ampliia.com/maia/install.sh | MAIA_REPO_URL=git@github.com:and270/maia.git bash
```

### Coming from upstream Hermes

Maia keeps its data strictly in `~/.maia` and never touches an existing `~/.hermes`: the two products stay fully independent (separate config, API keys, skills, gateway services), so installing, updating, or uninstalling Maia cannot affect a Hermes install on the same machine. When the installer detects `~/.hermes`, it offers to copy your personal Hermes data into Maia: skills, cron jobs, memories, and `SOUL.md`. API keys, config, and sessions are not copied; the dashboard onboarding sets up the provider. Non-interactive installs never copy silently; use the flags:

```bash
curl -fsSL https://ampliia.com/maia/install.sh | bash -s -- --migrate-hermes     # copy without asking
curl -fsSL https://ampliia.com/maia/install.sh | bash -s -- --no-migrate-hermes  # never offer
```

For a governed, review-first import of a Hermes export archive, use [`maia import --from-hermes-export`](#migrating-from-upstream-hermes) instead.

### Windows (WSL)

Maia runs on Windows through WSL2 (same recommendation as upstream Hermes).
One-time WSL setup from PowerShell (as Administrator), then reboot if asked:

```powershell
wsl --install -d Ubuntu
```

Then, inside the Ubuntu/WSL terminal:

```bash
curl -fsSL https://ampliia.com/maia/install.sh | bash
source ~/.bashrc
maia setup
maia
```

Notes for WSL:
- The installer keeps everything on the Linux filesystem (`~/.maia`), which avoids the slow `/mnt/c/...` installs that cause most WSL failures.
- The `maia` command works from any directory once your shell is reloaded.
- Keep company files you want Maia to govern inside WSL (e.g. `~/company-files`) for the same filesystem-performance reason. Windows paths remain reachable under `/mnt/c/...` when needed.

### Update

```bash
maia update            # pull the latest version and reinstall dependencies
maia update --check    # only check whether an update is available
```

`maia update` fetches the latest code from git, stashes and restores local changes safely, reinstalls dependencies, and clears stale bytecode. Options: `--backup` forces a pre-update backup to `<MAIA_HOME>/backups/`, `--yes` assumes yes for prompts (for scripts and cron), and re-running the install one-liner is always a safe repair path for broken checkouts.

### Uninstall

```bash
maia uninstall               # interactive: keep data or remove everything
maia uninstall --yes         # non-interactive, removes code but keeps configs/data
maia uninstall --full --yes  # non-interactive, removes everything
```

Keep-data mode preserves `<MAIA_HOME>` (config, API keys, sessions, logs, skills), so reinstalling with the one-liner restores service with the same settings. Full mode also stops and removes the gateway service, PATH entries, and the data directory.

### Manual development install

```bash
git clone https://github.com/and270/maia.git
cd maia
./setup-maia.sh
# Or, inside an existing clone:
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
maia --help
```

## Dashboard Access

Local setup (`maia` opens the same local dashboard and browser chat; `maia dashboard` starts the dashboard explicitly):

```bash
maia dashboard
```

Both commands bind the dashboard to `127.0.0.1` by default. Only a browser on that computer can reach it. It can edit `.env`, `config.yaml`, folder policies, cron jobs, knowledge approvals, plugins, and model settings, so configure protected mode before serving it on an intranet or public interface:

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

For a small private deployment, [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) is a practical way to publish the localhost service only inside a tailnet. For an identity-aware public endpoint, [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/) plus [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/choose-application-type/) is another option. Keep Maia's own dashboard authentication enabled behind either boundary, terminate TLS at the access layer, and never use `--insecure` as a permanent deployment mode.

You often do not need to publish the dashboard at all. An authorized admin can ask Maia in a private gateway conversation to admit a user, assign roles and teams, or change file/folder policies. Maia uses the authenticated sender identity and rechecks Governance for every operation. Team managers are limited to delegated roots; provider secrets and dashboard credentials remain server-only. Existing message approval buttons also let authorized managers approve governed writes from the messaging application.

Use the local token for bootstrap and system-admin access. Default built-in flow for team leaders is dashboard-first:

1. A user sends `/dashboard` in a private/direct chat with the bot.
2. Maia creates a pending request in **Dashboard Access** instead of asking anyone to edit YAML.
3. A system admin opens **Dashboard Access**, reviews the `platform:user_id`, assigns roles and teams, and approves or denies the request.
4. After approval, the user sends `/dashboard` again and receives a short-lived one-time token for the dashboard login form.
5. The admin can revoke or restore that dashboard access from the same page.

Channel-token config:

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

Maia does not provide SSO, VPN, zero-trust networking, or an identity-aware proxy. If your company already has that access layer, Maia can sit behind it and consume trusted identity headers such as `X-Auth-Request-User`.

## Corporate Governance

Maia keeps the existing gateway, tool, memory, and cron capabilities, but adds a `governance` section in `<MAIA_HOME>/config.yaml`. The dashboard writes role and team assignments into that section when an admin approves a dashboard access request. Server operators can still edit the YAML directly for infrastructure-as-code, backup restore, or break-glass recovery.

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  teams:
    finance: {}
    marketing: {}
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
- `read_file`, `search_files`, `write_file`, `patch`, and the lower-level file operation layer check configured folder policies. These policies are the server-side maximum directories Maia may access for any channel, cron job, or dashboard-triggered action.
- Admins manage gateway admission, people, teams, and global file access from the dashboard or by asking Maia in an authenticated private gateway conversation. Team leaders can manage file policy only for delegated roots such as `/srv/company/marketing`, and only for users or teams assigned to that managed team.
- Corporate memory/skills are injected into every conversation; team memory/skills are injected by team membership; user memory/skills stay profile-level.
- Corporate and team memory/skill edits are staged for approval and applied only by authorized humans in the Knowledge panel/API.
- Cron jobs can pause at an authorization node until an allowed user or role approves them.

## Role-Aware Self-Configuration Skill

Maia keeps the upstream `hermes-agent` skill, but extends it with a live governance block rendered at skill load time. The block includes the current actor, roles, teams, tenant, dashboard read/manage/admin gates, delegated team file roots, shared-knowledge approval roles, and cron authorization defaults.

This makes the agent aware of what it may configure for the current user. For people, teams, gateway admission, and file policies, Maia uses the structured `maia_admin` tool instead of editing `config.yaml` or `.env`; the runtime derives the requester from the gateway event and authorizes every call again:

- Operators and viewers can do assigned work only inside enabled tools and allowed folders. They must not change global config, secrets, models, providers, dashboard auth, roles, folder policies, plugins, MCP servers, toolsets, or gateway settings.
- Managers can act only inside the configured management surface: approval decisions, shared-knowledge approvals allowed by role, and delegated File Access roots.
- Admins can manage governed users, gateway admission, teams, direct file grants, delegated roots, and global folder policies when requested. They cannot use this channel tool to change provider secrets or dashboard credentials.

Corporate and team memory/skill changes are still proposal-first. The skill tells the agent to use `memory(scope="team"|"corporate", ...)` or `skill_manage(scope="team"|"corporate", ...)` with an `approval_note`, not to edit shared knowledge files directly. Server-side governance remains authoritative: if a file operation, dashboard action, or cron approval is denied, the model must ask an authorized manager/admin instead of bypassing the policy.

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

- [docs/admin-onboarding.md](docs/admin-onboarding.md): tenant, roles, gateway identities, folder access, cron approvals, and audit retention.
- [docs/knowledge-governance.md](docs/knowledge-governance.md): corporate, team, and user memory/skill layers plus the approval flow.
- [docs/migration-from-hermes.md](docs/migration-from-hermes.md): guarded import for upstream Hermes tar/tar.gz exports.
- [docs/cron-authorization-panel.md](docs/cron-authorization-panel.md): dashboard and tool approval checkpoints per role or user.
- [docs/observability.md](docs/observability.md): runtime logs, audit JSONL, SIEM webhook export, and current telemetry coverage.

The dashboard also includes an **Onboarding** page with the same admin checklist.

## Migrating From Upstream Hermes

Use guarded migration mode for a Hermes export archive:

```bash
maia import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

This stages memories and skills for review, imports MCP servers disabled by default, copies secrets only into the migration review folder, and preserves Maia governance guardrails. Promote reviewed content into corporate or team knowledge only through the Knowledge approval workflow.

## Observability

Operational logs are available through `maia logs` and the dashboard Logs page. Corporate audit events are written to `<MAIA_HOME>/logs/audit.jsonl` and include governance file denials, knowledge approvals, cron authorization requests/decisions, dashboard access requests/approvals/revocations, dashboard login/logout, dashboard role denials, and mutating dashboard API calls.

```bash
maia logs audit
```

## License

Maia is an AmpliIA distribution that includes upstream Hermes Agent components under the MIT License. Nous Research is credited for the upstream Hermes Agent code as required by the preserved MIT notice in [LICENSE](LICENSE).

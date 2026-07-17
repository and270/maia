---
sidebar_position: 15
title: "Web Dashboard"
description: "Browser-based dashboard for managing configuration, API keys, sessions, logs, analytics, cron jobs, and skills"
---

# Web Dashboard

The web dashboard is a browser-based UI for managing your Maia installation. Instead of editing YAML files or running CLI commands, you can configure settings, manage API keys, and monitor sessions from a clean web interface.

## Quick Start

```bash
maia dashboard
```

This starts a local web server and opens `http://127.0.0.1:9119` in your browser. The dashboard runs entirely on your machine and binds to localhost by default. The plain `maia` command opens this same localhost dashboard and its browser chat; neither command exposes it to another computer by default.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `9119` | Port to run the web server on |
| `--host` | `127.0.0.1` | Bind address |
| `--no-open` | — | Don't auto-open the browser |
| `--insecure` | off | Allow non-localhost binding without `dashboard.auth` (**DANGEROUS** — exposes API keys, config, and server file controls) |
| `--tui` | off | Expose the in-browser Chat tab (embedded `maia --tui` via PTY/WebSocket). Alternatively set `HERMES_DASHBOARD_TUI=1`. |

```bash
# Custom port
maia dashboard --port 8080

# Bind to all interfaces only after dashboard.auth is configured
maia dashboard --host 0.0.0.0

# Start without opening browser
maia dashboard --no-open
```

## Protected Intranet or Public Serving

The dashboard is an administrative surface, not the normal employee interface. Most users should talk to Maia through a configured gateway; expose the dashboard only to admins, auditors, managers, or delegated team leads who need web administration.

The dashboard can read and change `.env`, `config.yaml`, server folder policies, cron jobs, knowledge approvals, plugins, and model settings. Maia refuses to bind the dashboard to a non-loopback interface unless protected dashboard auth is configured, unless the operator explicitly uses `--insecure`.

You can usually leave it local. From an authenticated private gateway conversation, a system admin can ask Maia to manage admitted users, roles, teams, direct grants, delegated roots, and folder policies. Maia derives the requester from the message and rechecks Governance on every action. Team managers stay limited to delegated roots, and provider secrets/dashboard credentials are not exposed to this flow. Governed write approvals can also use the message application's approval controls.

If remote browser access is necessary, [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) is a simple private-network option. For an identity-aware public URL, use an access layer such as [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/) plus [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/choose-application-type/). Keep Maia auth enabled, use TLS, restrict who can reach the upstream, and never treat `--insecure` as a permanent configuration.

Token-based protected mode:

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

Role gates:

| Gate | Allows | Default roles |
|---|---|---|
| Read | sessions, logs, analytics, cron lists, knowledge review | `auditor`, `manager`, `admin` |
| Manage | cron authorization decisions, knowledge approval decisions, and delegated File Access updates | `manager`, `admin` |
| Admin | config, secrets, folder policies, plugin installation/removal, model settings | `admin` |

Channel-token mode is the default built-in path for team leaders:

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

Setup flow: the user runs `/dashboard` in a private/direct channel. Maia creates a pending request in **Dashboard Access** with the authenticated actor key, such as `discord:99887766`, `telegram:987654321`, or `whatsapp:+155****4567`. A system admin approves the request in the dashboard, assigns roles and teams, and can later revoke or restore access. After approval, the user runs `/dashboard` again to receive a one-time token for the normal login form. This flow is for people who need dashboard access; ordinary gateway users can keep using the bot without a dashboard token.

Maia does not provide SSO, VPN, zero-trust networking, or a reverse proxy. It provides trusted-header integration for companies that already operate that access layer. Configure `dashboard.auth.trusted_user_header`, bind Maia to `127.0.0.1` behind the TLS reverse proxy that strips spoofed client headers, then map identities in `governance.users` with keys such as `sso:alice@example.com`. Use `allow_trusted_headers_on_public_bind: true` only when the proxy is the only network path to the dashboard.

Mutating dashboard API calls, login/logout, and denied role checks are written to the audit log when observability audit logging is enabled.

## Prerequisites

The default `hermes-agent` install does not ship the HTTP stack or PTY helper — those are optional extras. The **web dashboard** needs FastAPI and Uvicorn (`web` extra). The **Chat** tab also needs `ptyprocess` to spawn the embedded TUI behind a pseudo-terminal (`pty` extra on POSIX). Install both with:

```bash
pip install 'maia[web,pty]'
```

The `web` extra pulls in FastAPI/Uvicorn; `pty` pulls in `ptyprocess` (POSIX) or `pywinpty` (native Windows — note that the embedded TUI itself still requires WSL). `pip install maia[all]` includes both extras and is the easiest path if you also want messaging/voice/etc.

When you run `maia dashboard` without the dependencies, it will tell you what to install. If the frontend hasn't been built yet and `npm` is available, it builds automatically on first launch.

## Pages

### Status

The landing page shows a live overview of your installation:

- **Agent version** and release date
- **Gateway status** — running/stopped, PID, connected platforms and their state
- **Active sessions** — count of sessions active in the last 5 minutes
- **Recent sessions** — list of the 20 most recent sessions with model, message count, token usage, and a preview of the conversation

The status page auto-refreshes every 5 seconds.

### Chat

The **Chat** tab embeds the full Hermes TUI (the same interface you get from `hermes --tui`) directly in the browser. Everything you can do in the terminal TUI — slash commands, model picker, tool-call cards, markdown streaming, clarify/sudo/approval prompts, skin theming — works identically here, because the dashboard is running the real TUI binary and rendering its ANSI output through [xterm.js](https://xtermjs.org/) with its WebGL renderer for pixel-perfect cell layout.

**How it works:**

- `/api/pty` opens a WebSocket authenticated with the dashboard's session token
- The server spawns `maia --tui` behind a POSIX pseudo-terminal
- Keystrokes travel to the PTY; ANSI output streams back to the browser
- xterm.js's WebGL renderer paints each cell to an integer-pixel grid; mouse tracking (SGR 1006), wide characters (Unicode 11), and box-drawing glyphs all render natively
- Resizing the browser window resizes the TUI via the `@xterm/addon-fit` addon

**Resume an existing session:** from the **Sessions** tab, click the play icon (▶) next to any session. That jumps to `/chat?resume=<id>` and launches the TUI with `--resume`, loading the full history.

**Prerequisites:**

- Node.js (same requirement as `hermes --tui`; the TUI bundle is built on first launch)
- `ptyprocess` — installed by the `pty` extra (`pip install 'maia[web,pty]'`, or `[all]` covers both)
- POSIX kernel (Linux, macOS, or WSL). Native Windows Python is not supported — use WSL.

Close the browser tab and the PTY is reaped cleanly on the server. Re-opening spawns a fresh session.

### Config

A form-based editor for `config.yaml`. All 150+ configuration fields are auto-discovered from `DEFAULT_CONFIG` and organized into tabbed categories:

- **model** — default model, provider, base URL, reasoning settings
- **terminal** — backend (local/docker/ssh/modal), timeout, shell preferences
- **display** — skin, tool progress, resume display, spinner settings
- **agent** — max iterations, gateway timeout, service tier
- **delegation** — subagent limits, reasoning effort
- **memory** — provider selection, context injection settings
- **approvals** — dangerous command approval mode (ask/yolo/deny)
- And more — every section of config.yaml has corresponding form fields

Fields with known valid values (terminal backend, skin, approval mode, etc.) render as dropdowns. Booleans render as toggles. Everything else is a text input.

**Actions:**

- **Save** — writes changes to `config.yaml` immediately
- **Reset to defaults** — reverts all fields to their default values (doesn't save until you click Save)
- **Export** — downloads the current config as JSON
- **Import** — uploads a JSON config file to replace the current values

:::tip
Config changes take effect on the next agent session or gateway restart. The web dashboard edits the same `config.yaml` file that `hermes config set` and the gateway read from.
:::

### API Keys

Manage the `.env` file where API keys and credentials are stored. Keys are grouped by category:

- **LLM Providers** — OpenRouter, Anthropic, OpenAI, DeepSeek, etc.
- **Tool API Keys** — Browserbase, Firecrawl, Tavily, ElevenLabs, etc.
- **Messaging Platforms** — Telegram, Discord, Slack bot tokens, etc.
- **Agent Settings** — non-secret env vars like `API_SERVER_ENABLED`

Each key shows:
- Whether it's currently set (with a redacted preview of the value)
- A description of what it's for
- A link to the provider's signup/key page
- An input field to set or update the value
- A delete button to remove it

Advanced/rarely-used keys are hidden by default behind a toggle.

### Sessions

Browse and inspect all agent sessions. Each row shows the session title, source platform icon (CLI, Telegram, Discord, Slack, cron), model name, message count, tool call count, and how long ago it was active. Live sessions are marked with a pulsing badge.

- **Search** — full-text search across all message content using FTS5. Results show highlighted snippets and auto-scroll to the first matching message when expanded.
- **Expand** — click a session to load its full message history. Messages are color-coded by role (user, assistant, system, tool) and rendered as Markdown with syntax highlighting.
- **Tool calls** — assistant messages with tool calls show collapsible blocks with the function name and JSON arguments.
- **Delete** — remove a session and its message history with the trash icon.

### Logs

View agent, gateway, and error log files with filtering and live tailing.

- **File** — switch between `agent`, `errors`, and `gateway` log files
- **Level** — filter by log level: ALL, DEBUG, INFO, WARNING, or ERROR
- **Component** — filter by source component: all, gateway, agent, tools, cli, or cron
- **Lines** — choose how many lines to display (50, 100, 200, or 500)
- **Auto-refresh** — toggle live tailing that polls for new log lines every 5 seconds
- **Color-coded** — log lines are colored by severity (red for errors, yellow for warnings, dim for debug)

### Analytics

Usage and cost analytics computed from session history. Select a time period (7, 30, or 90 days) to see:

- **Summary cards** — total tokens (input/output), cache hit percentage, total estimated or actual cost, and total session count with daily average
- **Daily token chart** — stacked bar chart showing input and output token usage per day, with hover tooltips showing breakdowns and cost
- **Daily breakdown table** — date, session count, input tokens, output tokens, cache hit rate, and cost for each day
- **Per-model breakdown** — table showing each model used, its session count, token usage, and estimated cost

### Cron

Create and manage scheduled cron jobs that run agent prompts on a recurring schedule.

- **Create** — fill in a name (optional), prompt, cron expression (e.g. `0 9 * * *`), and delivery target (local, Telegram, Discord, Slack, or email)
- **Job list** — each job shows its name, prompt preview, schedule expression, state badge (enabled/paused/error), delivery target, last run time, and next run time
- **Pause / Resume** — toggle a job between active and paused states
- **Trigger now** — immediately execute a job outside its normal schedule
- **Delete** — permanently remove a cron job

### File Access

Manage the server-side folder policies that bound what Maia can read, search, write, patch, or delete. The page saves to `<MAIA_HOME>/config.yaml` under `governance`; the dashboard is the normal way to edit it.

Governance is organized as **People → Teams → File access → Approvals → Settings**. People supports select-only team assignment and direct per-person paths. Teams supports creation, membership, team paths, and delegated management roots. Every direct grant offers **No write**, **Direct write**, or **Write after approval**. New approval-mode grants show governed manager/admin identities—not roles—and cannot be saved until at least one person is selected. A selected manager can inspect and execute the reviewed edit on that path; administrators have global file access. Existing role-based YAML remains compatible. File access opens directly on the policy list with **Add policy** and retains advanced role, deny, and named write-approver fields.

Saving a grant, revocation, read/write change, or approval-mode change replaces the affected gateway sandbox when the user's next gateway request starts. Users do not need a new chat thread and administrators do not need to restart the gateway. The page reports Docker sandbox readiness separately: a saved grant can be valid while secure terminal/code execution is temporarily unavailable, in which case Maia changes no files through those tools and instructs the requester to retry after the runtime is restored.

There is one File Access page. The logged-in dashboard actor determines what it shows:

- **System admins** manage registered teams, global shared folders, sensitive department folders, role-wide grants, and delegated team roots.
- **Team leaders** can use the same page after a private `/dashboard` token, or trusted-header login from an existing company identity layer, but only for folders under a delegated team root such as `/srv/company/marketing`.
- **Operators** normally do not use this page. They use CLI or gateway channels, and file tools are constrained by the policies saved here.

Before using the page:

1. Users who need dashboard or delegated file administration run `/dashboard` in a private channel.
2. An admin creates the required teams in **Governance → Teams**, then approves the requests with roles and registered teams.
3. The approved mapping is saved under `governance.users`, for example `roles: [operator]` and `teams: [marketing]`.

System admin workflow:

1. Open **People** to manage roles, team membership, and individual paths.
2. Open **Teams** to create teams, add people, grant team paths, and optionally delegate a management root.
3. Open **File Access** for advanced role, deny, and write-approval rules.
4. Save and test with real approved users.

Team leader workflow:

1. Open the same dashboard URL.
2. Confirm the page shows the expected managed team badge and delegated root.
3. Click **Add policy** and set a **Server path** below the delegated root.
4. Use **Read teams** / **Write teams** for team-wide grants or **Read users** / **Write users** for named users.
5. Leave **Recursive directory policy** on for folders; turn it off for one exact file, such as a read-only brand guideline PDF.
6. Save and ask the user to retry the file operation.

Team leaders cannot edit another team's root, grant role-wide access such as `read_roles: [viewer]`, or reference users outside the managed team unless they also have system-admin dashboard access.

Example backing YAML in `<MAIA_HOME>/config.yaml`:

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
6. Unmatched paths and matching policies without an applicable grant are denied.

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

### Skills

Browse, search, and toggle skills and toolsets. Skills are loaded from `~/.maia/skills/` and grouped by category.

- **Search** — filter skills and toolsets by name, description, or category
- **Category filter** — click category pills to narrow the list (e.g. MLOps, MCP, Red Teaming, AI)
- **Toggle** — enable or disable individual skills with a switch. Changes take effect on the next session.
- **Toolsets** — a separate section shows built-in toolsets (file operations, web browsing, etc.) with their active/inactive status, setup requirements, and list of included tools

:::warning Security
The web dashboard reads and writes `.env` and `config.yaml`, including API keys, governance roles, and server folder policies. It binds to `127.0.0.1` by default. Before binding to `0.0.0.0` or any intranet/public address, enable `dashboard.auth`, use TLS or a private network boundary, and keep `--insecure` for temporary trusted-network testing only.
:::

## `/reload` Slash Command

The dashboard PR also adds a `/reload` slash command to the interactive CLI. After changing API keys via the web dashboard (or by editing `.env` directly), use `/reload` in an active CLI session to pick up the changes without restarting:

```
You → /reload
  Reloaded .env (3 var(s) updated)
```

This re-reads `~/.maia/.env` into the running process's environment. Useful when you've added a new provider key via the dashboard and want to use it immediately.

## REST API

The web dashboard exposes a REST API that the frontend consumes. You can also call these endpoints directly for automation:

### GET /api/status

Returns agent version, gateway status, platform states, and active session count.

### GET /api/sessions

Returns the 20 most recent sessions with metadata (model, token counts, timestamps, preview).

### GET /api/config

Returns the current `config.yaml` contents as JSON.

### GET /api/config/defaults

Returns the default configuration values.

### GET /api/config/schema

Returns a schema describing every config field — type, description, category, and select options where applicable. The frontend uses this to render the correct input widget for each field.

### PUT /api/config

Saves a new configuration. Body: `{"config": {...}}`.

### GET /api/env

Returns all known environment variables with their set/unset status, redacted values, descriptions, and categories.

### PUT /api/env

Sets an environment variable. Body: `{"key": "VAR_NAME", "value": "secret"}`.

### DELETE /api/env

Removes an environment variable. Body: `{"key": "VAR_NAME"}`.

### GET /api/sessions/\{session_id\}

Returns metadata for a single session.

### GET /api/sessions/\{session_id\}/messages

Returns the full message history for a session, including tool calls and timestamps.

### GET /api/sessions/search

Full-text search across message content. Query parameter: `q`. Returns matching session IDs with highlighted snippets.

### DELETE /api/sessions/\{session_id\}

Deletes a session and its message history.

### GET /api/logs

Returns log lines. Query parameters: `file` (agent/errors/gateway), `lines` (count), `level`, `component`.

### GET /api/analytics/usage

Returns token usage, cost, and session analytics. Query parameter: `days` (default 30). Response includes daily breakdowns and per-model aggregates.

### GET /api/cron/jobs

Returns all configured cron jobs with their state, schedule, and run history.

### POST /api/cron/jobs

Creates a new cron job. Body: `{"prompt": "...", "schedule": "0 9 * * *", "name": "...", "deliver": "local"}`.

### POST /api/cron/jobs/\{job_id\}/pause

Pauses a cron job.

### POST /api/cron/jobs/\{job_id\}/resume

Resumes a paused cron job.

### POST /api/cron/jobs/\{job_id\}/trigger

Immediately triggers a cron job outside its schedule.

### DELETE /api/cron/jobs/\{job_id\}

Deletes a cron job.

### GET /api/skills

Returns all skills with their name, description, category, and enabled status.

### PUT /api/skills/toggle

Enables or disables a skill. Body: `{"name": "skill-name", "enabled": true}`.

### GET /api/tools/toolsets

Returns all toolsets with their label, description, tools list, and active/configured status.

## CORS

The web server restricts CORS to localhost origins only:

- `http://localhost:9119` / `http://127.0.0.1:9119` (production)
- `http://localhost:3000` / `http://127.0.0.1:3000`
- `http://localhost:5173` / `http://127.0.0.1:5173` (Vite dev server)

If you run the server on a custom port, that origin is added automatically.

## Development

If you're contributing to the web dashboard frontend:

```bash
# Terminal 1: start the backend API
maia dashboard --no-open

# Terminal 2: start the Vite dev server with HMR
cd web/
npm install
npm run dev
```

The Vite dev server at `http://localhost:5173` proxies `/api` requests to the FastAPI backend at `http://127.0.0.1:9119`.

The frontend is built with React 19, TypeScript, Tailwind CSS v4, and shadcn/ui-style components. Production builds output to `hermes_cli/web_dist/` which the FastAPI server serves as a static SPA.

## Automatic Build on Update

When you run `maia update`, the web frontend is automatically rebuilt if `npm` is available. This keeps the dashboard in sync with code updates. If `npm` isn't installed, the update skips the frontend build and `maia dashboard` will build it on first launch.

## Themes & plugins

The dashboard ships with six built-in themes and can be extended with user-defined themes, plugin tabs, and backend API routes — all drop-in, no repo clone needed.

**Switch themes live** from the header bar — click the palette icon next to the language switcher. Selection persists to `config.yaml` under `dashboard.theme` and is restored on page load.

Built-in themes:

| Theme | Character |
|-------|-----------|
| **Hermes Teal** (`default`) | Dark teal + cream, system fonts, comfortable spacing |
| **Hermes Teal (Large)** (`default-large`) | Same as default with 18px text and roomier spacing |
| **Midnight** (`midnight`) | Deep blue-violet, Inter + JetBrains Mono |
| **Ember** (`ember`) | Warm crimson + bronze, Spectral serif + IBM Plex Mono |
| **Mono** (`mono`) | Grayscale, IBM Plex, compact |
| **Cyberpunk** (`cyberpunk`) | Neon green on black, Share Tech Mono |
| **Rosé** (`rose`) | Pink + ivory, Fraunces serif, spacious |

To build your own theme, add a plugin tab, inject into shell slots, or expose plugin-specific REST endpoints, see **[Extending the Dashboard](./extending-the-dashboard)** — the complete guide covers:

- Theme YAML schema — palette, typography, layout, assets, componentStyles, colorOverrides, customCSS
- Layout variants — `standard`, `cockpit`, `tiled`
- Plugin manifest, SDK, shell slots, page-scoped slots (inject widgets into built-in pages without overriding them), backend FastAPI routes
- A full combined theme-plus-plugin walkthrough (Strike Freedom cockpit demo)
- Discovery, reload, and troubleshooting

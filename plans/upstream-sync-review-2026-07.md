# Upstream Sync Review — hermes-agent → Maia (2026-07-02)

Maia diverged from NousResearch/hermes-agent at merge-base `04193cf7` (2026-05-07).
Since then upstream added **6,614 commits** (~1.08M insertions across ~5,000 files);
Maia added 19 local commits (governance, RBAC, corporate dashboard, rename).

Upstream remote is configured as `upstream` (https://github.com/NousResearch/hermes-agent.git).
Refresh with `git fetch upstream`. Diff any area with:
`git log --oneline 04193cf7..upstream/main -- <path>`.

A wholesale merge is **not realistic** — upstream refactored `run_agent.py` from ~14.6k
to ~6k lines across 16+ new modules, repinned every dependency, and rewrote large parts
of the dashboard we forked. The strategy is selective porting, security first.

---

## Tier 1 — Security fixes (port first, mostly cherry-pickable)

These close real vulnerabilities directly relevant to a multi-user corporate deployment:

| Fix | Upstream ref(s) | Files | Notes |
|---|---|---|---|
| `/resume` + `/sessions` IDOR: sessions now scoped to caller origin/user (incl. `user_id_alt` for Signal/Feishu) | `c4f278c02`, `5b3f06425`, +6 related | `gateway/slash_commands.py` | Cross-user session hijack in shared groups. We modified nearby code — cherry-pick the series in order. |
| Fail-closed session authz + profile-aware multiplexing; authz before auto-resume; pairing-as-grant | `bb304b491`, `0de67ad60`, `1bfe08145`, `d3c866746` | `gateway/session.py`, `gateway/run.py` | Both files locally modified — manual review needed. |
| Credential/env isolation: strip `GOOGLE_APPLICATION_CREDENTIALS`, `HERMES_SESSION_*` etc. from spawned processes; token redaction | #56582 area | `agent/auxiliary_client.py`, subprocess helpers | We modified `auxiliary_client.py`. |
| Approval hardening: shell-collapse/brace-group/abbreviated-flag bypasses, Windows destructive commands (`Remove-Item`/`ri`), heredoc, NFKC homograph folding; new threat-pattern engine | `74e59b8b`, `b4342a83b`, `4b92a8cd3`, `3b2bb30c5`, `060779bb7` | `agent/approval.py`, new `tools/threat_patterns.py` | High governance value; medium conflict. |
| File-safety expansion (+581 lines): multiple write-safe roots, more credential paths blocked (`.env`, OAuth stores, `bws_cache.json`) | — | `agent/file_safety.py` | **High conflict** — this file implements our folder-policy governance. Port the blocked-paths list even if we keep our own root logic. |
| Browser SSRF/private-network guards: re-check after redirects/navigation, cloud-metadata floor, CDP token redaction | `0a7561651`, `4612ee946`, `500c2b1e4` | browser tools, gateway media paths | Low conflict. |
| Cron fail-closed validator; block `base_url` credential exfil via cron model config; auth required on `/health/detailed` | `1b7e781d2`, `b24708eda`, `2d8d08cae` | `cron/scheduler.py`, `gateway/run.py` | Both locally modified. |
| Plugin tool-override consent: plugins can no longer silently replace built-in tools; enable-time consent | `310122231`, `179eb8c2a`, `12f5624a7`, `bff61f558` | `hermes_cli/tools_config.py` | Directly strengthens our governance story. |
| Dashboard plugin backend import restricted to bundled plugins (RCE mitigation) | `8845f33` | plugins | Low conflict. |
| CVE dependency floors: aiohttp ≥3.14.0, Starlette (CVE-2026-48710), cryptography floor | `6c37b2c78`, `db57cbbaf` | pyproject | Can apply floors without adopting the full repin. |
| ACP: editor file edits now require explicit approval + session provenance for audit | `9592e595a`, `777dc9da6` | `acp_adapter/` | We modified `acp_adapter/server.py`. |
| Session/message-ID durability (data loss on resume) | `e4c6d1b22`, `f049227f3` | state persistence | Reliability, not security, but cheap. |

## Tier 2 — High value for Maia's corporate/governance focus

- **Dashboard auth provider plugins**: self-hosted **OIDC** (Keycloak etc.), **BasicAuth/LDAP**, generic API-token auth (`f57ce341`, `acb0e2ba`, `cb9cb6ba1`). Fits our SSO/trusted-header story — but `hermes_cli/web_server.py` had ~13.8k lines of upstream churn vs. our heavy local changes; port the provider abstraction, not the file.
- **Profile & multi-user isolation**: per-session profile switching, profile-scoped credentials (gateway multiplex phase 2, fail-closed), profile-scoped memory/skills (`96552c31e`, `8a45ce2dd`). Overlaps conceptually with our roles/teams — decide whether upstream "profiles" become an internal layer under our RBAC or stay unused.
- **Supply-chain hardening**: exact `==` pins for all direct deps + lazy provider deps (`tools/lazy_deps.py`), core deps cut ~80→~40. Very high governance value, very high conflict (regen `uv.lock`). Worth adopting deliberately as its own task.
- **Observability/telemetry hooks**: middleware execution intercepts + observer-grade telemetry (`2e0c9083`, `0d9b7132`) — direct fit for corporate audit logging.
- **`run_agent.py` modularization** (16+ new modules: `agent/agent_init.py`, `conversation_loop.py`, `tool_executor.py`, `system_prompt.py`, …). Not a feature, but every future port gets harder until we absorb it. Biggest single merge effort.
- **Compression/context durability**: in-place compaction, lock-lease refresh, persisted backoff, interrupt queueing during compression — matters for long-running gateway sessions.
- **Per-channel/session model & system-prompt overrides** with precedence session > channel > global (`c43aa6301`, `30e947e0a`) — a governance control surface for free.
- **Docker s6 supervision rework** + UID/GID validation hardening (`476875acb` series) — if we deploy via Docker, this is the supported path now.
- **`hermes serve` headless backend** (`dff491a2b`) — desktop/dashboard now talk to a standalone backend; relevant to how we serve the corporate dashboard.

## Tier 3 — Nice to have (port on demand)

- Providers: Google **Vertex AI** OAuth2 (`c73e74386`), xAI Grok OAuth, Microsoft **Entra ID** (Azure Foundry) — port if the company uses those clouds.
- Cron: blueprint/suggestion catalog, in-channel continuable delivery for Slack, per-profile job isolation + lifecycle guard.
- New tools: `tool_search.py`, `computer_use/` cross-platform module, `read_extract.py` (office/notebook extraction), `write_approval.py`, video/X-search tools.
- Slack Block Kit table rendering; WhatsApp Cloud API migration; Matrix E2EE hardening; Telegram reliability series.
- `/learn` skill distillation, skills AST audit, skill bundles; MoA presets; `/billing`–`/credits`; memory-graph/journey UI; new optional-skills batch (Stripe, OSINT, web-pentest, OpenHands, …).
- Delegation improvements: parallel subagent fan-out, unified concurrency caps.
- i18n: 16 locales incl. gateway command localization.

## Skip / not applicable

- `apps/` desktop app (Tauri/Electron, ~850 files) — upstream-infrastructure-tied (OAuth, updater). Revisit only if a native corporate client becomes a goal.
- Upstream `website/` marketing/docs churn (we rebranded ours), Nous portal/credits integrations, pet engine, themes, journey polish.

## Suggested order of work

1. Tier 1 security cherry-picks that don't touch our modified files (browser guards, threat patterns, plugin consent, dashboard plugin import, CVE floors).
2. Tier 1 fixes on shared files (`gateway/session.py`, `slash_commands.py`, `file_safety.py`, `auxiliary_client.py`, cron) — manual, one series at a time, with tests.
3. Decide the two strategic questions: adopt upstream **dependency pinning** model? map upstream **profiles** under our RBAC?
4. Absorb the `run_agent.py` modularization (unlocks cheaper future syncs).
5. Tier 2/3 features as needed.

## Conflict hot spots (fork-modified AND heavily changed upstream)

`run_agent.py` (refactored away), `agent/auxiliary_client.py` (+3.5k lines), `agent/file_safety.py`,
`agent/prompt_builder.py`, `gateway/run.py`, `gateway/session.py`, `gateway/config.py`,
`hermes_cli/web_server.py`, `hermes_cli/auth.py`, `hermes_cli/tools_config.py`,
`cron/scheduler.py`, `cron/jobs.py`, `acp_adapter/server.py`, `pyproject.toml`/`uv.lock`,
`ui-tui/` and `web/` (our dashboard vs. upstream admin panel — integrate by endpoint, don't merge UI).

---
slug: /
sidebar_position: 0
title: "Coorporate Hermes Documentation"
description: "AmpliIA's private one-tenant corporate assistant distribution with governance, knowledge approvals, guarded migration, cron approvals, and observability."
hide_table_of_contents: true
displayed_sidebar: docs
---

# Coorporate Hermes

Coorporate Hermes is an AmpliIA distribution for private one-tenant company deployments. It keeps the upstream Hermes Agent foundation and adds role-aware governance, governed corporate/team/user knowledge layers, guarded folder access, migration from upstream Hermes exports, human approval checkpoints for cron, and corporate audit logging.

<div style={{display: 'flex', gap: '1rem', marginBottom: '2rem', flexWrap: 'wrap'}}>
  <a href="/docs/enterprise/admin-onboarding" style={{display: 'inline-block', padding: '0.6rem 1.2rem', backgroundColor: '#FFD700', color: '#07070d', borderRadius: '8px', fontWeight: 600, textDecoration: 'none'}}>Admin Onboarding →</a>
  <a href="https://ampliia.com/en/" style={{display: 'inline-block', padding: '0.6rem 1.2rem', border: '1px solid rgba(255,215,0,0.2)', borderRadius: '8px', textDecoration: 'none'}}>AmpliIA</a>
</div>

## What is Coorporate Hermes?

It is a private corporate assistant for a single organization. Administrators map gateway users to roles, define folder policies, require approvals for sensitive scheduled workflows, and review audit events before connecting external observability systems.

## Quick Links

| | |
|---|---|
| 🛡️ **[Admin Onboarding](/docs/enterprise/admin-onboarding)** | Configure tenant, users, roles, folders, cron approvals, and audit logs |
| 🧠 **[Knowledge Governance](/docs/enterprise/knowledge-governance)** | Manage corporate, team, and user memory/skill layers with approvals |
| 🔁 **[Migrate From Hermes](/docs/enterprise/migration-from-hermes)** | Bring memories, skills, and MCP configuration from upstream Hermes exports safely |
| ⏱️ **[Cron Authorization](/docs/enterprise/cron-authorization-panel)** | Use role/user approval checkpoints for scheduled jobs |
| 📜 **[Observability](/docs/enterprise/observability)** | Runtime logs, audit JSONL, SIEM export, and current coverage |
| 🚀 **[Installation](/docs/getting-started/installation)** | Install on Linux, macOS, or WSL2 |
| 📖 **[Quickstart Tutorial](/docs/getting-started/quickstart)** | Your first conversation and key features to try |
| 🗺️ **[Learning Path](/docs/getting-started/learning-path)** | Find the right docs for your experience level |
| ⚙️ **[Configuration](/docs/user-guide/configuration)** | Config file, providers, models, and options |
| 💬 **[Messaging Gateway](/docs/user-guide/messaging)** | Set up Telegram, Discord, Slack, WhatsApp, Teams, or more |
| 🔧 **[Tools & Toolsets](/docs/user-guide/features/tools)** | 68 built-in tools and how to configure them |
| 🧠 **[Memory System](/docs/user-guide/features/memory)** | Persistent memory that grows across sessions |
| 📚 **[Skills System](/docs/user-guide/features/skills)** | Procedural memory the agent creates and reuses |
| 🔌 **[MCP Integration](/docs/user-guide/features/mcp)** | Connect to MCP servers, filter their tools, and extend Hermes safely |
| 🧭 **[Use MCP with Hermes](/docs/guides/use-mcp-with-hermes)** | Practical MCP setup patterns, examples, and tutorials |
| 🎙️ **[Voice Mode](/docs/user-guide/features/voice-mode)** | Real-time voice interaction in CLI, Telegram, Discord, and Discord VC |
| 🗣️ **[Use Voice Mode with Hermes](/docs/guides/use-voice-mode-with-hermes)** | Hands-on setup and usage patterns for Hermes voice workflows |
| 🎭 **[Personality & SOUL.md](/docs/user-guide/features/personality)** | Define Hermes' default voice with a global SOUL.md |
| 📄 **[Context Files](/docs/user-guide/features/context-files)** | Project context files that shape every conversation |
| 🔒 **[Security](/docs/user-guide/security)** | Command approval, authorization, container isolation |
| 💡 **[Tips & Best Practices](/docs/guides/tips)** | Quick wins to get the most out of Hermes |
| 🏗️ **[Architecture](/docs/developer-guide/architecture)** | How it works under the hood |
| ❓ **[FAQ & Troubleshooting](/docs/reference/faq)** | Common questions and solutions |

## Key Features

- **Corporate governance** — role-aware users, folder policies, gateway session isolation, and default-deny production patterns
- **Knowledge governance** — corporate/team/user memories and skills, with shared changes gated by human approval
- **Guarded migration** — import upstream Hermes tar/tar.gz exports without overwriting corporate guardrails
- **Cron approvals** — scheduled jobs can pause for role or user approval before execution
- **Audit trail** — append-only JSONL events for governance denials, knowledge approvals, and cron authorization decisions
- **A closed learning loop** — Agent-curated memory with periodic nudges, autonomous skill creation, skill self-improvement during use, FTS5 cross-session recall with LLM summarization, and [Honcho](https://github.com/plastic-labs/honcho) dialectic user modeling
- **Runs anywhere, not just your laptop** — 6 terminal backends: local, Docker, SSH, Daytona, Singularity, Modal. Daytona and Modal offer serverless persistence — your environment hibernates when idle, costing nearly nothing
- **Lives where you do** — CLI, Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Mattermost, Email, SMS, DingTalk, Feishu, WeCom, BlueBubbles, Home Assistant, Microsoft Teams — 15+ platforms from one gateway
- **AmpliIA distribution** — Coorporate Hermes is maintained by [AmpliIA](https://ampliia.com/en/) and preserves upstream Nous Research MIT attribution for Hermes Agent-derived components
- **Scheduled automations** — Built-in cron with delivery to any platform
- **Delegates & parallelizes** — Spawn isolated subagents for parallel workstreams. Programmatic Tool Calling via `execute_code` collapses multi-step pipelines into single inference calls
- **Open standard skills** — Compatible with [agentskills.io](https://agentskills.io). Skills are portable, shareable, and community-contributed via the Skills Hub
- **Full web control** — Search, extract, browse, vision, image generation, TTS
- **MCP support** — Connect to any MCP server for extended tool capabilities
- **Research-ready foundation** — Batch processing, trajectory export, and RL training capabilities inherited from upstream Hermes Agent

## For LLMs and coding agents

Machine-readable entry points to this documentation:

- **[`/llms.txt`](/llms.txt)** — curated index of every doc page with short descriptions. ~17 KB, safe to load into an LLM context.
- **[`/llms-full.txt`](/llms-full.txt)** — every doc page concatenated into a single markdown file for one-shot ingestion. ~1.8 MB.

Both files also resolve at `/docs/llms.txt` and `/docs/llms-full.txt`. Generated fresh on every deploy.

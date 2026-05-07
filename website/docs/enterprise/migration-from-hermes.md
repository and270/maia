---
title: "Migration From Hermes"
description: "Safely migrate upstream Hermes export archives into Coorporate Hermes without bypassing corporate guardrails."
---

# Migration From Upstream Hermes

Use guarded migration mode for upstream Hermes `.tar`, `.tar.gz`, `.tgz`, or `.zip` exports:

```bash
coorporate import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

The command preserves the active Coorporate Hermes configuration and stages imported content under:

```text
<HERMES_HOME>/migration/hermes-import-*/
```

## Imported Safely

- `memories/` is staged for review.
- `skills/` is staged under `skills-review/`.
- `.env`, `auth.json`, and `mcp-tokens/` are copied only into the review folder.
- `mcp_servers` are imported disabled, with secret-like values redacted.
- A `report.json` lists imported, reviewed, and skipped entries.

## Not Activated Automatically

- Governance and security settings are not overwritten.
- Corporate/team knowledge layers are not changed automatically.
- Imported skills are not activated.
- Imported MCP servers are not enabled.
- Old secrets are not copied into active `.env`.
- Session history is not restored as corporate active history.

Review staged files, re-enter secrets through the Keys panel, and enable MCP servers only after inspecting commands, URLs, env requirements, and tool filters. Promote reviewed company or department content into corporate/team memory or skills only through the Knowledge approval workflow.

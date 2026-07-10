---
title: "Knowledge Governance"
description: "Corporate, team, and user memory/skill layers plus human approval for shared knowledge in Maia."
---

# Knowledge Governance

Maia separates memory and skills into three layers:

| Layer | Path | Loaded For | Change Control |
|---|---|---|---|
| Corporate memory | `<MAIA_HOME>/corporate/memories/MEMORY.md` | Every conversation | Human approval |
| Corporate skills | `<MAIA_HOME>/corporate/skills/` | Every conversation | Human approval |
| Team memory | `<MAIA_HOME>/teams/<team>/memories/MEMORY.md` | Assigned team users | Human approval |
| Team skills | `<MAIA_HOME>/teams/<team>/skills/` | Assigned team users | Human approval |
| Gateway user memory | `<MAIA_HOME>/users/<platform-hash>/memories/` | One `platform:user_id` | Isolated user flow |
| Gateway user skills | `<MAIA_HOME>/users/<platform-hash>/skills/` | One `platform:user_id` | Isolated personal skill flow |
| Local/CLI memory | `<MAIA_HOME>/memories/` | Local profile | Legacy-compatible flow |
| Local/CLI skills | `<MAIA_HOME>/skills/` | Local profile and gateway baseline | Legacy-compatible flow |

Corporate and team knowledge is injected before user memory and user skills. If the layers conflict, approved corporate/team knowledge wins.

The filesystem segment is a stable hash of `platform:user_id`, so raw external IDs are not embedded in directory names. Cron jobs restore their creator identity and therefore reuse that creator's personal memory and skills.

## Teams

Assign team membership in `governance.users`:

```yaml
governance:
  enabled: true
  users:
    "slack:U123":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
```

## Approval Policy

```yaml
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
```

The agent can propose corporate/team memory or skill changes, but the files are changed only after an authorized human approves the request in the dashboard Knowledge panel or API.

Approvals are stored at:

```text
<MAIA_HOME>/knowledge/approvals.json
```

Approved changes are written to the shared knowledge directory and recorded in the audit log.

## Migration

Guarded migration from upstream Hermes exports stages memories and skills for review. It does not automatically promote them into corporate or team layers. Promote only reviewed content through the same Knowledge approval workflow used for new shared knowledge.

# Knowledge Governance

Coorporate Hermes separates memory and skills into three practical layers so company-wide instructions do not get mixed with personal preferences.

## Layers

| Layer | Path | Loaded For | How It Changes |
|---|---|---|---|
| Corporate memory | `<HERMES_HOME>/corporate/memories/MEMORY.md` | Every conversation | Human approval required |
| Corporate skills | `<HERMES_HOME>/corporate/skills/` | Every conversation | Human approval required |
| Team memory | `<HERMES_HOME>/teams/<team>/memories/MEMORY.md` | Users assigned to that team | Human approval required |
| Team skills | `<HERMES_HOME>/teams/<team>/skills/` | Users assigned to that team | Human approval required |
| User memory | `<HERMES_HOME>/memories/` | Current user/profile | Existing user-level memory flow |
| User skills | `<HERMES_HOME>/skills/` | Current user/profile | Existing skill flow |

Corporate and team knowledge is injected before user memory and user skills. If there is a conflict, the approved corporate/team layer wins.

## Assign Teams

Teams are assigned in `governance.users`:

```yaml
governance:
  enabled: true
  users:
    "slack:U123":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
```

A user can belong to more than one team.

## Approval Roles

Shared knowledge edits are proposal-first. The agent can propose them with the memory or skill tools, but the files are changed only after a human approves the request in the dashboard Knowledge panel or the API.

```yaml
knowledge:
  enabled: true
  corporate:
    approver_roles: [admin]
  team:
    approver_roles: [manager, admin]
```

Role hierarchy is honored. With the default hierarchy `viewer < operator < manager < admin`, an `admin` can approve manager-level team knowledge.

## Agent Tool Behavior

User-level memory and skills keep the original behavior:

```python
memory(action="add", target="memory", content="User prefers concise summaries.")
skill_manage(action="create", name="debugging-runbook", content="...")
```

Corporate and team writes create pending approvals:

```python
memory(
  action="add",
  target="memory",
  scope="corporate",
  content="All customer escalations use the incident rotation.",
  approval_note="Approved by support leadership.",
)

skill_manage(
  action="create",
  name="finance-close",
  scope="team",
  team="finance",
  content="---\nname: finance-close\ndescription: Finance close checklist.\n---\n...",
  approval_note="Finance wants this checklist available to the whole team.",
)
```

Approvals are stored at:

```text
<HERMES_HOME>/knowledge/approvals.json
```

Approved changes are written to the corporate/team memory or skill path and recorded in the audit trail.

## Dashboard Flow

1. Open **Onboarding** to confirm users, roles, and teams.
2. Open **Knowledge** to inspect corporate, team, and user layer paths.
3. Review pending shared memory and skill proposals.
4. Approve or deny each proposal. Denials should include a short reason.
5. Check **Logs** and select the audit log when you need approval evidence.

## Migration From Hermes

Guarded migration from upstream Hermes exports stages imported memories and skills for review. It does not promote them automatically into corporate or team layers. After review, administrators should promote only the approved entries through the Knowledge approval workflow so imported content respects the same guardrails as newly created content.

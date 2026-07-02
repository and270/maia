# Migrating From Upstream Hermes

Maia can migrate the export archive produced by upstream Hermes without treating it as a full trusted restore. This matters because corporate deployments have additional guardrails: tenant identity, user roles, folder policies, governed corporate/team knowledge, cron approvals, and audit logging.

## Supported Archives

Use guarded migration mode for `.tar`, `.tar.gz`, `.tgz`, or `.zip` exports:

```bash
maia import ~/Downloads/hermes-export.tar.gz --from-hermes-export
```

Full overlay restore remains available only for Maia ZIP backups created by `maia backup`.

## What Migration Does

Guarded migration mode:

- preserves the existing `config.yaml` governance and security settings;
- stages upstream `memories/` under `<MAIA_HOME>/migration/hermes-import-*/memories/`;
- stages upstream `skills/` under `<MAIA_HOME>/migration/hermes-import-*/skills-review/`;
- copies `.env`, `auth.json`, and `mcp-tokens/` only into the review folder;
- reads `mcp_servers` from the imported config, redacts secret-like values, imports the server definitions disabled, and marks them as requiring review;
- writes a `report.json` describing imported, staged, and skipped entries;
- blocks archive path traversal and ignores tar symlinks or special files.

## What Migration Does Not Do

Guarded migration does not:

- overwrite Maia `governance`, `approvals`, `terminal`, or observability settings;
- promote imported memories or skills into corporate/team knowledge layers automatically;
- activate imported skills automatically;
- activate imported MCP servers automatically;
- import old secrets into active `.env`;
- restore sessions as active corporate history.

## Post-Migration Review

1. Open the migration folder printed by the command.
2. Review `report.json`.
3. Read every staged `SKILL.md` before copying approved user-level skills into `<MAIA_HOME>/skills/`.
4. For corporate or team knowledge, use the dashboard Knowledge approval flow instead of copying directly into `<MAIA_HOME>/corporate/` or `<MAIA_HOME>/teams/`.
5. Re-enter secrets through the dashboard Keys page or the managed `.env` workflow.
6. Inspect imported MCP servers in `config.yaml`; only set `enabled: true` after reviewing command, URL, tool filters, and env requirements.
7. Keep `governance.default_file_policy: deny` unless this is a local test profile.

## Promoting Imported Knowledge

Treat upstream export content as user-level material until reviewed:

- import personal preferences into user memory only when they still apply to the current user/profile;
- promote company policies into corporate memory only through approval;
- promote department runbooks into team skills only through approval;
- discard or rewrite old skills that bypass current folder policies, MCP restrictions, or cron approval rules.

See [Knowledge governance](knowledge-governance.md) for the corporate/team/user layer model.

## Troubleshooting

If the command says the archive is not a ZIP, add `--from-hermes-export`. Tar archives are intentionally rejected by full restore mode.

If expected files were skipped, check `report.json`. The migration allowlist is intentionally narrow; files outside memories, skills, MCP config, and secrets-review locations are not activated automatically.

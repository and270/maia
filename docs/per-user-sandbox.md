# Per-user gateway filesystem sandboxes

Maia treats Governance as an always-on security boundary. A user record and
role allow a gateway identity to use the bot; they do not grant filesystem
access. Files and folders are available only through explicit matching
`governance.folder_policies`. No matching policy means deny.

## Enforcement paths

- `read_file`, `search_files`, `write_file`, and `patch` check the current
  gateway actor against folder policies before accessing a path.
- `terminal` and `execute_code` use a dedicated Docker environment keyed by
  the gateway session. The container receives bind mounts only for paths that
  actor may read or write.
- Read grants mount `ro`; write grants mount `rw`. A path whose writes require
  human approval mounts `ro`, forcing changes through the staging workflow.
- Delegated agents resolve to the parent's environment, so delegation cannot
  escape the original user's mount set.
- RPC tool calls made inside `execute_code` inherit the authenticated actor,
  preserving the same authorization checks and audit identity.

The local CLI operator is the bootstrap/break-glass authority and is not put in
a gateway sandbox unless an explicit local Governance identity is configured.

## Fail-closed behavior

Gateway isolation never falls back to the host. Maia forces the per-session
environment to Docker even if the general terminal backend is `local`. If
Docker is missing, stopped, or cannot create the environment, the tool returns
a structured `governance_access_denied` result. The model is instructed not to
try another tool or alternate path and to tell the requester to ask an
authorized manager or administrator.

An empty mount list is intentional and must stay empty. It must not inherit
global `terminal.docker_volumes` settings.

## Path handling

Administrators may paste Windows paths such as
`C:\Users\andre\Documents\Finance` while Maia runs in WSL. Governance
canonicalizes these paths to `/mnt/c/Users/andre/Documents/Finance` before
policy matching and Docker mount construction.

## Persisted configuration

Legacy values are migrated on startup:

```yaml
governance:
  enabled: true
  terminal:
    sandbox:
      enabled: true
```

Neither `enabled` field is a runtime off switch. The dashboard exposes the
enforced posture but does not offer a disable control.

## Operational requirement

The server running a messaging gateway must have a working Docker engine. Test
Docker before rollout and monitor Governance denial/audit events. Keep OS
permissions as defense in depth for especially sensitive data.

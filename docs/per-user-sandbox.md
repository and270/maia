# Per-user gateway filesystem sandboxes

Maia treats Governance as an always-on security boundary. A user record and
role allow a gateway identity to use the bot; they do not grant filesystem
access. Files and folders are available only through explicit matching
`governance.folder_policies`. No matching policy means deny.

## Enforcement paths

- `read_file`, `search_files`, `write_file`, and `patch` check the current
  gateway actor against folder policies before accessing a path.
- `terminal` and `execute_code` use a dedicated Docker or Podman environment keyed by
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
environment to the secure container runtime even if the general terminal backend is `local`. If
Docker or Podman is missing, stopped, or cannot create the environment, the tool returns
a retryable `secure_execution_unavailable` result. This is not a file-policy
denial: the grant remains saved, the command does not run, and no file is
changed. The model tells the requester that an administrator must restore the
secure runtime and that the same request can be retried without a new thread.

An empty mount list is intentional and must stay empty. It must not inherit
global `terminal.docker_volumes` settings.

## Permission changes are immediate

At the beginning of every gateway turn, Maia resolves the actor's current
folder grants. If the effective mount list changed, Maia synchronously removes
the previous governed container before it creates the replacement. This covers
new grants, revocations, read-only to read/write changes, and approval-gated
paths returning to read-only. The user's next gateway request uses the new
policy; a new message thread or gateway restart is not required.

## Path handling

Administrators may paste Windows paths such as
`C:\Users\andre\Documents\Finance` while Maia runs in WSL. Governance
canonicalizes these paths to `/mnt/c/Users/andre/Documents/Finance` before
policy matching and container mount construction.

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

The server running a messaging gateway needs a working Docker or Podman engine
for full governed terminal/code, Office/Python automation, and delegated command
execution. Without it, Maia remains safe in Restricted mode: chat, Governance,
approvals, audit, and path-checked file tools continue, while command-capable
operations return `secure_execution_unavailable`.

Use `maia secure-runtime status` to see why the boundary matters, the exact
consequences, and system-specific steps. Use `maia secure-runtime setup` during
initial setup or later. On Windows/WSL, Docker Desktop must have WSL Integration
enabled for the distribution running Maia. On Linux, rootless Podman is the
preferred path. On macOS, Podman needs a running `podman machine` (Docker Desktop
is also supported). The installer checks this state and `maia update` reports it
without changing system software unattended.

The Governance dashboard reports readiness separately from file authorization.
Test the runtime before rollout and monitor Governance denial/audit events. Keep
OS permissions as defense in depth for especially sensitive data.

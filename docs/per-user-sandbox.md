# Per-user terminal sandboxes (design)

## Problem

Folder policies govern the **file tools** per user. Shell commands and
`execute_code` scripts, however, run in the terminal backend with the host
process's OS permissions — so a command like
`python -c "open('/srv/finance/x','w')..."` or a plain `python script.py` whose
body writes into a governed folder is **not** constrained by the requester's
file grants. Dangerous-command pattern matching is heuristic and cannot be the
boundary (a plain `python script.py` matches nothing).

The airtight fix is to run each gateway user's commands in a container that
**mounts only the folders their governance policy grants** — read-only where
they only have read, read-write where they have write, and nothing else from
the host. Then even an un-flagged command physically cannot see another team's
data.

## Trust boundary

- **In scope:** what a gateway user's shell/`execute_code` can *reach* on the
  host filesystem. The container sees only policy-granted paths.
- **Out of scope:** kernel/container escape hardening beyond what the existing
  Docker backend already does (`--cap-drop ALL`, `--no-new-privileges`,
  `--pids-limit`, optional `--network=none`). This design reuses that backend;
  it does not add new escape defenses.
- **Not a replacement for OS permissions.** For genuinely radioactive data,
  the folder should also be unreadable by the OS account Maia runs under, or
  served by a separate Maia instance. Defense in depth.

## Mechanism this builds on

The terminal backend already supports per-task isolation:

- `register_task_env_overrides(task_id, overrides)` stores a per-task env
  config ([terminal_tool.py](../tools/terminal_tool.py)). RL/benchmark
  environments use it today to give a task its own Docker image.
- `_resolve_container_task_id(task_id)` collapses subagent task_ids to
  `"default"` so they share one container — **except** when an override is
  registered for that task_id, in which case the task_id is honored and gets
  its **own** container. This is exactly the per-user isolation hook: register
  an override keyed by the gateway `session_id` and that session gets a
  dedicated container.
- The gateway main loop already runs each turn as
  `agent.run_conversation(..., task_id=session_id)`
  ([gateway/run.py](../gateway/run.py)), so `session_id` is the task_id.

## Components

### 1. Mount resolver (`agent/sandbox.py`) — implemented

`resolve_sandbox_mounts(actor, config)` turns the actor's folder policies into
Docker `-v host:container:mode` bind specs:

- Enumerate `governance.folder_policies` paths.
- For each existing path: if the actor has **write** access → `rw`; else if
  **read** access → `ro`; else skip.
- **Write-approval folders fail safe to `ro`**: if a path requires staged
  approval for this actor (`file_write_approval_requirement` returns a
  requirement), the shell must not write it directly — it mounts `ro` so the
  only way to change it is the file tool, which stages the change. Approvers
  (for whom the requirement resolves to `None`) get `rw`.
- Container path = host path, so absolute paths inside the container match the
  host and reviewed diffs stay meaningful.
- Default-deny by construction: only explicitly-granted folders are mounted.
  Maia's immutable deny default keeps host authorization aligned with those
  mounts; there is no permissive fallback outside the sandbox.

This function is pure (config + filesystem existence checks only) and fully
unit-tested without Docker.

### 2. Per-task volume plumbing — implemented

The three container-config construction sites read `docker_volumes` (and `cwd`)
from the per-task override when present, falling back to global config:

- [terminal_tool.py](../tools/terminal_tool.py) (shell)
- [file_tools.py](../tools/file_tools.py) (file ops run in the same env)
- [code_execution_tool.py](../tools/code_execution_tool.py) (sandboxed scripts)

Before this change, `register_task_env_overrides` honored `docker_image`/`cwd`
but volumes were always the global set — so per-user mounts could not take
effect. This closes that gap and is independently useful.

### 3. Fail-closed backend guard — implemented

`sandbox_backend_error(env_type, actor)` in [agent/sandbox.py](../agent/sandbox.py)
enforces the safety invariant: when the sandbox is enabled for a **gateway
(non-local) actor** but the backend is not Docker, the terminal and
`execute_code` tools refuse with a clear message rather than run unsandboxed on
the host. The local operator (platform `local`) is the trust authority and is
never sandboxed. Wired into both [terminal_tool.py](../tools/terminal_tool.py)
and [code_execution_tool.py](../tools/code_execution_tool.py) right after the
backend is resolved.

`build_sandbox_overrides(actor)` returns the `register_task_env_overrides`
dict (`docker_volumes` = the resolved mount set, `cwd` = `/workspace`) that the
gateway increment will register.

Consequence: enabling `governance.terminal.sandbox.enabled` today is **safe** —
a gateway session on a non-Docker backend is blocked (fail closed), and on the
Docker backend it runs in the existing (host-isolated) Docker container. It is
not yet **per-user** until the registration increment below lands.

### 4. Gateway registration — remaining increment (needs Docker validation)

When the sandbox is enabled, register the per-user override before
`run_conversation(task_id=session_id)` in `_run_agent`
([gateway/run.py](../gateway/run.py)) and clear it after:

```
register_task_env_overrides(session_id, build_sandbox_overrides(actor=source_actor))
```

`source` (a `SessionSource`) is in scope there, so the actor is built directly
from `source.platform/user_id/user_name` — no reliance on context-var timing.

Subtleties to resolve and validate on a Docker host before this is trusted:

- **Subagent inheritance (important).** `_resolve_container_task_id` collapses
  `delegate_task` subagent task_ids to `"default"`, so a subagent's commands
  would run in the shared default container, **not** the parent's per-user
  sandbox — false isolation. The registration increment must make subagents of
  a sandboxed session resolve to the parent's `session_id` (or register the
  same override for each child), so a delegated command can't escape the mount
  set. This is the main reason the registration is not wired yet: it needs
  container-level validation.
- **Container lifecycle.** One container per active user session; the existing
  idle-cleanup thread reaps them. Cold-start ~1–2s on the first command.
- **Staged approvals interaction.** Approval-gated folders mount `ro`, so a
  shell write fails; the user changes those files via the file tool, which
  stages them host-side and applies after approval. The resolver already
  encodes this.

## Configuration (proposed)

```yaml
governance:
  enabled: true
  terminal:
    sandbox:
      enabled: true          # per-user Docker sandbox for gateway sessions
```

Requires the Docker terminal backend on the server.

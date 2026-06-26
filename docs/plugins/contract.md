# Mere Plugin Contract

Plugins are companion executables. They are not loaded into the `mere.run`
process, and they do not extend the core command tree by mutating it at runtime.

This keeps the base CLI local-first while allowing official bridges to
user-controlled services, machines, and workflow tools.

## Required Commands

Every official plugin exposes:

```text
<plugin> manifest --json
<plugin> doctor
<plugin> plan ...
<plugin> run ...
<plugin> resume <run.json>
<plugin> cleanup <run.json>
```

Provider plugins may expose additional helper commands when they are declared in
the manifest. Helpers must follow the same stdout/stderr and security rules as
the required commands, including dry-run or plan coverage for paid resource
creation.

### `manifest --json`

Prints a manifest matching `contracts/plugin.v1.schema.json`.

The manifest describes:

- plugin name and version
- executable name
- supported commands
- capabilities
- stdout/stderr policy
- security posture

### `doctor`

Checks local readiness without creating paid resources.

Examples:

- required executables
- provider credentials are present
- SSH key exists
- output directories are writable
- optional provider CLI is installed

### `plan`

Writes a dry-run plan and prints a JSON run manifest with status `planned`.

`plan` must show:

- recipe id
- dataset path and pair count
- exact training command
- remote provider settings
- cleanup default
- expected artifact directory

### `run`

Creates resources and executes work.

`run` must write `run.json` before the first paid resource is created. If the
process fails, the plugin must update `run.json` with failure and cleanup status.

### `resume`

Continues or inspects an existing run manifest. A plugin may refuse resume when
the remote resource is already gone, but it must say so in machine-readable
terms.

### `cleanup`

Tears down any remote resource referenced by a run manifest. Cleanup must be
idempotent.

## Streams

- stdout is machine-readable when the command promises JSON or paths.
- stderr is for logs and diagnostics.
- secrets must never appear on either stream.

## Exit Codes

- `0`: command succeeded.
- `1`: expected operator-facing failure.
- `2`: invalid CLI usage.
- `3`: readiness check failed.
- `4`: provider resource failure.
- `5`: cleanup failed.

## Discovery

The future core discovery rule is simple: scan `PATH` for executables named
`mere-*`, call `manifest --json`, then validate the result against
`plugin.v1.schema.json`.

Core discovery should not execute plugin `doctor`, `plan`, or `run`.

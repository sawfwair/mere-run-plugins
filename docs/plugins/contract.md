# Plugin contract

This reference is for plugin authors and automation maintainers. It defines the
process boundary, required provider lifecycle, output streams, and discovery
behavior for official `mere.run` plugins.

Plugins are companion executables. `mere.run` doesn't load them into the core
process or let them mutate the core command tree.

## Implement discovery

An installable plugin provides this command:

```text
PLUGIN_COMMAND manifest --json
```

The command prints a document that conforms to
`contracts/plugin.v1.schema.json`. It describes the plugin identity,
executable, commands, capabilities, output policy, and security posture.

Discovery calls only `manifest --json`. It doesn't call `doctor`, `plan`,
or `run`.

## Implement the provider lifecycle

Every provider plugin provides the following commands:

```text
PLUGIN_COMMAND doctor
PLUGIN_COMMAND plan ...
PLUGIN_COMMAND run ...
PLUGIN_COMMAND resume RUN_MANIFEST
PLUGIN_COMMAND cleanup RUN_MANIFEST
```

Focused local and graph-provider plugins can expose a smaller surface when their
catalog entry and manifest describe it.

### Check readiness with `doctor`

The `doctor` command checks required executables, credentials, paths, and
provider access. It must not create paid resources.

### Preview work with `plan`

The `plan` command validates inputs and writes a dry-run manifest with the
`planned` status. For paid work, the manifest includes the resolved resource
settings, command, expected artifacts, and cleanup policy.

### Execute work with `run`

The `run` command executes a reviewed plan. A provider plugin writes
`run.json` before it creates the first remote resource. After each state
change, it updates the resource, artifact, failure, and cleanup fields.

### Continue work with `resume`

The `resume` command continues or inspects a run manifest. If the provider
resource no longer exists, the command returns that state in a machine-readable
result.

### Remove resources with `cleanup`

The `cleanup` command removes remote resources referenced by a run manifest.
It is idempotent and updates the cleanup state after each attempt.

## Add helper commands

A plugin can expose helper commands in its manifest. A helper that creates paid
resources must provide a plan or dry-run mode. Helper commands follow the same
stream and secret-handling rules as lifecycle commands.

## Write to the correct stream

When a command promises JSON, paths, or newline-delimited JSON (NDJSON), it
writes only that machine-readable value to stdout. It writes diagnostics and
progress to stderr.

A plugin must not write secrets to either stream.

## Return consistent exit codes

Official plugins use these exit codes:

| Code | Meaning |
| ---: | --- |
| `0` | The command succeeded |
| `1` | An expected operator-facing failure occurred |
| `2` | The command or input was invalid |
| `3` | A readiness check failed |
| `4` | A provider resource operation failed |
| `5` | Cleanup failed |

For automation guidance, see [Exit codes](/reference/exit-codes).

## Publish the plugin

Add the package source, manifest, tests, catalog entry, and documentation in one
change. Before you open a pull request, run:

```bash
./scripts/check.sh
corepack pnpm docs:coverage
corepack pnpm docs:build
```

For schema details, see [Contract schemas](/reference/contracts). For resource
rules, see [Provider safety](/operations/provider-safety).

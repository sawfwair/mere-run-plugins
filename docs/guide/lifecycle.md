# Plugin lifecycle

This guide is for users and automation authors who operate manifest-based
plugins. It explains the shared control loop and the exceptions for focused
local commands.

## Inspect a plugin

To describe a plugin without running a readiness check, run:

```bash
PLUGIN_COMMAND manifest --json
```

The manifest reports the executable, capabilities, commands, output policy, and
security posture. Replace `PLUGIN_COMMAND` with an installed command, such as
`mere-vfx-tools`.

## Check readiness

The `doctor` command verifies required executables, credentials, paths, and
provider access. It doesn't create paid resources.

## Plan the workflow

The `plan` command validates inputs, resolves commands and provider settings,
and writes a `run.json` file with the `planned` status.

Review the plan before any workflow that creates cost or changes remote state.

## Run the plan

The `run` command consumes the reviewed manifest. A provider plugin writes the
manifest before the first external change. It then updates the manifest as
resources and artifacts change.

## Resume or inspect a run

The `resume` command continues or inspects a durable run. If a remote resource
no longer exists, the command reports that state in its machine-readable
result.

## Clean up resources

The `cleanup` command stops referenced remote resources or records a local
no-op. Cleanup is idempotent, so repeated cleanup requests preserve a successful
cleanup state.

## Use focused commands

Many plugins provide a task command such as `knockout`, `roto`, `perform`,
or `process`. These commands combine planning and execution while preserving
the plugin's manifest and output rules.

Some focused local and graph-provider plugins use a smaller command surface.
For the authoritative command list, run `manifest --json` or read the
plugin's reference page. Provider plugins always implement `doctor`, `plan`,
`run`, `resume`, and `cleanup`.

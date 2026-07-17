# Plugin lifecycle

Every official plugin exposes the same control loop:

```text
discover → doctor → plan → run → resume/inspect → cleanup
```

## Discover

`manifest --json` reports capabilities and commands. Discovery must not invoke
readiness checks or perform work.

## Doctor

`doctor` verifies local executables, credentials, paths, and provider readiness.
It does not create paid resources.

## Plan

`plan` validates inputs, resolves commands and provider settings, and writes
`run.json` with status `planned`.

## Run

`run` consumes that manifest. Provider plugins persist the manifest before the
first external mutation, then update it as resources and artifacts change.

## Resume

`resume` continues or inspects a durable run. A plugin may report that a remote
resource no longer exists, but the response must remain machine-readable.

## Cleanup

`cleanup` tears down referenced remote resources or records a local-only no-op.
It is idempotent: repeating cleanup must not create a new failure mode.

## One-shot commands

Many plugins expose a workflow-named convenience command such as `knockout`,
`roto`, `perform`, or `process`. It combines plan and run while preserving the
same manifest and output rules.

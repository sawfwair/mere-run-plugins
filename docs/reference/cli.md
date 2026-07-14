# CLI lifecycle reference

Official plugins share a predictable top-level command surface.

## `manifest --json`

Prints a plugin self-description matching `plugin.v1.schema.json`. Discovery may
call this command; it must not perform readiness checks or workflow execution.

```bash
mere-vfx-tools manifest --json
```

## `doctor`

Checks local and provider readiness without creating paid resources.

```bash
mere-runpod doctor
```

Expected checks include required executables, output paths, credentials, SSH
material, and optional provider tools.

## `plan`

Validates requested inputs, resolves execution, and writes a run manifest with
status `planned`.

```bash
mere-vfx-tools plan \
  --tool roto \
  --request-json ./request.json \
  --output-dir ./out \
  --run-id roto-001
```

Plugin-specific arguments follow `plan`; use `<plugin> plan --help` for the
authoritative surface of the installed version.

## `run`

Executes a planned manifest. Most local production plugins accept the manifest
path directly:

```bash
mere-vfx-tools run ./out/run.json
```

Provider plugins must persist the manifest before external resource creation.

## `resume`

Continues or inspects an existing durable run:

```bash
mere-vfx-tools resume ./out/run.json
```

Resume behavior is plugin-specific, but its response remains machine-readable.

## `cleanup`

Terminates referenced remote resources or records that a local run needs no
remote cleanup:

```bash
mere-vfx-tools cleanup ./out/run.json
```

Cleanup is idempotent.

## One-shot workflow commands

Plugins may expose declared helpers such as `knockout`, `roto`, `perform`,
`process`, or `run-jobs`. These combine planning and execution without weakening
manifest, stream, security, or cleanup rules.

## Stream policy

- stdout: promised JSON or path output;
- stderr: human diagnostics and child-process logs;
- neither stream: secrets.

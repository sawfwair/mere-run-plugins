# DECISIONS.md

## Companion Plugins, Not Core Runtime

The core `mere.run` repo owns local inference and canonical model behavior. This
repo owns companion executables that plan and coordinate workflows around that
runtime. Plugins are installed as standalone CLIs, not loaded dynamically into
the core process.

## Machine-Readable Output

When a command promises JSON, stdout is reserved for machine-readable payloads.
Human diagnostics and child-process logs go to stderr. This keeps plugins safe
for `mere.run`, agents, and shell automation.

## Durable Manifests Before Remote Mutation

Provider plugins write `run.json` before creating or mutating remote resources.
The manifest records intended operations, created IDs, artifacts, status, and
cleanup state so interrupted runs can be resumed or cleaned up safely.

## Paid Resources Require Preview

Any command that can create paid resources must expose a dry-run or planning
surface. Remote providers default to cleanup or termination unless the user
passes an explicit keep/debug flag.

## External APIs Are Boundary-Typed

Provider responses enter the codebase at narrow client functions. Those
functions are responsible for shape checks, redaction, and stable typed payloads
before the rest of the plugin consumes the data.

## Public Repo Hygiene

Public docs use repo-relative commands and placeholders. Workstation paths,
private pod IDs, credentials, local artifact bundles, and maintainer-only release
helpers do not belong in this repo.

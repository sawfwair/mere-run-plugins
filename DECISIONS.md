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

## Static Analysis Has No Whole-Module Escape Hatch

Every production module passes strict mypy and Ruff. Optional SDKs are narrowed
at dedicated protocol or array boundaries; missing third-party stubs may be
listed explicitly, but `ignore_errors`, dynamic top types, blanket ignores, and
lint suppressions are rejected by the gate.

## Coverage Measures Production Logic

Coverage may omit package initializers, module launch shims, and six one-purpose
workflow dispatch shims. Provider preparation, native handoffs, Blender workers,
and command routers remain in the denominator. Hardware and SDK boundaries use
deterministic fakes; installed-Blender integration is opt-in.

## Fast Feedback and Release Proof Are Separate

`scripts/check-fast.sh` runs static checks, structure and contract validation,
and package tests in parallel for local iteration. `scripts/check.sh` remains the
clean-environment gate: it installs dependencies, reports coverage, installs all
packages, and exercises installed executables. Pre-commit uses the fast gate;
CI uses the full gate.

## Public Repo Hygiene

Public docs use repo-relative commands and placeholders. Workstation paths,
private pod IDs, credentials, local artifact bundles, and maintainer-only release
helpers do not belong in this repo.

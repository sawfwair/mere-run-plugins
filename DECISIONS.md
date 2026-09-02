# DECISIONS.md

## Companion plugins, not a core runtime

The core `mere.run` repo owns local inference and canonical model behavior. This
repo owns companion executables that plan and coordinate workflows around that
runtime. Plugins are installed as standalone CLIs, not loaded dynamically into
the core process.

## Machine-readable output

When a command promises JSON, stdout is reserved for machine-readable payloads.
Human diagnostics and child-process logs go to stderr. This keeps plugins safe
for `mere.run`, agents, and shell automation.

## Durable manifests before remote changes

Provider plugins write `run.json` before creating or mutating remote resources.
The manifest records intended operations, created IDs, artifacts, status, and
cleanup state so interrupted runs can be resumed or cleaned up safely.

## Paid resources require a preview

Any command that can create paid resources must expose a dry-run or planning
surface. Remote providers default to cleanup or termination unless the user
passes an explicit keep/debug flag.

## External APIs are boundary-typed

Provider responses enter the codebase at narrow client functions. Those
functions are responsible for shape checks, redaction, and stable typed payloads
before the rest of the plugin consumes the data.

## Static analysis has no whole-module exception

Every production module passes strict mypy and Ruff. Optional SDKs are narrowed
at dedicated protocol or array boundaries; missing third-party stubs may be
listed explicitly, but `ignore_errors`, dynamic top types, blanket ignores, and
lint suppressions are rejected by the gate.

## Coverage measures production logic

Coverage may omit package initializers, module launch shims, and six one-purpose
workflow dispatch shims. Provider preparation, native handoffs, Blender workers,
and command routers remain in the denominator. Hardware and SDK boundaries use
deterministic fakes; installed-Blender integration is opt-in.

## Fast feedback and release proof are separate

`scripts/check-fast.sh` runs static checks, structure and contract validation,
and package tests in parallel for local iteration. `scripts/check.sh` remains the
clean-environment gate: it installs dependencies, reports coverage, installs all
packages, and exercises installed executables. Pre-commit uses the fast gate;
CI uses the full gate.

## Public repository hygiene

Public docs use repo-relative commands and placeholders. Workstation paths,
private pod IDs, credentials, local artifact bundles, and maintainer-only release
helpers do not belong in this repo.

## Pi proposes, and the film contract governs

The film studio uses Pi as its interactive harness and child-agent runtime, not
as the durable source of truth. Specialist processes receive read-only tools and
return versioned JSON proposals. Only `mere-film-tools` validates those
proposals, advances approval gates, executes media, accepts canon, and records
artifact hashes. This keeps provider choice in Pi while making interruption,
rerolls, production cost, and delivery independently auditable.

## Film evidence must be source-bound

Film automation does not infer success from a completed agent or a non-empty
file. Media reuse requires a matching job-spec digest, recorded artifact hash,
and current file hash. Dialogue is transcribed after synthesis, generated sound
effects are stream-checked, captions are derived from the accepted timeline,
and generated shot frames are inspected against canon. Every receipt is bound
to source hashes before critics receive it. OS-backed single-writer locking protects the ledger;
the next writer explicitly recovers work left `running` by a dead process.

## Creative search preserves every candidate

Multi-take film production never replaces evidence in place. Each candidate has
its own deterministic seed, job digest, media hash, and early/mid/late contact
sheet. A local vision selector scores candidates against accepted canon, copies
the winner into the edit, and records the complete tournament. Candidate count
is explicit because it directly multiplies local video compute.

## Human review is a bound artifact

The offline review page produces an approval or revision document bound to the
rough-cut hash and the complete automated evidence digest. Picture lock requires
that recorded human decision in addition to technical and AI review. The human
gate is durable and tamper-evident without pretending an agent can approve on
the user's behalf.

## Film production resolves models before media

Every media role is explicit in project state, including defaults for video,
vision inspection, ASR, TTS, SFX, and music. Draft and final execution resolve
all catalog-managed roles required by the accepted plan through `mere.run model info` before
the first generation job and write a source-bound readiness receipt. Missing
models fail together as a revision request instead of surprising the studio
after partial media generation. Usage gates remain separate: installed does not
mean licensed for the brief's intended use. The default `vision inspect` Qwen3-VL
runtime owns its own adapted cache and is recorded as runtime-managed; an
explicit override must be a compatible local Qwen model root.

# Archive investigator acceptance

This report records follow-up validation for the bounded Pi investigator from
PR #53 on September 5, 2026. It distinguishes process and contract checks from
model answer quality. A valid citation path doesn't prove that its snippet
supports a claim.

The 2-bit model passed this compound retrieval and answer-quality case and is
the follow-up default. The 1-bit comparison completed but failed evidence
acceptance. This is one fixture on the host below; it doesn't qualify arbitrary
questions or smaller hardware.

## Environment

| Component | Tested value |
| --- | --- |
| Hardware | Apple M4 Max, 128 GiB unified memory |
| OS | macOS 26.5.2 |
| Runtime | `mere.run` 0.50.0, `text-chat-q36` engine |
| Pi | v0.84.2 |
| Context | 16,384 tokens |
| Search limits | Four searches, five results per search |
| First-search and tool deadlines | 60 seconds each |
| Storage | Harbourline v3 safe-content SQLite index |
| Embeddings | `vision-embed-qwen3-vl-2b`, 1,024 dimensions |

The installed model manifests identify these sources:

| Model ID | Source repository | Source revision |
| --- | --- | --- |
| `text-chat-bonsai-27b-1bit` | `prism-ml/Bonsai-27B-mlx-1bit` | `ef22f239c670078e1507f9769bcaa66657332b96` |
| `text-chat-bonsai-27b-2bit` | `prism-ml/Ternary-Bonsai-27B-mlx-2bit` | `70f75f3ad081ab840a42f3304c02c27e7f89bfb7` |

Runtime executable SHA-256:
`38d2740f12fc01ea2f8ba78ba95f45858502c911a4a1bc3fe9340daac9959e4d`.
Dataset manifest SHA-256:
`5a0edb2e6b7b51613135228a29889d6d96ebf48cdd0a2dc70ae69e437a2c6edd`.
All 58 source files still match the manifest's baseline hashes. SQLite's
integrity check returned `ok` for the safe-content database.

## Acceptance criteria

The question is: "Was the Freezer 3 repair covered by warranty, and when does
that warranty expire?"

The opt-in test requires at least two searches and retrieval of all three
document groups:

- Repair record: `Facilities/Halifax/Freezer 3/2024/WO-HFX-241842-corrective-repair.pdf`
- Invoice: `Finance/Accounts Payable/Northshore Refrigeration/2024/INV-8841.pdf`
  or its duplicate, `Old Backups/Email Attachments/2024/INV-8841-copy.pdf`
- Agreement: `Vendors/Northshore Refrigeration/service-agreement-2024.docx`

The repair record establishes a 24-month warranty on the replacement parts
through **2026-02-17**. The snippets don't establish reimbursement of the repair
charge or exclusion of labor from coverage. The test requires a supported
expiry claim and at least one unresolved claim. Review of the returned claims
also checks that the model doesn't invent a labor exclusion. The general
contract validator checks structure and citation membership; it doesn't perform
this semantic review.

## Timing and memory observations

Each run starts a new API process. The OS file cache wasn't cleared, and the
workstation also ran unrelated workloads. These observations aren't isolated
throughput benchmarks or evidence of performance on a smaller Mac.

API-ready time includes question reduction, preflight, and server startup.
First-search time is measured from Pi launch to its first tool call. Total time
includes cleanup. Peak memory is the sum of sampled launcher and owned-process
RSS, sampled approximately every 0.5 seconds. RSS excludes macOS and other
applications, can count shared mappings more than once, and isn't a measurement
of total unified-memory demand.

| Run | API ready (s) | First search after Pi launch (s) | Total (s) | Peak RSS (GiB) | Searches | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1-bit, 600-second Pi budget | 10.062 | 13.661 | 120.725 | 13.39 | 2 | Valid contract; failed evidence acceptance |
| 2-bit, 300-second Pi budget | 9.779 | 15.725 | 311.248 | 14.36 | 4 | Deadline expired during final generation |
| 2-bit, final implementation, 600-second Pi budget | 11.124 | 10.686 | 223.766 | 14.36 | 4 | Passed contract, retrieval, and evidence review |

The 1-bit answer cited the invoice as proof that the repair wasn't covered and
didn't retrieve the vendor agreement. It isn't qualified by this run.

The passing 2-bit run completed on its first attempt, within the default
300-second Pi limit despite using an explicit 600-second budget for comparison.
It kept the API resident for all four searches. One RSS sample failed and was
counted without interrupting inference. Its sampled peak was 15,422,619,648
bytes. The final claims cited the repair record and agreement paths listed
above; the invoice and its duplicate were also retrieved. It supported the
parts expiry date and marked whether the repair was covered as unresolved,
without inventing a labor exclusion.

## Diagnosis and fixes

The original interrupted three-minute run had no retained request timeline,
so its unique cause can't be established retrospectively. Follow-up traces
showed that extensions loaded in under a second and the first tool call could
start promptly. Most subsequent delay occurred between successful API responses
and completed model generations. Some runs reached the output or wall-clock
limit; a structurally valid earlier 2-bit answer invented a labor exclusion
and didn't pass answer-quality acceptance.

The follow-up fixes independently verified integration defects:

- Convert search path objects to relative citation strings instead of discarding
  them, and omit absolute paths from model-visible search results.
- Honor the runtime's token and thinking capability fields. Don't send both
  `max_tokens` and `max_completion_tokens`.
- Read the final completed assistant text from Pi's JSON event stream. Ignore
  earlier turns and thinking blocks.
- Disable tools when the search budget is exhausted. A contract repair reuses
  retrieved evidence, disables tools, and requests JSON when the runtime supports
  it. Both attempts share one deadline and search budget.
- Disable Pi compaction, automatic retries, sessions, and automatic discovery
  for the isolated investigation.
- Own process groups through startup, searches, repair, interruption, and
  shutdown. Use an ephemeral API key for the temporary loopback server.
- Count failed RSS samples in `missedMemorySamples` instead of allowing an
  observational `ps` timeout to abort inference. The regression test simulates
  this failure while a child process completes successfully.

## Admission and smaller-machine validation

On this 128 GiB Mac, the runtime advertises four admission permits. Its standard
API workload uses two permits; a standard search inference step can use the
other two. The launcher checks live capacity, queued work, available memory,
and memory pressure before searching. It keeps the API resident when there is
room and releases its own idle server when capacity is constrained.

A workload can queue after that initial check. While a search runs, the launcher
checks for newly queued work and releases its server so an exclusive workload
can't wait behind the API while the nested search waits behind that workload.
The runtime remains responsible for actual admission and its memory guard.
Tests cover both constrained capacity and this queue race.

**16 GB validation gap:** No 16 GB Apple Silicon Mac was available. The owner
accepted recording this gap in the follow-up PR. Process RSS measured on the
128 GiB host doesn't establish that the complete workflow fits or passes the
runtime's memory guard on a 16 GB host. No smaller-machine qualification is
claimed.

## Reproduce the checks

Run the repository gate and Pi adapter tests from the repository root:

```bash
./scripts/check.sh
corepack pnpm test:archive-pi
corepack pnpm docs:coverage
corepack pnpm docs:build
```

The gate includes deterministic multi-search, citation rejection, bounded
repair, timeout, read-only preservation, and SIGINT/SIGTERM process-tree tests.
It also verifies that installed wheels preserve the bundled Pi resources.

To run the installed-model acceptance case, supply the existing safe-content
Harbourline v3 index:

```bash
MERE_ARCHIVE_HARBOURLINE_DATABASE=/path/to/harbourline-safe.sqlite3 \
MERE_ARCHIVE_ACCEPTANCE_OUTPUT_DIR=./artifacts/investigation/acceptance \
MERE_ARCHIVE_ACCEPTANCE_PI_TIMEOUT=600 \
PYTHONPATH=packages/mere-archive-tools/src:packages/mere-archive-tools/tests \
  .venv/bin/python -m unittest test_investigation.HarbourlineAcceptance -v
```

Set `MERE_ARCHIVE_ACCEPTANCE_MODEL=text-chat-bonsai-27b-1bit` for the comparison.
The acceptance test is skipped by default. Keep local result and diagnostic
bundles outside Git; this report records their relevant observations.

Set `MERE_ARCHIVE_ACCEPTANCE_COMMAND` to the installed bundle entrypoint to
validate the distributed executable. Frozen bundles dispatch nested searches
through the reviewed `mere_archive_tools.cli` module; Python installations use
`python -m mere_archive_tools`. A regression test exercises both searches through
the frozen dispatcher contract.

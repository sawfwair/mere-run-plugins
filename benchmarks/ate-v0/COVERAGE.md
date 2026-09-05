# Coverage and benchmark size

This release contains 240 authored decisions: 12 cases in each of 20 server families, with 120 cases in each split. It is a first tool-decision benchmark, not a completed evaluation of autonomous work.

## Why this size

The original 48 cases were useful for validating the case format and scorer. Expanding to 240 adds distinct interfaces and failure modes while keeping every case individually reviewable. Additional names and paraphrases alone would not provide comparable coverage.

A later 500–1,000-case release makes sense after actual model runs identify missing failure modes. Allocate that expansion to new server families, independently authored workflows, long tool catalogs, tool-result failures, recovery, and multi-step outcome checks. Do not treat a larger raw count as proof of representative coverage.

Scores from 12 cases within one family are coarse diagnostics. Cases share vocabulary and structure, so they are not independent samples. Report overall and per-family scores, failure counts, and execution-lane scores separately; do not present occupational coverage or statistical precision from the raw count alone.

## Family coverage

| Family | Split | Cases | Executable cases |
|---|---|---:|---:|
| audio | development | 12 | 0 |
| browser | development | 12 | 4 |
| calendar | held-out | 12 | 6 |
| captions | held-out | 12 | 0 |
| documents | development | 12 | 0 |
| filesystem | development | 12 | 8 |
| geo | held-out | 12 | 0 |
| git | held-out | 12 | 0 |
| images | held-out | 12 | 0 |
| issues | development | 12 | 0 |
| mail | held-out | 12 | 0 |
| metrics | development | 12 | 4 |
| notes | development | 12 | 6 |
| publishing | held-out | 12 | 9 |
| scheduling | development | 12 | 0 |
| search | development | 12 | 0 |
| sql | held-out | 12 | 8 |
| storage | held-out | 12 | 9 |
| tables | development | 12 | 6 |
| web | held-out | 12 | 0 |

## Behavioral coverage

Cases can carry multiple behavior tags, so these counts overlap.

| Behavior | Cases |
|---|---:|
| clarification | 43 |
| unavailable | 28 |
| untrusted-content | 20 |
| result-followup | 20 |
| recovery | 3 |
| scope | 28 |
| near-neighbor | 12 |
| units | 5 |
| argument-types | 6 |
| direction | 6 |
| no-action | 5 |

See `coverage.json` for every tag and exact counts.

## Execution and outcome checks

Sixty cases have executable, in-memory fixtures across notes, storage, publishing, files, SQLite, spreadsheets, browser state, calendars, and process telemetry. Eight SQL cases add alternate fixture states. SQL accepts equivalent queries based on returned rows and complete final state; the remaining cases use reviewed exact decisions with explicit alternatives where appropriate.

Twenty prompts include supplied earlier tool results, such as an ID listing, a language list, a failed modality choice, or a discovered browser selector. These test the next decision from context. They do not exercise native function-call transport or run an autonomous tool loop.

No image, audio, geographic, web, or mail service is invoked. Media decisions do not establish perceptual quality. All upstream tool schemas are replaced by explicitly authored fixture contracts; ATE identities and snapshot hashes provide traceability, not server conformance.

## Split and review limits

Entire target and distractor server families remain in one split. All cases are published, so held-out means held apart by this pack, not sealed or absent from a model's training. Development and held-out families differ in difficulty. Shared generic actions such as read/create remain conceptually related across families.

Cases are author-reviewed. Independent review, native tool-call transport, multi-step execution, representative workload weighting, repeated model trials, and model results remain future work. Diagnostic gates and local fixture checks are not model release qualification.

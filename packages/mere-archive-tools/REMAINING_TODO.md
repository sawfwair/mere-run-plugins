# Archive investigator completion status

This checklist records the follow-up to merged PR #53. See [the acceptance
report](ACCEPTANCE.md) for model revisions, source paths, measurements, failed
comparisons, and reproduction commands.

## Runtime acceptance

- [x] Run the 1-bit model to completion against the Harbourline safe-content
  index and assess its answer. It returned valid JSON but failed evidence
  acceptance: it missed the agreement and inferred noncoverage from an invoice.
- [x] Compare the 2-bit model on the same case. It passed the compound retrieval
  and answer-quality test and replaces 1-bit as the default.
- [x] Verify that Pi starts `archive_search` within the first-search deadline.
  The passing run reached it 10.686 seconds after Pi launch.
- [x] Retrieve the repair record, invoice, and vendor agreement through query
  refinements. The passing run used four searches.
- [x] Return only recorded citation paths, support the parts expiry date, and
  leave repair reimbursement and labor coverage unresolved.
- [x] Record API-ready time, first-search time, total latency, sampled process
  memory, search count, and citation paths. The passing run took 223.766 seconds
  on an M4 Max with 128 GiB of unified memory.

## Process lifecycle and diagnosis

- [x] Own process groups for preflight, question reduction, the temporary API,
  Pi, and nested searches. Stop them after success, error, SIGINT, or SIGTERM.
- [x] Test interruption during server readiness and active Pi execution,
  including a grandchild process.
- [x] Bound server readiness, first search, each search, both Pi attempts, and
  shutdown. Contract repair reuses prior evidence without restarting retrieval.
- [x] Record content-free timing and request metadata. Ignore hidden reasoning
  and earlier assistant turns when parsing the final result.
- [x] Diagnose reproducible integration and generation delays. The original
  interrupted three-minute run had no retained timeline, so its unique cause
  remains unknown. Follow-up traces distinguish fast extension loading from
  later generation delays and bounded timeout failures.
- [x] Prevent a failed memory observation from aborting inference; report missed
  samples explicitly.

## Admission and hardware

- [x] Use current capacity, queues, memory pressure, and available memory to
  decide whether the search can run alongside the API. On this 128 GiB host,
  four permits allow the two-permit API and standard search work to coexist.
- [x] Release the investigator's idle server when another workload queues after
  a search starts, avoiding a FIFO admission deadlock.
- [x] Retain runtime memory guards and enforce deadlines on constrained-capacity
  paths. Test them with deterministic fake processes.
- [x] Document RSS and latency as observations on the tested hardware, without
  treating process RSS as total unified-memory demand.
- [ ] Run on an actual 16 GB Apple Silicon Mac and verify the full workflow
  against its memory guard. No such machine is available; the owner accepted
  recording this validation gap in the follow-up PR.

## Regression coverage and contracts

- [x] Test multiple searches through the real supervisor and search CLI with
  fake native inference and Pi processes.
- [x] Reject missing searches, invented citation paths, exceeded budgets,
  malformed final JSON, truncated output, and timed-out tools.
- [x] Preserve source files and the database; open search connections read-only
  and reject output or diagnostics paths that overlap protected inputs.
- [x] Validate the published result schema and illustrative example, including
  optional metrics. Verify bundled Pi resources in the installed wheel.
- [x] Add opt-in installed-model Harbourline acceptance and Pi adapter tests.
- [x] Pass the repository gate and docs checks before opening the follow-up PR.

# Remaining archive investigator work

This checklist is for contributors who complete the bounded Pi investigator in
Archive Tools. The implementation, unit tests, package resources, and developer
documentation are present. The repository gate passes.

## Complete runtime acceptance

- [ ] Run `mere-archive-tools investigate` to completion against the Harbourline
  safe-content index with `text-chat-bonsai-27b-1bit`.
- [ ] Confirm that Pi calls `archive_search` within the configured timeout. In
  the first live attempt, the API server loaded Bonsai and Pi connected, but no
  search trace appeared during approximately three minutes before the run was
  interrupted.
- [ ] Confirm that the Freezer 3 question retrieves the repair record, invoice,
  and vendor warranty agreement through separate query refinements.
- [ ] Confirm that the final JSON marks unsupported facts as `unresolved` and
  cites only paths recorded in the authoritative search trace.
- [ ] Record cold-start time, time to first search, total latency, peak memory,
  search count, and cited paths for the acceptance run.

Use this acceptance question:

```bash
mere-archive-tools investigate \
  --database ./harbourline-safe.sqlite3 \
  --question "Was the Freezer 3 repair covered by warranty, and when does that warranty expire?"
```

## Tighten process lifecycle behavior

- [ ] Add signal handling that stops the temporary `mere.run api serve` process
  when the launcher receives `SIGINT` or `SIGTERM`. The interrupted live test
  required an explicit stop for the orphaned API server.
- [ ] Add a test that interrupts the launcher and verifies that Pi and the API
  server both exit.
- [ ] Preserve the existing bounded waits for server readiness, Pi completion,
  search execution, and server shutdown.

## Diagnose time to first search

- [ ] Capture Pi diagnostics and the local API request timeline without storing
  hidden reasoning or archive content.
- [ ] Determine whether the delay comes from model generation, provider
  metadata, tool schema processing, or extension loading.
- [ ] Set a practical first-search deadline or select a faster qualified default
  model if Bonsai can't meet the acceptance target.
- [ ] Re-run the investigation with `text-chat-bonsai-27b-2bit` as a comparison
  while keeping the less-than-16-GB deployment target.

## Validate constrained retrieval on smaller machines

- [ ] Run the acceptance case on an Apple Silicon Mac with 16 GB of unified
  memory.
- [ ] Verify that the chat model, PII reducer, and embedding workflow stay within
  the memory guard instead of waiting indefinitely for machine admission.
- [ ] If nested `mere.run` search commands contend with the API server, route
  query embeddings through the temporary loopback API or another single-process
  path.
- [ ] Document measured memory and latency as observations tied to the tested
  hardware and model revision.

## Add end-to-end regression coverage

- [ ] Add a deterministic fake-Pi test that makes multiple `archive_search`
  calls and returns a valid investigation contract.
- [ ] Add rejection tests for a missing search trace, a fabricated citation, an
  exceeded search budget, invalid JSON, and a timed-out tool call.
- [ ] Add an opt-in Harbourline acceptance test that uses installed local models.
- [ ] Keep `./scripts/check.sh` passing before the pull request leaves draft
  status.

# Complete the run setup

For operators, this is the launch checklist for one five-entry campaign.
Complete the campaign copy before any scored build. A checked box is an operator
attestation, not an automated proof. The kit does not launch agents, enforce
budgets, isolate processes, or validate these attestations.

## Pin the participants and common controls

Record the following in `manifest.json` under `runSettings` and each participant's
`modelConfiguration`. Use explicit values; do not leave a required setting blank.
Use `unavailable` with a reason for unobservable measurements.

- [ ] Assign the four local configurations and one explicitly named frontier
  configuration to A–E using a recorded shuffle seed or saved assignment record.
  Record the execution order before scoring. Keep the mapping from reviewers.
- [ ] Pin each model ID, weight digest or provider version, quantization, runtime
  revision, context size, sampling settings, seed support, reasoning settings,
  and token-accounting method. Record `fresh-context` or `author-informed`.
- [ ] Pin the harness revision, system prompt, tool definitions, permissions,
  prompt formatting, and any installed instructions or skills. Hash their saved
  configuration files. Use the same harness and controls when supported; record
  every difference and label differing conditions as unmatched.
- [ ] Pin browser version, operating system, the two review viewports, default
  time zone, and a common browser clock of September 7, 2026, at 12:00 UTC.
  Record how the harness overrides and verifies time zone and browser wall clock.
  F23 and F24 temporarily replace these defaults. Do not change the host clock.
- [ ] Declare exactly what browser feedback each agent receives: screenshots,
  rendered text, accessibility tree, DOM, console logs, and interaction tools.
  Qualify the same usable feedback for every participant. Merely exposing an
  image tool does not establish that a model can consume its output. If a shared
  modality is unavailable, choose a common supported set before scoring or mark
  the comparison unmatched.
- [ ] Record each stage's wall-time, tool-turn, per-response-token, and aggregate
  token limits, the component that enforces each, and stop/cleanup behavior.
  Count generation across all responses, including responses without tool calls.
  Record whether reasoning is included, excluded, or unavailable. If the proposed
  totals cannot be enforced comparably, freeze a common enforceable alternative
  or report unmatched budgets. Do not label unknown reasoning counts as zero.
- [ ] Record the filesystem boundary and network policy. Participant tools must
  not read sibling entries, this repository, operator files, host instructions,
  or credentials. Allow only the entry and declared ordinary dependencies.
  Deny outbound internet from the participant shell and browser. Allow the
  operator-owned model transport to its pinned provider endpoint and the local
  site/browser control connections; keep provider credentials outside the entry.
- [ ] Record when each stage's timer starts and ends, how the same conversation
  resumes for stage 2, and how history compaction is handled. Pause agent activity
  during review. Review time does not consume the follow-up budget. Feed no review
  findings or case instructions back into the agent conversation.

## Qualify the execution path

Use an unrelated tiny fixture in a separate throwaway entry and fresh agent
context for each configuration. Do not use After Hours, its data, or its checks.
Record qualification transcripts, commands, observed results, and evidence paths.
These are separate unscored attempts and must not enter the scored context.

- [ ] Confirm file editing, shell execution, serving a local page, and the declared
  browser feedback and controls work through the actual harness.
- [ ] Confirm two model turns preserve tool results and required reasoning history.
  Pause and resume that same session using the planned stage-transition mechanism.
- [ ] Exercise the stop mechanism with small fixture limits for each supported
  budget. Confirm no automatic retry or budget extension occurs and partial files
  and transcripts survive. Record token totals and individual tool-call counts.
- [ ] Confirm access to synthetic sibling/operator sentinels is rejected through
  both file and shell tools. Test the network boundary without using real secrets.
  Confirm the allowed model transport and local site still work.
- [ ] Confirm reviewer browser automation can apply and independently observe
  Pacific/Honolulu, Pacific/Kiritimati, and the F24 browser clock; export and
  restore storage; and retain an entry's origin across a source update.

A missing or failed qualification blocks scoring. Preserve the failed evidence.
Document a configuration correction before any additional qualification. Never
count a declared capability as a successful observed check.

## Freeze and schedule review

- [ ] Wait for the current inference study to finish. Record machine admission
  and the absence of competing inference before this campaign starts.
- [ ] Allocate up to 10 hours of agent work under the default five-entry budgets.
  Separately assign reviewers and allow time for 280 case assessments, including
  their substeps, and at least 80 required state/viewport screenshots. These are
  counts and ceilings, not a finish-time estimate. Record a review-time allowance.
- [ ] Retain the source revision and current uncommitted-source hashes. Hash the
  completed manifest, this checklist, protocol, prompts, checks, calculator,
  qualification evidence, harness configuration, and every initial entry file.
  Store a separate dated freeze manifest outside participant scope. Before each
  entry starts, verify its initial files and shared controls against that freeze.
  After an entry starts, preserve its outputs separately from those initial hashes.
- [ ] Set `protocolFrozen` to `true` only after completing the settings and checks,
  before hashing the final manifest. Record the operator and freeze time. Any
  later control change needs a preserved amendment and explicit comparability
  assessment. Never overwrite an earlier attempt or its frozen contract.

## Preserve the migration fixture before stage 2

For each entry, stop the stage 1 agent and save its transcript and source hash.
Before sending the follow-up, run C05's preparation steps against that stage 1
source. Keep a dedicated export with two active adjacent bookings and one
previously canceled booking. Record the existing storage shape without imposing
an identifier field or changing records. Preserve the effective origin/profile.

If stage 1 cannot create the fixture, retain the failed setup evidence. Record
C05 as `fail` with `failureCause: "stage1-prerequisite"`; never fabricate records.
Otherwise, restore the preserved export for C05 after the update and record any
failure as `failureCause: "site-behavior"`. Do not include `failureCause` for a
pass or pending result. The calculator reports this distinction separately.
All other independent stage 2 cases start with empty visitor storage.

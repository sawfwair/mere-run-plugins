# Run protocol

For operators, this protocol fixes the conditions of the comparison before
you run an agent. Store the completed settings with the campaign manifest.
Complete and retain
[the run setup checklist](RUN_SETUP.md), including observed qualification, before
any scored build. The checklist records operator evidence; this kit does not
enforce execution controls.

## Common conditions

Use one entry per model, one initial attempt, and one follow-up in the same
agent session. Give each agent file reads and edits, a shell, and the same
browser controls. Restrict its file scope to its entry and ordinary tool
dependencies. Block outbound internet from participant shell and browser tools;
allow the operator-owned model transport and local site/browser connections
defined in the setup checklist. Keep provider credentials outside participant
scope. Do not provide design advice, reviewer results, hidden examples, or
another participant's work.

Use these default limits for all five entries:

| Limit | Initial build | Follow-up |
| --- | ---: | ---: |
| Wall time | 90 minutes | 30 minutes |
| Agent turns that request tools | 64 | 24 |
| Generated tokens per response, including exposed reasoning | 16,384 | 16,384 |
| Total generated tokens, including exposed reasoning | 131,072 | 65,536 |

A tool turn can contain multiple calls; also record the number of individual
calls. Stop at the first exhausted limit. Preserve and evaluate the resulting
site, including partial work. Record truncation and the stop reason. Do not
silently retry or extend a participant's budget.

These are proposed defaults. Confirm that every runtime and harness can enforce
them before the first run. If a common limit is unsupported, freeze a supported
common alternative for every entry, or label the comparison as unmatched.
Do not equate hidden frontier reasoning tokens with an observed local count.
Record unavailable token accounting as unavailable.

Run local models sequentially on the same machine without competing inference
jobs. Record hardware, model digest, quantization, context size, temperature,
seed support, runtime revision, and prompt formatting. Record the frontier model
version and provider separately. Timing compares these deployed configurations;
it does not isolate model architecture or hardware speed.

## Browser review

Use the same browser version and studio data for every entry. For each independent
case, start with seed data and empty visitor storage, unless the case specifies
a sequence or preserved storage. Keep one origin per entry. For refresh and
migration checks, reuse that origin and browser profile. Retain a copy of
stage 1 source and storage before the follow-up. Never clear that copy.

At stage 1, review all 26 cases. Before sending the follow-up, prepare and export
the dedicated C05 migration fixture against the preserved stage 1 source. At
stage 2, review the 24 stable cases and all six changed-rule cases. The two
original exact-adjacency cases are replaced, so their intentional behavior
change never counts as a regression.

F23 repeats a booking across Pacific/Honolulu and Pacific/Kiritimati, retaining
its origin and storage. F24 moves only the browser clock past the booking window.
Capture the effective overrides and restore the common defaults after each case.
An unavailable override is an infrastructure limitation, not a model failure.

A blocked path caused by the site counts as a failure. Leave a case pending
only when the reviewer has not assessed it. Tool or machine failure is an
infrastructure incident: retain the attempt and report it separately. Do not
quietly convert an interrupted review into a final model score.

If stage 1 cannot create C05’s migration fixture, score C05 as a failed deliverable
and record `failureCause: "stage1-prerequisite"`. Report it separately from an
observed migration failure (`failureCause: "site-behavior"`). Do not inject
synthetic records into the participant’s storage. C05 counts in the six-case
changed-rule percentage in either case; the percentage alone does not establish
why migration failed or whether migration could be assessed.

For every pass or failure, record the inputs, observed result, and an evidence
path. Save screenshots at both viewports, the browser console log, source
hashes, transcripts, and localStorage exports. Measure elapsed build time,
time to complete a booking task, tool calls, and token usage separately.

## Metrics

- **Initial functionality:** passed stage 1 cases / 26.
- **Updated functionality:** passed stable stage 2 cases / 24.
- **Changed-rule success:** passed new cases / 6.
- **Regression rate:** previously passing stable cases that fail in stage 2 /
  stable cases that passed in stage 1. Report `null` when the denominator is zero.
  Also report the numerator and denominator; zero regressions can accompany a
  poor initial site.
- **Review scores:** use the separate visual, usability, and accessibility
  ratings in [the review guide](REVIEW.md). Do not average these with case scores.

Incomplete categories report a pending count and a `null` final percentage.
For repeated runs, retain every attempt and report per-model distributions.

## Blind comparison

Shuffle A–E assignments before running models. Keep the model mapping and resource
metrics from visual reviewers. Present identical viewport captures and working
sites in a randomized order. Record individual ratings before discussion.
Use at least two reviewers when available and retain disagreements.

A fresh frontier baseline receives only its entry files and the same follow-up.
Record `fresh-context` or `author-informed` in the run manifest. The latter is
useful as a reference implementation, but cannot establish an unbiased frontier
comparison.

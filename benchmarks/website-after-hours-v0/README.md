# After Hours website evaluation

For evaluation operators, this kit compares agents building the same small
booking website. It includes a neutral starter, fixed data, two prompts,
browser acceptance cases, a blind review rubric, and a result calculator.

This is an authored website task, separate from the JSON-response eval pack
format. Do not pass this directory to `mere.run eval run`. The kit prepares
workspaces and calculates recorded results; it does not run model agents or
automatically judge their websites.

## Prepare a comparison

From the repository root, run:

```bash
python3 benchmarks/website-after-hours-v0/benchmark.py validate
python3 -m unittest discover -s benchmarks/website-after-hours-v0 -p 'test_*.py'
python3 benchmarks/website-after-hours-v0/benchmark.py prepare \
  --output runs/website-after-hours-v0/first
```

The output contains five independent `entries/A` through `entries/E`
directories and an `operator` directory. Each entry contains only `PROMPT.md`
and `site/`. The operator directory holds the follow-up, checks, score template,
a run setup checklist, and a manifest with SHA-256 hashes. It also copies the
result calculator. Preparation refuses an existing destination.

1. Fill in each participant's model ID, quantization, runtime revision, agent
   harness, sampling settings, context limit, and supported tools in the manifest.
   Use the four local configurations from the earlier comparison and one frontier
   baseline. Shuffle their assignment to A–E before the first run. Keep the mapping
   from visual reviewers.
2. Complete [the run setup checklist](RUN_SETUP.md), qualify each execution path
   on an unrelated fixture, and freeze the settings in [the protocol](PROTOCOL.md)
   before any scored participant starts. Give every participant its own entry
   directory and the same tools.
   Do not expose this repository, the operator directory, or other entries.
3. Give the agent `PROMPT.md`. Serve its site with the command in
   `site/README.md`. Retain its complete transcript and final source snapshot.
4. Review stage 1 using [the browser cases](checks.json) and
   [the visual rubric](REVIEW.md). Record evidence in the result template.
5. Preserve the stage 1 source and prepare C05’s dedicated migration storage,
   including its canceled booking, before sending the follow-up. Give the same
   agent the operator's `FOLLOW_UP.md`, then review stage 2. Rerun the stable
   cases and the changed-rule cases. Keep the original stage 1 result.
6. Calculate a result for each entry:

```bash
python3 runs/website-after-hours-v0/first/operator/benchmark.py score \
  runs/website-after-hours-v0/first/operator/result-template.json
```

Copy the template for each entry before editing it. Replace the path in the
command with that entry's completed result file. An unreviewed template reports
pending cases and `null` final percentages. It never treats missing evidence as
a passing result.

## What you get

- Six fictional rooms, hourly CAD prices, equipment, and four seed reservations.
- Six original SVG room illustrations, covered by the repository MIT license.
  These are illustrations, not photographs of real premises.
- A dependency-free HTML/CSS/JavaScript starter with no booking implementation
  or suggested visual design.
- A frozen two-day booking window, so the task does not age with the wall clock.
- 26 stage 1 cases, including explicit browser time-zone and wall-clock checks.
  Stage 2 replaces two adjacency cases with six changed-rule cases; the other
  24 cases measure regressions.
- Separate functionality, changed-rule success, regression, visual, usability,
  accessibility, and resource-use records. There is no combined leaderboard score.

## Evidence limits

Browser cases require a reviewer to operate each site's actual controls. They
do not depend on invented selectors or a required DOM layout. The calculator
validates the review record; it does not verify screenshot contents or execute
the UI. Attach source snapshots, screenshots, browser logs, and storage exports
to make each result reviewable.

The task, checks, and rubric are public. This is a controlled authored comparison,
not a sealed benchmark.

The default limits permit up to 10 hours of agent work. Budget browser review
separately: five entries require 280 case assessments and at least 80
state/viewport screenshots.

A baseline implemented in the conversation that authored the task is
author-informed. Use a fresh agent context containing only the entry
files for a clean baseline, and record which method you used. One run per model
does not measure repeatability or establish general model rankings.

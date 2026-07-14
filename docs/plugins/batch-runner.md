# Batch Runner

`mere-batch-runner` executes explicit `mere.run` argument arrays from JSONL. It
records durable per-job state, supports resume, and hashes discovered outputs.

## Install

```bash
mere.run plugin install mere-batch-runner
mere-batch-runner doctor
```

## Write a jobs file

Each non-empty JSONL line represents one job with an explicit core command. Keep
credentials out of job arguments and the jobs file.

## Plan and execute

```bash
mere-batch-runner plan \
  --jobs ./jobs.jsonl \
  --output-dir ./batch-out \
  --run-id batch-001
mere-batch-runner run ./batch-out/run.json
```

Or plan and run in one command:

```bash
mere-batch-runner run-jobs \
  --jobs ./jobs.jsonl \
  --output-dir ./batch-out \
  --continue-on-error
```

## Resume semantics

Use the existing manifest after an interruption:

```bash
mere-batch-runner resume ./batch-out/run.json
```

Do not generate a fresh run ID to hide an incomplete batch. The durable manifest
is what connects the job list, completed work, failures, and output hashes.

## Safety

Batch Runner accepts only explicit `mere.run` argument lists; it is not a generic
shell execution service. Review generated job files before execution.

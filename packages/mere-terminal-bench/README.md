# mere-terminal-bench

`mere-terminal-bench` evaluates local `mere.run` text models with the official
Harbor harness and Terminal-Bench 2.1 dataset.

The plugin owns orchestration and receipts. It does not implement model
inference, vendor Terminal-Bench tasks, create a Docker VM, upload results, or
publish leaderboard submissions. `mere.run` owns the local OpenAI-compatible
model endpoint; Harbor owns task execution and verification.

## Install

```bash
mere.run plugin install mere-terminal-bench --yes
uv tool install "harbor==0.22.0"
```

Docker must be available. Select a non-default engine explicitly with
`--docker-context`. The plugin never creates or resizes a Colima or Docker
Desktop runtime.

The selected Docker runtime must mount the planned output directory at the
same absolute path with read and write access. Before starting a model, `run`
uses `busybox:1.37.0` for a small round-trip bind-mount check. This prevents a
verifier reward from being written only inside a Docker VM and then reported as
missing on the host.

## Plan and run

```bash
mere-terminal-bench doctor --docker-context colima-terminal-bench

mere-terminal-bench plan \
  --output /Volumes/SALVATION/mere-run-evidence/ornith-terminal-bench-2-1 \
  --docker-context colima-terminal-bench

mere-terminal-bench run \
  /Volumes/SALVATION/mere-run-evidence/ornith-terminal-bench-2-1/run.json
```

The default matched comparison is:

- Ornith Q4: `text-agent-ornith-35b-mlx-4bit`
- Ornith Q8: `text-agent-ornith-35b-mlx-8bit`
- Terminus-2 with temperature `0.7`
- One attempt per task and one concurrent trial
- A maximum of 64 GiB of additional Docker storage during the run

One attempt per task is an internal model-selection pass, not a qualifying
Terminal-Bench leaderboard submission. Use `--attempts 5` only when the
additional runtime is intentional.

Use `--include-task <name>` or `--n-tasks 1` for smoke runs. Short task names
are normalized to the `terminal-bench/` package namespace. `resume` skips
completed model arms and continues interrupted or failed arms:

```bash
mere-terminal-bench resume ./run.json
mere-terminal-bench report ./run.json
mere-terminal-bench cleanup ./run.json
```

## Storage and cleanup

The plan records the Docker context and storage ceiling before execution. The
plugin measures Docker's reported storage usage while Harbor runs and stops the
job if additional usage crosses the plan's ceiling. Harbor deletes task
containers by default. The plugin stops only the `mere.run` server process it
started; it does not prune shared images, delete Docker contexts, or remove run
artifacts.

An arm succeeds only when Harbor completes every trial, every trial has a
numeric verifier score, and no trial is cancelled. Harbor error counts remain
in the report. A scored timeout doesn't invalidate an arm because the verifier
score remains comparison evidence. A zero Harbor process exit alone isn't
treated as a valid evaluation result.

## Reproducibility pins

- Harbor: `0.22.0`
- Dataset: `terminal-bench/terminal-bench-2-1`
- Dataset digest: `sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`
- Official source commit: `7131e4375048a0e408a8fb404b5f499d726b695b`
- Expected task count: `89`

See `THIRD_PARTY_NOTICES.txt` for upstream licensing.

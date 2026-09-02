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
```

The source package requires Python 3.12 or later. The installation includes
Harbor 0.22.0, so you don't need to install a second Python tool.

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
mere-terminal-bench doctor --deep --docker-context colima-terminal-bench

mere-terminal-bench plan \
  --output /Volumes/SALVATION/mere-run-evidence/ornith-terminal-bench-2-1 \
  --docker-context colima-terminal-bench

mere-terminal-bench run \
  /Volumes/SALVATION/mere-run-evidence/ornith-terminal-bench-2-1/run.json
```

The first `doctor` command checks Harbor, Docker, and `mere.run`. It
doesn't inspect Docker storage or preflight models. The explicit `--deep` check
adds those slower readiness checks and can take several minutes. Neither mode
creates a Docker runtime or task container.

The default matched comparison is:

- Ornith Q4: `text-agent-ornith-35b-mlx-4bit`
- Ornith Q8: `text-agent-ornith-35b-mlx-8bit`
- Terminus-2 with temperature `0.7`
- One attempt per task and one concurrent trial
- A maximum of 64 GiB of additional Docker storage during the run

One attempt per task is an internal model-selection pass. Five attempts per
task consume substantially more runtime but don't make a run eligible for the
Terminal-Bench leaderboard. The plugin produces local evidence and doesn't
upload results or claim leaderboard eligibility.

Use `--include-task TASK_NAME` or `--n-tasks 1` for smoke runs. Short task names
are normalized to the `terminal-bench/` package namespace. If a task filter
contains a glob, you must also pass `--n-tasks` with the expected match count.
The plugin fails the run if Harbor doesn't return that exact count. `resume`
skips completed model arms and continues interrupted or failed arms:

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

An arm succeeds only when Harbor returns the planned number of unique tasks and
attempts, completes every trial, gives every trial a numeric verifier score,
and cancels no trials. Harbor error counts remain in the report. A scored
timeout doesn't invalidate an arm because the verifier score remains comparison
evidence. A zero Harbor process exit alone isn't a valid evaluation result.
Successful and failed runs both produce a hashed artifact bundle.

## Reproducibility pins

- Harbor: `0.22.0`
- Dataset: `terminal-bench/terminal-bench-2-1`
- Dataset digest: `sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`
- Official source commit: `7131e4375048a0e408a8fb404b5f499d726b695b`
- Expected task count: `89`

See `THIRD_PARTY_NOTICES.txt` for upstream licensing.

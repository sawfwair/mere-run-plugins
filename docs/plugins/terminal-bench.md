# Terminal-Bench plugin

This guide is for developers who compare local `mere.run` text models with
Terminal-Bench 2.1. The `mere-terminal-bench` plugin plans and runs a matched
comparison by using the official Harbor harness.

## Why this capability is a plugin

The core `mere.run` CLI owns model loading, inference, and the local
OpenAI-compatible API. The plugin owns the following external orchestration:

- Harbor and dataset version pins
- Docker context selection
- Terminus-2 configuration
- Model-arm sequencing
- Storage monitoring
- Run manifests, reports, and artifact hashes
- Process cleanup

The plugin doesn't create or resize a Docker runtime. It also doesn't upload
results or publish a leaderboard submission.

## Install the plugin

Install the plugin and its pinned Harbor dependency:

```bash
mere.run plugin install mere-terminal-bench --yes
```

The source package requires Python 3.12 or later. The installation includes
Harbor 0.22.0, so you don't need to install a second Python tool.

## Check local readiness

Run a quick dependency check first:

```bash
mere-terminal-bench doctor --docker-context BENCHMARK_CONTEXT
```

Replace `BENCHMARK_CONTEXT` with the name of a running Docker context. The
command checks the pinned Harbor runtime, the selected Docker engine, and the
`mere.run` executable. It doesn't inspect Docker storage, start containers, or
preflight models.

Before a long evaluation, run the deep readiness check:

```bash
mere-terminal-bench doctor --deep --docker-context BENCHMARK_CONTEXT
```

The deep check also reads Docker's reported storage use and preflights both
default Ornith models. It can take several minutes, but it still doesn't create
containers, virtual machines, or storage.

The later `run` command checks the planned output directory with a small
`busybox:1.37.0` container before loading a model. The Docker runtime must see
that host directory at the same absolute path and must be able to write back to
it. For a Colima profile, add the external volume that contains the run
directory to the profile's writable mounts.

## Create a run plan

To create the default Q4 and Q8 comparison, run the following command:

```bash
mere-terminal-bench plan \
    --output RUN_DIRECTORY \
    --docker-context BENCHMARK_CONTEXT
```

Replace the following:

- `RUN_DIRECTORY`: the directory that stores the manifest, Harbor jobs, logs,
  and reports
- `BENCHMARK_CONTEXT`: the Docker context that runs the task containers

The generated `run.json` file records the following controls:

- Harbor version `0.22.0`
- The Terminal-Bench 2.1 dataset digest and source commit
- Both model IDs and the shared Terminus-2 settings
- A shared `balanced` memory guard and 131,072-token context limit
- One attempt per task and one concurrent trial
- A 64 GiB maximum increase in Docker-reported storage
- `createsDockerRuntime: false`

One attempt per task supports internal model selection. Five attempts per task
consume substantially more runtime but don't make a run eligible for the
Terminal-Bench leaderboard. The plugin produces local evidence and doesn't
upload results or claim leaderboard eligibility.

## Run or resume the comparison

To run all pending model arms, use the generated manifest:

```bash
mere-terminal-bench run RUN_DIRECTORY/run.json
```

Task filters accept either `regex-log` or the fully qualified
`terminal-bench/regex-log` package name. If a filter contains a glob, pass
`--n-tasks` with the expected match count. The plugin fails the run if Harbor
doesn't return that exact count. If a model arm stops, resume the run:

```bash
mere-terminal-bench resume RUN_DIRECTORY/run.json
```

The plugin starts one loopback `mere.run` server for each model. It stops the
server before the next arm. Harbor deletes task containers after each trial.

## Inspect the report

To rebuild the matched comparison from Harbor result files, run the following
command:

```bash
mere-terminal-bench report RUN_DIRECTORY/run.json
```

The `report.json` file contains per-model accuracy, errors, tokens, agent-only
execution time, output tokens per agent second, and pairwise quality and speed
wins. Agent-only timing separates model and agent-loop speed from Docker image
setup and verifier time. The `artifact-bundle.json` file records SHA-256 hashes
for the run manifest, report, model configurations, server logs, and Harbor job
results.

The plugin fails closed when Harbor doesn't return the planned number of unique
tasks and attempts, doesn't complete every trial, cancels a trial, or omits a
numeric verifier score. Harbor error counts remain in the report. A scored
exception, including a timeout, doesn't invalidate an arm. A successful Harbor
process exit doesn't replace these completeness checks. Successful and failed
runs both produce a hashed artifact bundle.

## Stop a recorded server

To stop a server process that the manifest still records, run the following
command:

```bash
mere-terminal-bench cleanup RUN_DIRECTORY/run.json
```

Cleanup verifies the process command and model ID before it sends `SIGTERM`.
Cleanup doesn't prune images, delete Docker contexts, or remove run artifacts.

For upstream task and submission requirements, see the
[Terminal-Bench 2.1 repository](https://github.com/harbor-framework/terminal-bench-2-1).
For agent configuration details, see the
[Harbor Terminus-2 documentation](https://github.com/harbor-framework/harbor/blob/main/docs/content/docs/agents/terminus-2.mdx).

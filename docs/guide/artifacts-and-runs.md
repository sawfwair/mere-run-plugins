# Artifacts and runs

`run.json` is the connective tissue of every workflow.

## What it records

The stable contract can represent:

- contract version, run ID, status, and timestamps;
- plugin and recipe identity;
- local inputs and resolved commands;
- provider configuration and resource identity;
- ordered execution steps;
- artifact paths, content types, labels, and hashes;
- failure details and cleanup status.

The exact schema is documented under [Run manifest](/reference/run-manifest).

## Why it is written early

If a provider process stops after creating a pod but before saving its identity,
the user can be left with an untracked paid resource. Provider plugins therefore
write the manifest before external mutation and update it immediately after a
resource is created.

## Artifact integrity

Local production plugins hash completed outputs. Provider runners fetch outputs
into an artifact bundle that inventories the received files. Hashes let later
automation verify that the artifact under review is the one the run produced.

## Store runs with the work

Keep the manifest beside the output directory or in the production system that
references those outputs. It supports:

- later provenance and review;
- safe resume after interruption;
- explicit provider cleanup;
- debugging without reconstructing the original command;
- agent and pipeline integration through stable JSON.

## Streams

When a command promises JSON or paths, stdout is reserved for that structured
result. Human diagnostics and child-process logs go to stderr. This separation
allows callers to parse stdout without losing useful operator feedback.

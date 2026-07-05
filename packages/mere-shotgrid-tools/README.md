# mere-shotgrid-tools

ShotGrid, now Autodesk Flow Production Tracking, companion tools for publishing
local `mere.run` artifacts into production review.

The plugin does not run inference and does not turn `mere.run` into a hosted
service. It bridges local run manifests and artifact files into user-owned
ShotGrid projects by creating Versions, optional Notes, Playlist links, and Task
status updates.

## Install

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-shotgrid-tools"
```

## Credentials

Use a dedicated Flow Production Tracking Script entity when possible:

```bash
export MERE_SHOTGRID_URL="https://example.shotgrid.autodesk.com"
export MERE_SHOTGRID_SCRIPT_NAME="mere-shotgrid-tools"
export MERE_SHOTGRID_API_KEY="..."
```

User login/password authentication is also supported through
`MERE_SHOTGRID_LOGIN` and `MERE_SHOTGRID_PASSWORD`.

## Publish Review Artifacts

```bash
mere-shotgrid-tools plan \
  --project-id 123 \
  --entity-type Shot \
  --entity-id 456 \
  --task-id 789 \
  --artifact ./renders/shot010_v003.mov \
  --thumbnail ./renders/shot010_v003.png \
  --note "Local mere.run pass ready for review." \
  --output-dir ./shotgrid-publish \
  --run-id shot010-v003

mere-shotgrid-tools run ./shotgrid-publish/run.json
```

`publish` combines the two steps:

```bash
mere-shotgrid-tools publish \
  --project-id 123 \
  --entity-type Shot \
  --entity-id 456 \
  --artifact ./renders/shot010_v003.mov \
  --output-dir ./shotgrid-publish \
  --run-id shot010-v003
```

The plugin writes `run.json` before any remote mutation and updates it after
each ShotGrid create, upload, or update call.

## Pull Tasks

`pull-tasks` reads ShotGrid Tasks and emits JSONL job requests for local
workflow tools:

```bash
mere-shotgrid-tools pull-tasks \
  --project-id 123 \
  --assignee-id 42 \
  --status rdy \
  --tool shot-kit \
  --output ./shotgrid-jobs.jsonl
```

The resulting JSONL can be fed into local relay or batch tooling without moving
inference into ShotGrid.

# ShotGrid Tools Plugin

`mere-shotgrid-tools` publishes local `mere.run` artifacts into ShotGrid, now
Autodesk Flow Production Tracking, as production review records.

The plugin is a companion executable. It does not run hosted inference and does
not extend the core `mere.run` command tree. ShotGrid decides what production
work exists; local or user-controlled `mere.run` workflows produce artifacts;
this plugin records what was produced.

## Commands

```bash
mere-shotgrid-tools manifest --json
mere-shotgrid-tools doctor
mere-shotgrid-tools plan \
  --project-id 123 \
  --entity-type Shot \
  --entity-id 456 \
  --task-id 789 \
  --artifact ./review.mov \
  --thumbnail ./poster.png \
  --note "Ready for review." \
  --output-dir ./publish \
  --run-id shot010-v003
mere-shotgrid-tools run ./publish/run.json
mere-shotgrid-tools publish \
  --project-id 123 \
  --entity-type Shot \
  --entity-id 456 \
  --artifact ./review.mov \
  --output-dir ./publish \
  --run-id shot010-v003
mere-shotgrid-tools pull-tasks \
  --project-id 123 \
  --assignee-id 42 \
  --status rdy \
  --tool shot-kit \
  --output ./jobs.jsonl
mere-shotgrid-tools cleanup ./publish/run.json
```

## Credentials

The plugin reads credentials from explicit flags or environment variables:

- `MERE_SHOTGRID_URL`, `SHOTGRID_URL`, or `SG_URL`
- `MERE_SHOTGRID_SCRIPT_NAME`, `SHOTGRID_SCRIPT_NAME`, or `SG_SCRIPT_NAME`
- `MERE_SHOTGRID_API_KEY`, `SHOTGRID_API_KEY`, or `SG_API_KEY`
- `MERE_SHOTGRID_LOGIN` and `MERE_SHOTGRID_PASSWORD` for user auth

Credentials are never written to `run.json`, stdout, or planned command arrays.

## Publish Shape

A publish creates one ShotGrid `Version` linked to a Project and optional
Shot/Asset/Task. It can also:

- upload artifacts to the Version
- upload a thumbnail to the Version
- create a review Note linked to the Version and target entity
- add the Version to an existing or newly-created Playlist
- update the linked Task status

`cleanup` is a no-op by default. Deleting production-tracking records requires
explicit flags and only operates on records stored in the run manifest as records
created by this plugin.

## Task Pull Shape

`pull-tasks` queries assigned ShotGrid Tasks and emits JSONL requests that can
be run by local relay or batch tooling. It performs no remote mutations.

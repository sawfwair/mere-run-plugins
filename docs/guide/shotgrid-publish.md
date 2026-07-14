# Publish to ShotGrid

`mere-shotgrid-tools` bridges local `mere.run` artifacts into Flow Production
Tracking without moving inference into ShotGrid.

## Check configuration

```bash
mere.run plugin install mere-shotgrid-tools
mere-shotgrid-tools doctor
```

The plugin requires the ShotGrid site and script credentials documented under
[Environment](/reference/environment).

## Plan a review Version

```bash
mere-shotgrid-tools plan \
  --project-id 123 \
  --entity-type Shot \
  --entity-id 456 \
  --artifact ./review.mov \
  --output-dir ./runs/shotgrid-publish \
  --run-id shot-010-review
```

The plan identifies the target entity and local artifact before any provider
mutation. Execute the written manifest only after verifying both.

## Production actions

The plugin can create a Version, upload review media, create a Note, link a
Playlist, and update task status. It can also query task-backed jobs into JSONL
for local relay or [Batch Runner](/plugins/batch-runner) workflows.

See [ShotGrid Tools](/plugins/shotgrid-tools) for command examples and boundaries.

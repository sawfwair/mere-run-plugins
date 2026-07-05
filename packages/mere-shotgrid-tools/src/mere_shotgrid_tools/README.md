# mere_shotgrid_tools Source Map

`mere_shotgrid_tools` is the ShotGrid / Flow Production Tracking bridge. It
publishes local artifacts as review Versions and pulls ShotGrid Tasks into local
job JSONL.

Entry points:

- `__main__.py`: module execution shim.
- `cli.py`: command parser, credential loading, ShotGrid client protocol,
  artifact collection, publish manifest creation, remote publish execution,
  resume, cleanup, and task-pull commands.

Important boundaries:

- Redact credentials; never write secrets to manifests or stdout.
- Treat ShotGrid SDK responses as untrusted provider data and narrow them
  before mutating manifests.
- Cleanup is intentionally destructive only with `--delete-created-records` and
  a matching `--confirm-run-id`.
- `plan` and `publish --dry-run` must not create remote records.
- Keep task-pull output as JSONL jobs that local tools can consume.

Do not add live network calls to default tests or the repo gate.

# mere_runpod Source Map

`mere_runpod` is the RunPod provider plugin. It plans and runs canonical
`mere.run` LoRA recipes on user-owned ephemeral RunPod pods.

Entry points:

- `__main__.py`: module execution shim.
- `cli.py`: command parser, recipe loading, manifest creation, RunPod API
  boundary checks, SSH/rsync orchestration, artifact fetch, resume, volume, and
  cleanup commands.
- `recipes/`: packaged recipe JSON used by `load_recipe`.

Important boundaries:

- Keep stdout JSON-only for plugin commands.
- Treat RunPod GraphQL/REST responses as untrusted at the boundary and narrow
  them before use.
- Write `run.json` before creating or mutating remote resources.
- Keep paid-resource paths behind `plan`, `--dry-run`, or explicit user action.
- Default cleanup terminates pods unless `--keep-pod` is set.

Do not move canonical model behavior into this package. That belongs in the
core `mere.run` repo.

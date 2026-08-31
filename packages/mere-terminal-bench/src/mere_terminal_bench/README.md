# mere_terminal_bench Source Map

`mere_terminal_bench` orchestrates pinned Terminal-Bench comparisons against
local models served by `mere.run`.

Entry points:

- `__main__.py`: module execution shim.
- `cli.py`: manifest, readiness, planning, Harbor configuration, model-arm
  execution, storage monitoring, reporting, and cleanup commands.
- `recipes/`: packaged benchmark recipe with the Harbor, dataset, source, agent,
  inference, model, and resource pins.

Important boundaries:

- Keep stdout JSON-only and diagnostics on stderr.
- Write `run.json` before starting a model server or Harbor.
- Use an existing Docker context. Never create or resize a virtual machine or
  disk.
- Stop Harbor when Docker-reported growth crosses the planned ceiling. Never
  prune shared Docker state automatically.
- Accept a completed trial when it has a numeric verifier score, even if Harbor
  records an exception. Preserve exception counts in the report.
- Require the exact planned task and attempt counts before an arm succeeds.
- Replace local OpenAI-compatible credentials with a non-secret placeholder
  before Harbor starts.
- Write reports and hashed artifact bundles for successful and failed runs.
- Keep model loading and inference in the installed `mere.run` executable.
- Do not upload results or publish leaderboard submissions.

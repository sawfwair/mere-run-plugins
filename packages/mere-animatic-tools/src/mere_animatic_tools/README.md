# mere_animatic_tools Source Map

`mere_animatic_tools` contains local production helpers for Animatic workflows.
It generates reviewable files from request JSON and local or downloaded image
inputs.

Entry points:

- `__main__.py`: module execution shim.
- `cli.py`: command parser, tool registry, request loading, artifact manifest
  helpers, local image/contact-sheet utilities, tool executors, resume, and
  cleanup commands.
- `set_proxy.py`: USD set-proxy serialization and the explicit Blender process
  boundary.
- `blender_worker.py`: Blender-only scene construction, lighting receipts, and
  plate rendering; unit tests inject a typed fake `bpy` backend.

Important boundaries:

- Commands write machine-readable JSON to stdout.
- Local artifacts are recorded in `run.json` under `artifacts.files`,
  `artifacts.items`, and `artifacts.sha256`.
- Downloads are best-effort input staging; failures are diagnostics, not remote
  side effects.
- Cleanup only marks local state because this package creates no remote
  resources.

Do not introduce hosted dependencies or live network requirements beyond
explicit asset download URLs supplied by the request.

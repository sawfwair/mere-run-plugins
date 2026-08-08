# mere_vfx_tools Source Map

`mere_vfx_tools` is the local shot-oriented VFX companion plugin.

- `__main__.py` is the module execution shim.
- `cli.py` owns the manifest and command parser, request validation, durable run
  state, native-model handoffs, deterministic FFmpeg assembly, artifact hashes,
  resume, and cleanup for every registered VFX tool.

Keep JSON stdout machine-readable and child-process diagnostics on stderr.
Model inference stays in the user-selected `mere.run` executable; media
assembly stays in the user-selected `ffmpeg` executable. When adding a tool,
update its manifest entry, validation, docs, examples, and tests together.

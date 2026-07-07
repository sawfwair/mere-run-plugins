# mere_perform Source Map

`mere_perform` is the local realtime performance plugin. It plans Magenta Heart
shows, exports a static stage UI, and executes the installed `mere.run music
realtime` command when asked.

Entry points:

- `__main__.py`: module execution shim.
- `cli.py`: command parser, show normalization, run-manifest creation, stage UI
  export, realtime execution, event logging, resume, devices, and cleanup
  commands.

Important boundaries:

- Keep stdout JSON-only for plugin commands.
- Treat show and manifest JSON as untrusted until narrowed.
- Do not embed another Magenta runtime; call the user's `mere.run` executable.
- Keep prompt strategy metadata in the show manifest so stage UI, runtime
  stdin commands, and recorded events describe the same palette.
- Keep MIDI hardware ingestion native to `mere.run`; this package owns
  controller metadata, planning, and stage visualization only.
- Write `run.json` during planning and update it through execution.
- Cleanup is local-state only because this package creates no remote resources.

When changing the show contract, update package docs, catalog metadata, tests,
and validation in the same change.

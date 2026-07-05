# mere_image_tools Source Map

`mere_image_tools` contains local image helper commands for planning and
producing image artifacts around existing `mere.run` capabilities.

Entry points:

- `__main__.py`: module execution shim.
- `cli.py`: command parser, manifest creation, image segmentation/knockout
  planning, artifact recording, local execution helpers, resume, and cleanup
  commands.

Important boundaries:

- Keep JSON command output on stdout and diagnostics on stderr.
- Treat request and manifest JSON as untrusted until narrowed.
- Prefer existing `mere.run` image behavior instead of adding parallel model
  logic here.
- Cleanup is local-state only; this package does not create remote resources.

When adding a command, update the manifest, docs, examples, and tests together.

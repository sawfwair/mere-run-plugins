# mere_workflow_tools Source Map

`mere_workflow_tools` contains local workflow helpers for documents, media,
datasets, transcripts, images, and batch request files.

Entry points:

- `__main__.py`: package command shim.
- `cli.py`: shared command parser, manifest helpers, execution dispatch,
  artifact tracking, resume, and cleanup commands.
- `doc_cli.py`, `media_cli.py`, `dataset_cli.py`, `transcript_cli.py`,
  `image_compose_cli.py`, `batch_cli.py`: focused command wrappers.

Important boundaries:

- Keep stdout JSON-only for plugin commands.
- Treat request and manifest JSON as untrusted until narrowed.
- Keep wrappers thin; shared run-manifest behavior belongs in `cli.py`.
- Cleanup is local-state only unless a future provider-specific module documents
  otherwise.

When adding a workflow surface, keep the command, manifest contract, package
README, examples, and tests in the same change.

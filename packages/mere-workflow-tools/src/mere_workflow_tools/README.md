# mere_workflow_tools Source Map

`mere_workflow_tools` contains local workflow helpers for documents, media,
datasets, transcripts, images, and batch request files.

Entry points:

- `__main__.py`: package command shim.
- `cli.py`: shared command parser, manifest helpers, execution dispatch,
  artifact tracking, resume, and cleanup commands.
- `doc_cli.py`, `media_cli.py`, `dataset_cli.py`, `transcript_cli.py`,
  `image_compose_cli.py`, `batch_cli.py`: focused command wrappers.
- `identity_cli.py`: generic identity graph-provider facade for a separately
  installed local backend; product-specific identities never enter this repo.
- `anydoc_backend.py`: typed Firecrawl AnyDoc boundary for local
  document-to-Markdown conversion; hosted OCR is always rejected.

Important boundaries:

- Keep stdout JSON-only for plugin commands.
- Treat request and manifest JSON as untrusted until narrowed.
- Keep wrappers thin; shared run-manifest behavior belongs in `cli.py`.
- Cleanup is local-state only. A provider-specific module must document any
  remote resource that it creates.

`doc_graph_provider.py` exposes local document conversion through the graph SDK,
with confined artifacts and replayable run manifests.

When adding a workflow surface, keep the command, manifest contract, package
README, examples, and tests in the same change.

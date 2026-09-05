# mere_archive_tools

This package implements the `mere-archive-tools` companion CLI.

- `cli.py` owns lifecycle commands, resumable traversal, retention policy, and
  search results.
- `database.py` owns the SQLite schema, full-text search, deduplication, and
  compact vector storage.
- `extractors.py` reads text and converts documents in memory with local
  AnyDoc.
- `runtime.py` calls local `mere.run` captioning, OCR, PII reduction, and
  multimodal embedding commands.
- `pi_harness.py` runs bounded, read-only investigations through the bundled Pi
  extensions and validates source-linked claims.

Source files remain read-only. Unreduced extracted text stays in memory or a
temporary caption directory and is removed before the index stores derived
data.

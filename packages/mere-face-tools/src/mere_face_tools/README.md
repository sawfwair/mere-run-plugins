# mere_face_tools

This package is the implementation of the `mere-face-tools` companion CLI.

- `cli.py` owns manifests, recursive library traversal, resumable warm-batch
  execution, reference search, and review exports.
- `database.py` owns the versioned SQLite schema and compact normalized
  embedding storage.

Inference stays in the installed `mere.run vision face` runtime. Source photos
are read only; search results are JSON, CSV, a contact sheet, and symlinks.

# mere-face-tools

`mere-face-tools` turns the raw `mere.run vision face` commands into durable,
resumable photo-library workflows. It does not ship another inference runtime.

```bash
mere.run model pull vision-face-buffalo-l

mere-face-tools index \
  --photos /Volumes/Photos \
  --database ./faces.sqlite3 \
  --output-dir ./face-index

mere-face-tools search \
  --database ./faces.sqlite3 \
  --reference ./scott.jpg \
  --output-dir ./searches/scott
```

Indexing uses the warm-session `mere.run vision face batch` JSONL surface and
stores normalized embeddings, boxes, landmarks, source size, and modification
time in SQLite. An interrupted run can be continued with:

```bash
mere-face-tools resume ./face-index/run.json
```

Search ranks the best face per photo, writes JSON and CSV, creates non-mutating
symlink exports under `strong/`, `likely/`, and `review/`, and renders a contact
sheet. The original library is never modified.

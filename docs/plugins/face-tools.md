# Face Tools

`mere-face-tools` turns native `mere.run` face detection and embeddings into a
durable photo-library index and reference-face search. It traverses the library,
tracks changed files, stores normalized face records in SQLite, and produces
review artifacts. Core `mere.run` continues to own model download and inference.

## Install and check readiness

```bash
mere.run plugin install mere-face-tools
mere.run model pull vision-face-buffalo-l
mere-face-tools doctor
```

`doctor` checks the local `mere.run` face-analysis surface and SQLite support.
The plugin does not require provider credentials or create paid resources.

## Index a photo library

```bash
mere-face-tools index \
  --photos /Volumes/Photos \
  --database ./faces.sqlite3 \
  --output-dir ./face-index
```

Indexing uses the warm-session `mere.run vision face batch` JSONL interface and
stores normalized embeddings, bounding boxes, landmarks, source dimensions,
and modification times. It writes `run.json` before execution and can continue
an interrupted scan:

```bash
mere-face-tools resume ./face-index/run.json
```

Unchanged photos are skipped when the library is indexed again.

## Search by reference face

```bash
mere-face-tools search \
  --database ./faces.sqlite3 \
  --reference ./reference.jpg \
  --output-dir ./searches/reference
```

Search embeds the reference image, ranks the best matching face per photo, and
writes JSON, CSV, and a contact sheet. Symlink-only review folders group results
under `strong/`, `likely/`, and `review/` without copying the originals.

## Privacy and source safety

Detection, embeddings, indexing, and search run locally. The plugin never
modifies the source photo library. The SQLite database and review artifacts may
contain sensitive biometric relationships, so keep the output directory under
the same access controls as the original library and remove it deliberately
when it is no longer needed.

`cleanup` records the local cleanup decision but does not delete source photos
or the index automatically.

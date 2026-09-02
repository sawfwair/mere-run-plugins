# mere-archive-tools

Build a local, searchable index from a read-only shared drive. The plugin
converts documents with AnyDoc, captions and reads text from images with
`mere.run`, reduces personally identifiable information (PII), and stores
shared text and image embeddings in SQLite.

Install the distributable plugin bundle with mere.run. The bundle includes its
own runtime, so installation doesn't require Python or a package manager.

```bash
mere.run plugin install mere-archive-tools --yes
```

Choose one retention tier:

- `full-content` stores complete PII-reduced text, captions, OCR, and vectors.
- `safe-content` stores a short PII-reduced summary, keywords, and vectors.
- `pointers` stores file pointers, fingerprints, metadata, and vectors.

The plugin never modifies source files. It doesn't provide access control,
retention policy, or document-management features. Adapt those controls to
your organization.

```bash
mere-archive-tools index \
  --source /Volumes/Shared \
  --database ./archive.sqlite3 \
  --output-dir ./archive-run \
  --storage-tier safe-content

mere-archive-tools search \
  --database ./archive.sqlite3 \
  --query "Halifax installation photos"
```

Create a fictional mixed-file benchmark before you point the plugin at a real
shared drive:

```bash
mere-archive-tools benchmark prepare --output-dir ./archive-benchmark
mere-archive-tools index \
  --source ./archive-benchmark/source \
  --database ./archive-benchmark-safe.sqlite3 \
  --output-dir ./archive-benchmark-safe-run
mere-archive-tools benchmark evaluate \
  ./archive-benchmark/benchmark.json \
  --database ./archive-benchmark-safe.sqlite3 \
  --output ./archive-benchmark-safe-report.json
```

The generated Mere Archive Gauntlet includes 18 files, office documents,
images, exact duplicates, fake PII canaries, and 16 retrieval questions. Use
`benchmark mutate` to apply a controlled rename, edit, deletion, and addition,
then reindex the same database to test incremental behavior.

Image indexing defaults to PII-reduced captions and OCR. Pass `--image-index
visual` to add embeddings of source pixels. Visual embeddings can preserve
sensitive visual relationships that text reduction doesn't remove.

Run `mere-archive-tools benchmark sources` to inspect the pinned ViDoRe and
GovDocs1 download-on-demand datasets. Public dataset files aren't included in
the plugin bundle.

The distributable bundle includes Python 3.12 and AnyDoc. Python 3.10 or later
is only required when running directly from source. Hosted OCR is never
enabled.

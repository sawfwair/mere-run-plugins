# Archive Tools

This guide is for teams that need to search years of mixed files on a shared
drive. `mere-archive-tools` builds a local SQLite index without modifying the
source files or uploading them to a hosted service.

The plugin is an adaptable indexing tool, not a document-management product.
Your organization owns authentication, authorization, retention, encryption,
backup, and sharing policy.

## Install and check readiness

Install the plugin from the public catalog:

```bash
mere.run plugin install mere-archive-tools --yes
mere-archive-tools doctor
```

The distributable bundle includes Python 3.12 and AnyDoc 0.2.4; it doesn't use
the user's Python environment or a package manager. Text and image workflows
also use these local `mere.run` commands:

- `mere.run text anonymize`
- `mere.run vision caption`
- `mere.run vision ocr`
- `mere.run vision embed`

`doctor` checks each command, SQLite full-text search, and AnyDoc. The plugin
doesn't use credentials or create paid resources.

Python 3.10 or later is required only when contributors run the package
directly from source.

## Choose a storage tier

Every tier stores file paths, relative paths, file fingerprints, metadata, and
embeddings. The plugin reduces personally identifiable information (PII) from
text before it creates those embeddings. The following table describes the
additional retained data and search behavior.

| Storage tier | Retained derived content | Search behavior |
| --- | --- | --- |
| `full-content` | Complete PII-reduced document text, captions, OCR, keywords, and chunk text | Semantic search, full-text search, result snippets, and duplicate paths |
| `safe-content` | A short PII-reduced extractive summary and keywords; no complete extracted body | Semantic search, summary full-text search, and short result snippets |
| `pointers` | No extracted text, captions, OCR, summaries, keywords, or chunk text | Semantic search from retained vectors; results point to source files |

The `safe-content` tier is the default. The word *safe* describes reduced
retention, not a security guarantee. Embeddings and file paths can still reveal
sensitive relationships.

In `full-content`, *full* means the complete PII-reduced derivative. The plugin
never stores the original binary or unreduced extracted text in the index.

## Build an index

To create the recommended reduced-content index, run the following command:

```bash
mere-archive-tools index \
  --source /Volumes/Shared \
  --database ./archive.sqlite3 \
  --output-dir ./archive-run \
  --storage-tier safe-content
```

The `--database` and `--output-dir` paths must be outside the source tree. The
plugin rejects configurations that could write generated files to the shared
drive.

The index supports these source types:

- UTF-8 text, Markdown, JSON, JSON Lines, XML, YAML, reStructuredText, and log files.
- DOCX, PPTX, XLSX, PDF, RTF, EPUB, and CSV files through local AnyDoc conversion.
- BMP, HEIC, HEIF, JPEG, PNG, TIFF, and WebP images through local captioning and OCR.

AnyDoc receives `ocr="reject"` for every conversion. A scanned PDF produces a
recorded file error instead of using hosted OCR. To index a scanned PDF, render
its pages to images and index those images.

## Understand the privacy sequence

The plugin processes each unique file in this order:

1. It reads the source file and computes a SHA-256 fingerprint.
2. It extracts document text or creates image captions and OCR in temporary storage.
3. It reduces PII with `mere.run text anonymize`, followed by deterministic
   email and phone matching.
4. It chunks and embeds only the PII-reduced text.
5. It stores data according to the selected tier.
6. It discards temporary unreduced derivatives.

There is no option that bypasses PII reduction. The privacy model reduces
exposure, but it might not detect every sensitive value. Keep the database
under controls that are appropriate for the source collection.

## Control image embeddings

The default `--image-index captions` mode embeds PII-reduced captions and OCR.
It doesn't embed source pixels.

To improve text-to-image retrieval, opt in to visual embeddings:

```bash
mere-archive-tools index \
  --source /Volumes/Shared \
  --database ./archive-visual.sqlite3 \
  --output-dir ./archive-visual-run \
  --storage-tier safe-content \
  --image-index visual
```

Visual embeddings can encode people, places, and other sensitive visual
relationships. Text reduction doesn't sanitize source pixels. Use visual mode
only when your organization's policy permits that derived data.

## Search the index

To find relevant files, send a natural-language query:

```bash
mere-archive-tools search \
  --database ./archive.sqlite3 \
  --query "photographs of the blue pump installed outdoors"
```

The plugin reduces PII in the query before embedding it. Search combines shared
text and image vector similarity with SQLite full-text matching when the tier
retains searchable text. Results include every duplicate source path for each
matching content record.

The source drive must remain mounted to open results. The `available` field in
each path record reports whether the source file is present during the search.

## Investigate a compound question

Use the investigator when one question requires evidence from several files.
The command uses Pi to refine archive searches and assemble source-linked
claims. It doesn't replace the index or guarantee complete retrieval.

Install Pi and the default local model before the first investigation:

```bash
mere.run agent onboard --install-pi
mere.run model pull text-chat-bonsai-27b-2bit
```

To investigate the Freezer 3 repair, run the following command:

```bash
mere-archive-tools investigate \
  --database ./archive.sqlite3 \
  --question "Was the Freezer 3 repair covered by warranty, and when does that warranty expire?"
```

The command performs these actions:

1. It reduces PII in the question.
2. It starts a temporary loopback `mere.run` server with the 2-bit Bonsai
   model.
3. It gives Pi only the `archive_search` tool. Pi can't read arbitrary files,
   run shell commands, or change the archive.
4. It permits up to four searches with five results per search.
5. It checks the claim structure and requires citations to match returned paths.
6. It stops the temporary server and returns structured JSON.

Before each search, the launcher checks current machine admission capacity,
queued work, and memory pressure. It keeps the chat server resident when a
search can run. When capacity is constrained, it stops its own server, runs
the search, and restarts the server before Pi continues. The runtime's admission
and memory guards remain active.

The result includes the reduced question, the model ID, the authoritative
search trace, supported or unresolved claims, and the enforced limits. The
validator rejects fabricated citation paths. It doesn't determine whether a
snippet entails a claim or whether conflicting or missing records exist.
Review the cited evidence before relying on the answer.

To change the investigation budget, use `--max-searches` and `--top`. The
launcher accepts at most eight searches and 10 results per search. The default
model is `text-chat-bonsai-27b-2bit`; pass `--model` and `--engine` together to
use another installed tool-capable model.

The default context contains 16,384 tokens. The first search must start within
60 seconds of Pi startup, and each search has a 60-second deadline. The entire
Pi loop, including one contract-repair retry, has a 300-second deadline. Use
`--first-search-timeout`, `--search-timeout`, and `--pi-timeout` to change these
limits. Server preflight and each startup have a separate `--server-timeout`
limit, with restarts also bounded by the remaining Pi deadline.

Use `--diagnostics ./investigation-metrics.json` to save timing events and
sampled peak process-tree memory, including on failure. Diagnostics omit the
question, search terms, archive text, citations, and hidden reasoning. Successful
JSON results include the same metrics. RSS measurements include the launcher,
Pi, and its inference processes; they exclude other applications and macOS.
`missedMemorySamples` counts failed RSS observations without aborting inference.

The result follows the
[Archive Investigation contract](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/archive-investigation.v1.schema.json).
See the [illustrative result](https://github.com/sawfwair/mere-run-plugins/blob/main/examples/archive/investigation.result.json)
and [acceptance report](https://github.com/sawfwair/mere-run-plugins/blob/main/packages/mere-archive-tools/ACCEPTANCE.md)
for the output shape and measured validation limits.

The launcher cleans up its process groups on completion, errors, timeouts,
Ctrl-C, and `SIGTERM`. It reads the index through a read-only connection and
rejects output paths inside the source tree.

## Resume and inspect indexing

The plugin compares each file's size and modification time before it runs
inference. It hashes changed files and stores identical content only once.

To continue an interrupted run, use its manifest:

```bash
mere-archive-tools resume ./archive-run/run.json
```

To review coverage and retention settings, inspect the database:

```bash
mere-archive-tools stats --database ./archive.sqlite3
```

After a later index run, the plugin removes database records for source files
that are no longer present. It doesn't delete or change source files.

## Test with the Mere Archive Gauntlet

Before you index a real shared drive, generate the fictional mixed-file test
collection:

```bash
mere-archive-tools benchmark prepare \
  --dataset mere-archive-gauntlet \
  --output-dir ./archive-benchmark
```

The generator uses only code and data included in the plugin. It doesn't use
the network. The baseline contains 18 files in nested, inconsistent folders:

- Text, Markdown, JSON, JSON Lines, XML, YAML, reStructuredText, and log files.
- DOCX, PPTX, XLSX, PDF, RTF, EPUB, and CSV files.
- Two PNG files with visible labels.
- One exact duplicate stored under an old backup path.
- Two fictional PII canaries: an example email address and an `800-555-01xx`
  phone number.
- 16 questions with document-level relevance judgments.

Index the generated `source` directory as though it were the shared drive:

```bash
mere-archive-tools index \
  --source ./archive-benchmark/source \
  --database ./archive-benchmark-safe.sqlite3 \
  --output-dir ./archive-benchmark-safe-run \
  --storage-tier safe-content
```

Evaluate custody, retention, privacy, deduplication, coverage, and retrieval:

```bash
mere-archive-tools benchmark evaluate \
  ./archive-benchmark/benchmark.json \
  --database ./archive-benchmark-safe.sqlite3 \
  --output ./archive-benchmark-safe-report.json
```

The command fails if the source changed unexpectedly, the database contains a
stale or missing path, duplicate bytes use different content records, the
storage tier violates its retention contract, or an exact PII canary appears
in retained SQLite text or database bytes. The canary scan detects exact test
values; it isn't proof that all sensitive information or embedding-level
relationships were removed.

The report includes Recall@1, Recall@5, Recall@10, hit rate, MRR@10, and local
query-latency statistics. Retrieval quality is informational unless you set a
threshold. The following example requires Recall@5 of at least 0.8 and MRR@10
of at least 0.6:

```bash
mere-archive-tools benchmark evaluate \
  ./archive-benchmark/benchmark.json \
  --database ./archive-benchmark-safe.sqlite3 \
  --minimum-recall-at-5 0.8 \
  --minimum-mrr-at-10 0.6
```

The generated manifest follows the
[Archive Benchmark contract](https://mere.run/contracts/archive-benchmark.v1.schema.json).
The result follows the
[Archive Benchmark Report contract](https://mere.run/contracts/archive-benchmark-report.v1.schema.json).

### Compare all storage tiers

Use a separate database for each tier. The database records its tier and
rejects later attempts to change that setting.

```bash
for TIER in full-content safe-content pointers; do
  mere-archive-tools index \
    --source ./archive-benchmark/source \
    --database "./archive-${TIER}.sqlite3" \
    --output-dir "./archive-${TIER}-run" \
    --storage-tier "${TIER}"
  mere-archive-tools benchmark evaluate \
    ./archive-benchmark/benchmark.json \
    --database "./archive-${TIER}.sqlite3" \
    --output "./archive-${TIER}-report.json"
done
```

Compare `databaseSizeBytes`, the retention check, and the retrieval metrics in
the three reports.

### Test an incremental reindex

The mutation command changes only the generated fixture. It refuses public
datasets and a fixture that no longer matches the exact baseline hashes.

```bash
mere-archive-tools benchmark mutate ./archive-benchmark/benchmark.json
mere-archive-tools index \
  --source ./archive-benchmark/source \
  --database ./archive-benchmark-safe.sqlite3 \
  --output-dir ./archive-benchmark-mutated-run \
  --storage-tier safe-content
mere-archive-tools benchmark evaluate \
  ./archive-benchmark/benchmark.json \
  --database ./archive-benchmark-safe.sqlite3 \
  --output ./archive-benchmark-mutated-report.json
```

This phase moves the duplicate, edits the Calgary record, removes a legacy log,
and adds a Bridgewater crane inspection. The evaluator detects the phase from
the complete source path and SHA-256 set. It then checks that the old paths are
gone, the added paths are indexed, and the duplicate still shares one content
record.

### Test connected business questions

The Harbourline benchmark models a fictional regional cold-storage company. Its
58 files connect maintenance, safety, procurement, compliance, finance, and
capital-planning records across six facilities. Unlike the smaller gauntlet,
its 30 questions can require several related files to answer one operational
question.

Generate the fictional archive:

```bash
mere-archive-tools benchmark prepare \
  --dataset harbourline-operations-archive \
  --output-dir ./harbourline-benchmark
```

The collection includes two duplicate groups, two fictional PII canaries,
eight image fixtures, and 14 supported formats. Example questions cover an
urgent freezer repair, a fire-door closeout, a stormwater cleanout decision,
solar performance, generator readiness, a warehouse lease, a network change,
and a capital-replacement case.

## Test with public datasets

Inspect the pinned dataset metadata before downloading anything:

```bash
mere-archive-tools benchmark sources
```

The plugin exposes two download-on-demand options. Neither dataset is included
in the distributable plugin bundle.

### Measure real visual document retrieval

Prepare 100 rows from the pinned
[ViDoRe government-reports test set](https://huggingface.co/datasets/vidore/syntheticDocQA_government_reports_test):

```bash
mere-archive-tools benchmark prepare \
  --dataset vidore-government-reports \
  --limit 100 \
  --output-dir ./vidore-government-reports
```

The adapter requests the pinned dataset revision, downloads each selected page
image, records its SHA-256 value, groups repeated questions and relevant pages,
and writes the same benchmark contract as the generated fixture. To prepare
the complete test split, set `--limit 1000`.

Create separate caption and visual indexes to measure the value of source-pixel
embeddings:

```bash
mere-archive-tools index \
  --source ./vidore-government-reports/source \
  --database ./vidore-captions.sqlite3 \
  --output-dir ./vidore-captions-run \
  --image-index captions
mere-archive-tools index \
  --source ./vidore-government-reports/source \
  --database ./vidore-visual.sqlite3 \
  --output-dir ./vidore-visual-run \
  --image-index visual
```

Evaluate each database against
`./vidore-government-reports/benchmark.json`, then compare the retrieval
metrics. Visual mode retains embeddings derived from source pixels, so apply
your organization's policy for sensitive visual relationships.

### Stress document parsing and resume behavior

Prepare the pinned 1,000-file
[GovDocs1](https://digitalcorpora.org/corpora/file-corpora/files/) shard:

```bash
mere-archive-tools benchmark prepare \
  --dataset govdocs1-shard-000 \
  --output-dir ./govdocs1-000
```

The download is about 487 MB before extraction. The adapter verifies the
official SHA-1 value, rejects unsafe ZIP paths and symbolic links, and extracts
only source types that Archive Tools supports. GovDocs1 doesn't provide
retrieval judgments, so its report covers source integrity, index accounting,
retention, database size, and parser errors rather than retrieval quality.

Treat downloaded public files as untrusted input. Use a dedicated test
location, review the GovDocs1 collection terms before redistribution, and don't
mix the corpus with production shared-drive data.

## Adapt the tool for your organization

The plugin provides the local indexing and search engine. An organization can
add a user interface, mount policy, scheduled execution, encryption, database
backup, result authorization, or a cited question-answering layer.

Apply source-system access rules before you expose search results. The plugin
doesn't reproduce shared-drive access-control lists or decide who can view a
returned path.

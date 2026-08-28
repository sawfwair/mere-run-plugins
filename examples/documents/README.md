# Local AnyDoc conversion example

All data in `report.csv` is synthetic. From the repository root, with the
normal `mere-workflow-tools` package installed on Python 3.10+:

```bash
mere-doc-tools doctor --extractor anydoc --no-redact
mere-doc-tools plan \
  --extractor anydoc \
  --input ./examples/documents/report.csv \
  --output-dir ./runs/document-example \
  --run-id document-example \
  --no-redact
mere-doc-tools run ./runs/document-example/run.json
mere-doc-tools resume ./runs/document-example/run.json
mere-doc-tools cleanup ./runs/document-example/run.json
```

Planning works without AnyDoc or `mere.run`. Execution writes `report.md` and
records its SHA-256 in `run.json`. Cleanup only updates the manifest; it does
not remove local files. No hosted service, API key, model, or paid resource is
used. Change the input to an office document or text PDF to use the same path.

Omit `--no-redact` to add native `mere.run text anonymize` steps, which write
`report.redacted.md` and `report.pii.json` while retaining the original Markdown.

## Graph conversion

The included invocation exercises the installed provider and verifies its
catalog, preflight, event stream, and confined outputs:

```bash
mere-graph-conformance --provider mere-doc-tools \
  --invocation ./examples/documents/convert.invocation.json \
  --run-dir ./runs/document-conformance --execute --json
```

Run the same conversion through the native `mere.run` graph engine:

```bash
mere-doc-tools graph templates export document-to-markdown --output ./document.graph.json
printf '{"document":"./examples/documents/report.csv"}\n' > document.inputs.json
MERERUN_GRAPH_PROVIDERS=mere-doc-tools mere.run graph preflight ./document.graph.json \
  --inputs-json ./document.inputs.json --json
MERERUN_GRAPH_PROVIDERS=mere-doc-tools mere.run graph run ./document.graph.json \
  --inputs-json ./document.inputs.json --run-dir ./runs/document-graph --json
```

Catalog installation registers the provider automatically; the environment
setting also supports direct pipx installs. The template returns Markdown and
a run-manifest asset, inline unredacted text for downstream nodes, and JSON stats.
Neither example loads a model or uploads the document.

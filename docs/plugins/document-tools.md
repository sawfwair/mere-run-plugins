# Document Tools plugin

`mere-doc-tools` converts office documents and text PDFs to Markdown with
[AnyDoc](https://github.com/firecrawl/anydoc), or performs image OCR with native
`mere.run` models. Both paths support optional local PII redaction. The command
is installed by the `mere-workflow-tools` package.

## Install

```bash
mere.run plugin install mere-doc-tools --yes
mere-doc-tools doctor --extractor anydoc --no-redact
```

### Python compatibility

On Python 3.10+, the normal installation includes AnyDoc automatically. No extra
or API key is needed. Catalog installation also registers the document graph
provider with `mere.run`. Python 3.9 installations retain native OCR and the
other workflow tools, but document conversion requires a newer interpreter.

To select a specific interpreter when installing directly with pipx:

```bash
pipx install --python python3.12 "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-workflow-tools"
mere-doc-tools doctor --extractor anydoc --no-redact
```

Choose an available Python 3.10+ interpreter for `--python`. Upgrade an existing
installation with `pipx upgrade mere-workflow-tools`. To migrate a Python 3.9
environment, use `pipx reinstall --python python3.12 mere-workflow-tools`.
The former `[anydoc]` extra remains a compatibility alias. For an older plugin
version already running on Python 3.10+, the dependency can also be added with:

```bash
pipx inject mere-workflow-tools "firecrawl-anydoc>=0.2.4,<0.3"
```

The distribution is **firecrawl-anydoc**, imported as `anydoc`; the unrelated
package named `anydoc` on PyPI is not supported. `doctor --extractor anydoc`
checks both conversion and the default redaction dependencies. Adding
`--no-redact` checks conversion without requiring a `mere.run` executable.

## Convert a document to Markdown

```bash
mere-doc-tools process \
  --extractor anydoc \
  --input ./report.docx \
  --output-dir ./doc-out \
  --no-redact
```

This writes `report.md` and a durable `run.json`, including the executed AnyDoc
version and SHA-256 hashes of output artifacts. No model or `mere.run` executable
is needed when redaction is disabled. AnyDoc runs locally in Python through its
Rust bindings; the plugin never invokes `npx`, downloads a runtime on demand, or
enables hosted OCR.

AnyDoc supports Word (`doc`, `docx`, `docm`), PowerPoint (`ppt`, `pps`, `pot`,
`pptx`, `pptm`, `ppsx`, `ppsm`), Excel (`xls`, `xlsx`, `xlsm`, `xlsb`),
OpenDocument (`odt`, `ods`, `odp`), RTF, EPUB, CSV, and text-based PDF. It detects
formats from content, with the file extension as fallback, including for CSV.
This workflow converts one local file per run.

Omit `--no-redact` to also write `report.redacted.md` and `report.pii.json` using
native `mere.run text anonymize`. The original unredacted Markdown remains in
the output directory. Review redaction results before sharing; conversion does
not preserve page layout or export embedded binary assets.

## OCR a document image

```bash
mere-doc-tools process \
  --input ./scan.png \
  --output-dir ./doc-out \
  --ocr-backend lighton \
  --redact
```

`--extractor ocr` is the default, preserving existing image workflows.
Redaction is enabled by default for both extractors. Use `--no-redact` to skip
it, or `--replacement` to change the replacement format. Supported native OCR
backends are `lighton`, `glm`, and `infinity`; `--ocr-backend` only applies to
the `ocr` extractor.

## Plan and run separately

```bash
mere-doc-tools plan \
  --extractor anydoc \
  --input ./report.docx \
  --output-dir ./doc-out \
  --run-id document-001 \
  --no-redact
mere-doc-tools run ./doc-out/run.json
mere-doc-tools resume ./doc-out/run.json
mere-doc-tools cleanup ./doc-out/run.json
```

`plan` and `process --dry-run` write the plan without loading AnyDoc or running
models. `run --dry-run` prints the existing plan without execution. `run`
executes it, including when retrying a failed run after installing a missing
dependency. `resume` inspects recorded state; it does not rerun conversion.
Cleanup records a local no-op and retains source and derived files.

An executable synthetic example is in
[`examples/documents`](https://github.com/sawfwair/mere-run-plugins/tree/main/examples/documents).

## Native workflow graphs

The plugin advertises `graph-node-provider-v1` and the `document.convert` node.
The node accepts one local `input` asset and emits:

| Output | Type | Content |
| --- | --- | --- |
| `markdown` | asset | UTF-8 Markdown file |
| `manifest` | asset | Durable `plugin-run.v1` receipt, compatible with `run`, `resume`, and `cleanup` |
| `text` | string | The same unredacted Markdown, usable by downstream text nodes |
| `stats` | JSON | Source/output SHA-256, output byte count, and AnyDoc version |

```bash
mere-doc-tools graph catalog --json
mere-doc-tools graph templates export document-to-markdown --output ./document.graph.json
printf '{"document":"./report.docx"}\n' > document.inputs.json
mere.run graph preflight ./document.graph.json --inputs-json ./document.inputs.json --json
mere.run graph run ./document.graph.json --inputs-json ./document.inputs.json --run-dir ./document-graph-run --json
```

For direct pipx installations that have not been registered by the catalog
installer, set `MERERUN_GRAPH_PROVIDERS=mere-doc-tools` for the native graph
commands. Install the plugin on each executor that runs this node. Graph
execution uses no model, credentials, or network access; scanned PDFs fail
locally. Graph outputs are **not redacted**. Use the CLI redaction workflow
before sharing sensitive text.

Preflight checks the backend, input, and confined output paths without converting
or creating a run directory. Execution writes a running manifest before
conversion, persists failures, and emits NDJSON progress, artifacts, statistics,
and one final result only after success. It refuses source/output aliases and
detects source changes during conversion. Cross-run caching is disabled because
the AnyDoc version can change independently of the plugin version.

## Conversion failures

Missing or incompatible AnyDoc installations return exit code `3` with install
guidance. Conversion failures return `1` and persist a failed run manifest.
Encrypted, malformed, unsupported, or resource-limited documents do not silently
succeed. Scanned or image-only PDF pages fail locally with an OCR-required
diagnostic. Render those pages to images and use `--extractor ocr`; there is no
automatic fallback or document upload.

## Privacy boundary

No hosted API is used. AnyDoc is always called with `ocr="reject"`, even when
`FIRECRAWL_API_KEY` or `FIRECRAWL_API_URL` is set. Source and derived text stay
local, but callers remain responsible for access control and review of
redaction quality. See
[Private workflows](/guide/private-workflows).

## Third-party notices

The package includes `mere_workflow_tools/THIRD_PARTY_NOTICES.txt` in its source
distribution, wheel, and installed files. It preserves the full MIT notices for
AnyDoc 0.2.4 and its pdf-inspector 1.14.2 component.

If you bundle or redistribute dependencies, preserve their applicable license
and copyright notices. This file supplements those notices; it isn't a complete
inventory of transitive dependency licenses. Review the resolved dependency
versions before redistribution.

# mere-workflow-tools

Local workflow companion tools for `mere.run`.

This package installs six small commands. They do not ship model runtimes and do
not call hosted APIs; each command writes a run manifest, shells out to the
installed `mere.run` CLI, records artifacts, and marks cleanup as local-only.

## Commands

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-workflow-tools"

mere-doc-tools process --input ./scan.png --output-dir ./doc-out
mere-media-scrub scrub --input ./frames --output-dir ./scrub-out
mere-dataset-tools caption --input ./dataset --output-dir ./caption-out --trigger-token STYLE
mere-transcript-tools transcribe --input ./meeting.wav --output-dir ./transcript-out
mere-image-compose generate --prompt "a product render" --output-dir ./image-out
mere-batch-runner run-jobs --jobs ./jobs.jsonl --output-dir ./batch-out
```

Set `MERE_WORKFLOW_TOOLS_MERE_RUN` or pass `--mere-run-command` to target a
source-checkout binary.

## Tool Map

- `mere-doc-tools`: `mere.run vision ocr` plus optional `mere.run text anonymize`
- `mere-media-scrub`: OCR/redaction over image folders or single frames
- `mere-dataset-tools`: `mere.run vision caption`, optional OCR sidecars, and a contact sheet
- `mere-transcript-tools`: `mere.run speech transcribe` plus optional PII redaction
- `mere-image-compose`: `mere.run image generate` with ref image and LoRA flags recorded
- `mere-batch-runner`: JSONL batch runner for explicit `mere.run` argv lists

Every command supports:

```bash
<tool> manifest --json
<tool> doctor
<tool> plan ...
<tool> run ./run.json
<tool> resume ./run.json
<tool> cleanup ./run.json
```

`mere-dataset-tools` is also a portable graph-node provider. The fixed protocol
keeps execution out of the core process:

```bash
mere-dataset-tools graph catalog --json
mere-dataset-tools graph preflight --request invocation.json --run-dir ./node --json
mere-dataset-tools graph execute --request invocation.json --run-dir ./node --json-stream
```

Its first node, `dataset.prepare`, verifies image-caption pairs and emits a
training-ready directory, content-addressed manifest, optional contact sheet,
and structured statistics.

The package also includes reusable provider helpers, a conformance command,
native graph templates, and a conservative ComfyUI API importer:

```bash
mere-graph-conformance --provider mere-dataset-tools --json
mere-graph-conformance --provider ./provider --invocation ./fixture.json --run-dir ./fixture-run --execute --json
mere-graph-provider-init ./provider --provider-id mere-example-tools --node-kind example.write
mere-graph-compile ./program.json --output ./workflow.json --report-output ./compile.json --json
mere-dataset-tools graph templates list --json
mere-dataset-tools graph comfy inspect ./workflow.json --json
```

The template catalog includes Creative Prompt Lab and Describe and Remix,
which demonstrate reusable value, join, template, enhancement, and
image-description nodes from the public `mere.run` catalog.

ComfyUI compatibility stops at import. Imported requests become ordinary
`mere.run/workflow-graph` documents and use the same local, SSH, or Relay
execution contract as graphs authored elsewhere.

`mere-graph-compile` expands confined reusable module imports, compile-time
branches, and deterministic static maps. Its output is a flat immutable
`mere.run/workflow-graph`; executors never need to understand the richer source
format. Set `execution.max_parallel_nodes` in the program to let independent
expanded nodes overlap. Variable overrides are accepted from a separate JSON
file so source programs remain reusable and compilation stays reproducible.

The separate `mere-run-graph-studio` application consumes these public graph
provider, template, compiler, and Comfy bridge commands. Keeping the visual app
outside this package lets workflow tools remain headless and independently
versioned.

The initializer writes only into a new or empty destination. Its generated
provider is deterministic, emits a final `node_result`, confines declared
outputs, and includes a catalog test. Full conformance additionally validates
preflight requirements, contiguous event sequences, declared output names,
and on-disk artifact paths.

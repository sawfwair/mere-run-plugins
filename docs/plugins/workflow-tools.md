# Workflow Tools

`mere-workflow-tools` is a shared package that installs six companion commands
and one graph-provider conformance tool:

- `mere-doc-tools`
- `mere-media-scrub`
- `mere-dataset-tools`
- `mere-transcript-tools`
- `mere-image-compose`
- `mere-batch-runner`
- `mere-graph-conformance`

Each command follows the same plugin fashion:

```bash
<tool> manifest --json
<tool> doctor
<tool> plan ...
<tool> run ./run.json
<tool> resume ./run.json
<tool> cleanup ./run.json
```

The one-shot command for each tool writes a manifest and immediately executes it.

## Runtime Boundary

The package does not include OCR, ASR, captioning, anonymization, segmentation,
or image-generation runtimes. It shells out to `mere.run` and records the exact
planned steps. Override the executable with `MERE_WORKFLOW_TOOLS_MERE_RUN` or
`--mere-run-command`.

## Commands

Document OCR plus redaction:

```bash
mere-doc-tools process \
  --input ./scan.png \
  --output-dir ./doc-out
```

Media OCR scrub over a frame directory:

```bash
mere-media-scrub scrub \
  --input ./frames \
  --output-dir ./scrub-out
```

Dataset captioning for LoRA prep:

```bash
mere-dataset-tools caption \
  --input ./dataset \
  --output-dir ./caption-out \
  --trigger-token STYLE \
  --focus "border" \
  --focus "lighting"
```

Audio transcription plus redaction:

```bash
mere-transcript-tools transcribe \
  --input ./meeting.wav \
  --output-dir ./transcript-out
```

Image generation composition:

```bash
mere-image-compose generate \
  --prompt "a sharp product render" \
  --output-dir ./image-out \
  --model image-klein-9b
```

Batch execution:

```bash
mere-batch-runner run-jobs \
  --jobs ./jobs.jsonl \
  --output-dir ./batch-out
```

Each JSONL batch row must contain an `argv` string array. Optional `outputs`
entries tell the runner which artifacts to hash after execution:

```json
{"argv":["text","anonymize","--output","./redacted.txt"],"outputs":{"redacted":"./redacted.txt"}}
```

## Portable Graphs

`mere-dataset-tools` exposes `dataset.prepare` through the fixed graph-provider
protocol. The package SDK centralizes confined invocation decoding, diagnostic
records, ordered event streams, and catalog conformance:

```bash
mere-graph-conformance --provider mere-dataset-tools --json
mere-dataset-tools graph templates list --json
mere-dataset-tools graph templates export lora-train-sample \
  --output ./workflow.json --json
```

The native template catalog includes dataset-to-LoRA-to-sample and
image-to-video workflows. The canonical graph and run schemas are mirrored in
`contracts/` and validated with every repository gate.

## ComfyUI Bridge

The bridge is an importer, not a second runtime. It inspects ComfyUI UI or API
JSON and imports a supported API prompt subset into a native graph:

```bash
mere-dataset-tools graph comfy inspect ./comfy-workflow.json --json
mere-dataset-tools graph comfy import ./comfy-api.json \
  --model image-krea2-turbo \
  --output ./workflow.json \
  --inputs-output ./inputs.json \
  --json
```

Checkpoint, CLIP text, KSampler, latent-image, optional image input, optional
LoRA, VAE decode, and save nodes are recognized. Custom nodes and UI-only
exports remain inspectable but block import with explicit diagnostics. ComfyUI
sampler and scheduler choices are reported as omitted warnings when the native
node contract has no equivalent.

## Why These Are Plugins

These are local production workflows, not new model capabilities. Keeping them
as companion plugins lets `mere.run` stay focused on inference while users get
repeatable, inspectable pipelines for documents, media, datasets, transcripts,
image generation, and batch automation.

# Workflow Tools

`mere-workflow-tools` is a shared package that installs six companion commands:

- `mere-doc-tools`
- `mere-media-scrub`
- `mere-dataset-tools`
- `mere-transcript-tools`
- `mere-image-compose`
- `mere-batch-runner`

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

## Why These Are Plugins

These are local production workflows, not new model capabilities. Keeping them
as companion plugins lets `mere.run` stay focused on inference while users get
repeatable, inspectable pipelines for documents, media, datasets, transcripts,
image generation, and batch automation.

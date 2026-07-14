# Document Tools

`mere-doc-tools` performs local document OCR and optional PII redaction with
native `mere.run` models. It is one of six executables installed by the
`mere-workflow-tools` package.

## Install

```bash
mere.run plugin install mere-doc-tools
mere-doc-tools doctor
```

## Process a document

```bash
mere-doc-tools process \
  --input ./scan.png \
  --output-dir ./doc-out \
  --ocr-backend lighton \
  --redact
```

Redaction is enabled by default. Use `--no-redact` when the output must preserve
the complete OCR text, or `--replacement` to change the replacement format.
Supported OCR backends are `lighton`, `glm`, and `infinity`.

## Plan and run separately

```bash
mere-doc-tools plan \
  --input ./scan.png \
  --output-dir ./doc-out \
  --run-id document-001
mere-doc-tools run ./doc-out/run.json
```

## Core commands

The plugin composes `mere.run vision ocr` with optional
`mere.run text anonymize`. It records the resolved commands, extracted text,
redacted text, artifact paths, and hashes in the run manifest.

## Privacy boundary

No hosted API is used. Source and derived text stay local, but callers remain
responsible for access control and review of redaction quality. See
[Private workflows](/guide/private-workflows).

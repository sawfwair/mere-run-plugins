# Media Scrub

`mere-media-scrub` scans a single image or folder of frames, extracts visible
text locally, and optionally redacts sensitive text.

## Install and run

```bash
mere.run plugin install mere-media-scrub
mere-media-scrub doctor
mere-media-scrub scrub \
  --input ./frames \
  --output-dir ./scrub-out \
  --ocr-backend lighton \
  --redact
```

Redaction is enabled by default. OCR backends are `lighton`, `glm`, and
`infinity`.

## Planned workflow

```bash
mere-media-scrub plan \
  --input ./frames \
  --output-dir ./scrub-out \
  --run-id media-scrub-001
mere-media-scrub run ./scrub-out/run.json
```

The manifest tracks the input set, per-step execution, outputs, and hashes so an
interrupted or audited batch does not depend on terminal history.

## Boundary

The plugin calls local `mere.run` OCR and anonymization commands. It does not
upload frames or extracted text. Review the results before distributing source
media or redacted reports.

# Media Scrub plugin

`mere-media-scrub` scans a single image or folder of frames, extracts visible
text locally, and optionally redacts sensitive text. It can also export images
with visually reviewed areas covered by opaque black rectangles.

## Install and run

```bash
mere.run plugin install mere-media-scrub --yes
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

## Review and export redacted images

```bash
mere-media-scrub redaction-review --input ./frames --output-dir ./review
open ./review/review.html
```

Open `review.html` in a local browser. Drag rectangles over sensitive areas or
enter pixel coordinates. Use **Actual size** to inspect small details. Approve
each frame after checking it, including frames that need zero rectangles.
Select **Download approved review** once all frames are approved. The review
page uses local previews and works offline.

```bash
mere-media-scrub redact-export \
  --input ./frames \
  --review ~/Downloads/approved-redactions.json \
  --output-dir ./redacted
```

Both commands accept a single image or a folder of still frames in filename
order. Use fresh output directories outside the input folder. The export
checks each source filename, oriented dimensions, and SHA-256 against the
review. Any changed, missing, or unapproved source stops the batch.

The output contains numbered RGB PNGs and an `export.json` receipt that maps
source names to output files and records rectangles and output hashes. The PNGs
apply EXIF orientation, flatten transparency onto white, and omit source
metadata. Inspect the exported PNGs before sharing them. Keep the review folder
private because it contains full-size unredacted previews.

The existing `scrub` command uses local OCR and anonymization models to redact
extracted text. Visual review and export use the rectangles you approve and
require no models or network access.

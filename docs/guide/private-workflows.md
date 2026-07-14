# Keep workflows private

The privacy-oriented workflow tools keep source documents, frames, and audio on
the machine that owns them. They shell out to native `mere.run` OCR, speech,
captioning, and anonymization commands; they do not call hosted APIs.

## Documents

```bash
mere-doc-tools process \
  --input ./call-sheet.png \
  --output-dir ./doc-out \
  --redact
```

Use [Document Tools](/plugins/document-tools) for a single document or small
document set.

## Media frames

```bash
mere-media-scrub scrub \
  --input ./frames \
  --output-dir ./scrub-out \
  --redact
```

Use [Media Scrub](/plugins/media-scrub) for an image folder or extracted frames.

## Audio

```bash
mere-transcript-tools transcribe \
  --input ./meeting.wav \
  --output-dir ./transcript-out \
  --redact
```

Use [Transcript Tools](/plugins/transcript-tools) for local transcription with
optional anonymization.

## Privacy is more than model location

Local execution does not remove the need for operational care:

- keep source and output directories access-controlled;
- inspect redaction results before distribution;
- do not commit real customer material, credentials, or run bundles;
- remember that manifests can contain paths and production identifiers;
- securely remove intermediate OCR or transcript text when policy requires it.

See [Security](/operations/security) for repository and runtime rules.

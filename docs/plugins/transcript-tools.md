# Transcript Tools

`mere-transcript-tools` transcribes local audio with `mere.run` and can pass the
result through local PII redaction.

## Install and transcribe

```bash
mere.run plugin install mere-transcript-tools
mere-transcript-tools doctor
mere-transcript-tools transcribe \
  --input ./meeting.wav \
  --output-dir ./transcript-out \
  --backend auto \
  --redact
```

Backends are `auto`, `parakeet`, and `qwen`. Use `--language` when the selected
backend benefits from an explicit language. Redaction is enabled by default;
use `--no-redact` to preserve the full transcript.

## Plan and resume

```bash
mere-transcript-tools plan \
  --input ./meeting.wav \
  --output-dir ./transcript-out \
  --run-id transcript-001
mere-transcript-tools run ./transcript-out/run.json
mere-transcript-tools resume ./transcript-out/run.json
```

The run records the transcript and redacted artifacts separately, including
hashes. Source audio and text remain local.

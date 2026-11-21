# Transcript Tools

Transcribe an audio file or a folder of recordings locally. Add speaker labels,
timed captions, and PII redaction to prepare transcripts for review.

## Install and transcribe

```bash
mere.run plugin install mere-transcript-tools --yes
mere.run plugin doctor mere-transcript-tools
mere.run plugin run mere-transcript-tools -- transcribe \
  --input ./meeting.wav --output-dir ./transcript-out
```

Select `--backend auto`, `parakeet`, `qwen`, `whistle`, `nemotron`, or
`sov`. Use `--model` to select an installed ASR model and `--language` when
your backend uses a language hint. Read the [speech runtime guide](https://docs.mere.run/runtime/speech).

## Export speaker-labeled subtitles

```bash
mere.run plugin run mere-transcript-tools -- transcribe \
  --input ./recordings --output-dir ./subtitles \
  --diarize --subtitles both
```

A folder run includes supported recordings in subfolders. Each recording gets a
separate output directory based on its relative path, including its extension.
Use `--subtitles srt`, `vtt`, or `both`. The ASR model must return real
timestamps. Choose Parakeet or Whistle for alignment output. `--diarize` writes speaker intervals and labels each
cue with the speaker who overlaps it most.

Redaction is enabled by default for transcripts and subtitle exports. Use
`--no-redact` to export the original wording. The output directory also holds
raw ASR text for local review. Share the reviewed `.redacted` outputs when they
meet your needs.

## Plan and inspect a run

```bash
mere.run plugin run mere-transcript-tools -- plan \
  --input ./meeting.wav --output-dir ./transcript-out \
  --run-id transcript-001 --subtitles vtt
mere.run plugin run mere-transcript-tools -- run ./transcript-out/run.json
mere.run plugin run mere-transcript-tools -- resume ./transcript-out/run.json
```

The run manifest records the inputs, native commands, and hashes of its outputs.

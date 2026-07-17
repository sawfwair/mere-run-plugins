# Play a realtime show

`mere-perform` wraps `mere.run music realtime` in a repeatable live-performance
run with MIDI control, a local stage, event logs, and optional audio capture.

## Create a show file

```bash
mere.run plugin install mere-perform
mere-perform show-template --output ./show.json
```

Edit the prompts, scenes, model, audio, and MIDI mappings, then check readiness:

```bash
mere-perform doctor
```

## Rehearse the plan

```bash
mere-perform plan \
  --show ./show.json \
  --output-dir ./runs/rehearsal \
  --run-id rehearsal \
  --no-play
```

## Start the live run

```bash
mere-perform perform \
  --show ./show.json \
  --output-dir ./runs/live-take \
  --run-id live-take \
  --midi-input "OP-1 Bluetooth" \
  --stage-port 8880 \
  --open-stage
```

The stage is served only on the local machine. During a live MIDI run it mirrors
observed notes and can send typed prompt updates to the interactive core process.

## Review the take

The run directory keeps the show, stage export, events, manifest, and captured
audio when enabled. To inspect an exported stage after the realtime process has
finished:

```bash
mere-perform stage ./runs/live-take/run.json --serve --open --port 8765
```

See [Perform](/plugins/perform) for show schema and control details.

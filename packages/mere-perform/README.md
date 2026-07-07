# mere-perform

Realtime performance companion plugin for local `mere.run` workflows.

`mere-perform` plans a Magenta Heart show, records a durable `run.json`, exports
a local stage UI, and can launch `mere.run music realtime` with MIDI mappings,
stable instrument prompts, and WAV capture. It does not embed a second inference
runtime and does not create paid or remote resources.

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-perform"

mere-perform manifest --json
mere-perform doctor
mere-perform show-template --output ./show.json
mere-perform plan \
  --show ./show.json \
  --output-dir ./runs/heart-demo \
  --run-id heart-demo \
  --no-play
mere-perform perform \
  --show ./show.json \
  --output-dir ./runs/heart-live \
  --run-id heart-live \
  --midi-input "OP-1 Bluetooth" \
  --stage-port 8880 \
  --open-stage
mere-perform run ./runs/heart-demo/run.json
```

The stage export writes:

- `stage/index.html`
- `stage/state.json`
- `stage/live.json`
- `show.json`
- `events.jsonl` after execution starts
- the requested WAV capture path when `mere.run` produces it

Use `--stage-port` with `--open-stage` on `perform`, or on `plan` before
`run`, to keep the stage available while `mere.run music realtime` is active.
Use `stage --serve --open` only to inspect an exported run after the realtime
process has finished.

Default mode is instrument mode: the initial prompt stays put and the MIDI
controller drives the model. When a MIDI input is configured, instrument mode
starts from the first `mode: "solo"` prompt so Magenta RT2 gets a note-following
`SOLO ...` seed instead of a background texture. Add `--sequence-scenes` only
when you explicitly want timed prompt and parameter changes.

For live MIDI debugging, add `--midi-log-events` or `--midi-log-raw` to the
`perform` command. If the OP-1 is transmitting on a specific channel, pass that
channel explicitly, for example `--midi-channel 4`. When `--stage-port` and a
MIDI input are both set, `mere-perform` enables event logging automatically so
the piano strip can mirror observed `mere.run` note events.

Use `devices` to inspect MIDI sources through the installed `mere.run` binary:

```bash
mere-perform devices
```

Set `MERE_PERFORM_MERE_RUN` or pass `--mere-run-command` to target a source
checkout or non-standard binary.

## Prompt Palette

`show-template` now treats prompts as a performance palette. Each prompt can
carry:

- `role`: stage meaning such as `texture`, `groove`, `lead`, or `space`
- `mode`: `jam` for accompaniment, `solo` for note-following lead prompts
- `cfgMusicCoCa`: prompt strength for the realtime MusicCoCa steering path
- `resetAfterPrompt`: whether to reset after the prompt settles

Patches can reference anchors by `promptId`:

```json
{
  "id": "cut",
  "title": "Cut",
  "durationSeconds": 7,
  "promptId": "lead",
  "temperature": 0.86
}
```

Keep anchors compact and musical: genre, instrumentation, texture/production,
and energy. Solo prompts stay clean in JSON; the plugin adds the Magenta-style
`SOLO ` runtime prefix when sending commands to `mere.run`.

## MIDI Controller Stage

The plugin passes physical MIDI through to native `mere.run` with
`--midi-input`, `--midi-channel`, `--midi-note-offset`, and repeatable
`--midi-cc`. The stage UI adds the performance layer around that native path:

- MIDI source, channel, note offset, and gate readouts
- on-screen piano strip with active-note highlighting from observed
  `mere.run` note logs
- computer-keyboard preview with local active-note highlighting
- optional sequence pads when `--sequence-scenes` is enabled
- local `stage/live.json` feed for physical controllers such as OP-1 Bluetooth

Example:

```json
{
  "midi": {
    "input": "OP-1",
    "channel": "all",
    "noteOffset": 0,
    "logEvents": false,
    "logRaw": false,
    "keyboard": {"enabled": true, "baseNote": 60, "octaveRange": 2},
    "gate": {"enabled": true, "releaseMs": 900, "idleStopSeconds": 30},
    "cc": ["1=temp:0.2:1.4", "2=drums:0:2", "3=mc:1:5"],
    "pads": [{"id": "pad-1", "label": "1", "sceneId": "ignite"}],
    "activity": {"demoNotes": [60, 64, 67]}
  }
}
```

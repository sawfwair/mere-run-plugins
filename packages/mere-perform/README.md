# mere-perform

Realtime performance companion plugin for local `mere.run` workflows.

`mere-perform` plans a Magenta Heart show, records a durable `run.json`, exports
a local stage UI, and can launch `mere.run music realtime` with MIDI mappings,
scene prompts, and WAV capture. It does not embed a second inference runtime and
does not create paid or remote resources.

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
mere-perform stage ./runs/heart-demo/run.json
mere-perform run ./runs/heart-demo/run.json
```

The stage export writes:

- `stage/index.html`
- `stage/state.json`
- `show.json`
- `events.jsonl` after execution starts
- the requested WAV capture path when `mere.run` produces it

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

Scenes can reference anchors by `promptId`:

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
- on-screen piano strip with active-note highlighting
- computer-keyboard preview using a Magenta Jam-style layout
- scene pads that preview scene jumps on the stage
- demo active notes for rehearsal screenshots and overlays

Example:

```json
{
  "midi": {
    "input": "OP-1",
    "channel": "all",
    "noteOffset": 0,
    "keyboard": {"enabled": true, "baseNote": 60, "octaveRange": 2},
    "gate": {"enabled": true, "releaseMs": 900, "idleStopSeconds": 30},
    "cc": ["1=temp:0.2:1.4", "2=drums:0:2", "3=mc:1:5"],
    "pads": [{"id": "pad-1", "label": "1", "sceneId": "ignite"}],
    "activity": {"demoNotes": [60, 64, 67]}
  }
}
```

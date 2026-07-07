# Perform

`mere-perform` turns local `mere.run music realtime` sessions into repeatable
performance runs. It plans a Magenta Heart show, writes `run.json`, exports a
stage UI, records event JSONL, and can capture the realtime stream to WAV.

It is a companion executable. It does not embed Magenta's Python or C++ runtime
and does not turn `mere.run` into a hosted service. The plugin shells out to the
user's installed `mere.run` binary, so model behavior stays in the core CLI.

```bash
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

The default performance mode is instrument mode: `mere.run music realtime`
holds the initial prompt, OP-1 notes drive the model through native CoreMIDI,
and CC mappings shape parameters without timed prompt jumps. Pass
`--sequence-scenes` only when you explicitly want an arranged prompt sequence.
When a MIDI input is configured, instrument mode starts from the first
`mode: "solo"` prompt so the realtime command gets a note-following
`SOLO ...` seed.

The stage view is a local HTML export. It visualizes the prompt nodes,
patch list, MIDI controller state, on-screen piano strip, and magenta heart
cursor for rehearsal, projection, or stream overlays. Pass
`--stage-port` and `--open-stage` to `perform`, or to `plan` before `run`, so
the stage is served while `mere.run music realtime` is actually alive. During a
live staged MIDI run, `mere-perform` mirrors observed `mere.run` note logs into
`stage/live.json` so the piano strip reflects physical key presses. Use
`stage --serve` only to inspect an exported run after the realtime process has
finished. Add `--open` to launch the default browser after the local server
starts:

```bash
mere-perform stage ./runs/heart-demo/run.json --serve --open --port 8765
```

## Show File

`show-template` prints a starter `mere.run/perform-show.v1` JSON file:

- `title`
- `durationSeconds`
- `model`
- `audio.play`
- `audio.capture`
- `midi.input`
- `midi.channel`
- `midi.noteOffset`
- `midi.cc`
- `midi.keyboard`
- `midi.gate`
- `midi.pads`
- `midi.activity`
- `heart`
- `promptStrategy`
- `prompts`
- `scenes`

Scene prompts are not sent automatically in the default instrument mode. With
`--sequence-scenes`, scene prompts are sent to
`mere.run music realtime --interactive` while the run is active. MIDI CC
mappings are passed through to the native CoreMIDI surface. Incoming note
transposition is passed through to native `--midi-note-offset`.

## Prompt Strategy

Author prompts as compact musical anchors, not paragraph-length song requests.
The useful shape is:

```text
genre + instrumentation + texture/production + energy
```

Good anchors are short, concrete, and blendable:

```text
drumless glassy arpeggios with soft tape hiss
afrobeat band with horns and complex drums
distorted cello lead with long tremolo swells
cavernous endless reverb electric guitar swells
```

`promptStrategy` records how the show treats those anchors:

```json
{
  "shape": "short musical anchors: genre, instrumentation, texture/production, energy",
  "blendModel": "inverse-distance prompt palette",
  "blendFalloff": 2.0,
  "promptDebounceMs": 400,
  "resetAfterPrompt": true
}
```

Each prompt can declare a stage `role`, runtime `mode`, prompt strength, and
reset behavior:

```json
{
  "id": "lead",
  "role": "lead",
  "mode": "solo",
  "text": "distorted cello lead with long tremolo swells",
  "cfgMusicCoCa": 3.5,
  "unmaskWidth": 127,
  "resetAfterPrompt": true
}
```

Use `mode: "jam"` for full accompaniment prompts. Use `mode: "solo"` for
note-following lead or instrument prompts. Solo mode keeps the authored prompt
clean in the show file and sends the Magenta-style `SOLO ` runtime prefix to
`mere.run`.

Patches should usually reference palette nodes by `promptId` instead of
duplicating prompt text. They become timed prompt changes only when the run uses
`--sequence-scenes`:

```json
{
  "id": "cut",
  "title": "Cut",
  "durationSeconds": 7,
  "promptId": "lead",
  "temperature": 0.86
}
```

`cfgMusicCoCa` is prompt strength. Higher values follow the prompt more
strictly; lower values leave more room for musical continuity. Keep temperature
and top-k as exploration controls, not substitutes for better prompt anchors.

Magenta RT2 is strongest for instrumental realtime steering. If a show needs
lyrics or explicit sung words, route that scene through another `mere.run`
music surface rather than trying to force lyrics through the realtime prompt.

## MIDI Controller Layer

`mere-perform` does not reimplement CoreMIDI. Physical MIDI notes and CCs stay
inside `mere.run music realtime`; the plugin records the intended controller
setup and renders it on the stage.

```json
{
  "midi": {
    "input": "OP-1",
    "channel": "all",
    "noteOffset": 0,
    "logEvents": false,
    "logRaw": false,
    "cc": ["1=temp:0.2:1.4", "2=drums:0:2", "3=mc:1:5"],
    "keyboard": {
      "enabled": true,
      "baseNote": 60,
      "octaveRange": 2,
      "layout": "ableton"
    },
    "gate": {
      "enabled": true,
      "releaseMs": 900,
      "idleStopSeconds": 30
    },
    "pads": [
      {"id": "pad-1", "label": "1", "sceneId": "ignite", "target": "scene"}
    ],
    "activity": {
      "demoNotes": [60, 64, 67]
    }
  }
}
```

The stage uses this metadata to show a MIDI source strip, observed note status,
optional sequence pads, and a piano reference strip. Computer-keyboard preview
follows the Magenta Jam pattern: home-row keys map to white notes, nearby
top-row keys map to black notes, and locally held preview notes pulse the heart.
Physical OP-1 note ingestion stays inside native `mere.run`; the browser only
mirrors note events that `mere.run` actually logs into the local `stage/live.json`
feed.

Use `mere.run` or `mere-perform` MIDI logs to prove hardware input:

```bash
mere.run music realtime --midi-monitor \
  --midi-input "OP-1 Bluetooth" \
  --midi-channel all \
  --midi-log-raw \
  --midi-log-events \
  --duration 45

mere-perform perform \
  --output-dir ./runs/op1-debug \
  --run-id op1-debug \
  --midi-input "OP-1 Bluetooth" \
  --midi-channel 4 \
  --midi-log-events \
  --midi-log-raw \
  --stage-port 8880 \
  --open-stage
```

## Artifacts

Successful runs record:

- `run.json`
- `show.json`
- `events.jsonl`
- `stage/index.html`
- `stage/state.json`
- `stage/live.json`
- WAV capture when `mere.run` writes it

`cleanup` is a no-op by default because no remote resources are created.

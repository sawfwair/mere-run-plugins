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
mere-perform stage ./runs/heart-demo/run.json
mere-perform run ./runs/heart-demo/run.json
```

The stage view is a static local HTML export. It visualizes the prompt nodes,
scene list, MIDI controller state, on-screen piano strip, scene pads, and
magenta heart cursor for rehearsal, projection, or stream overlays. Use
`stage --serve` when a browser needs an HTTP URL:

```bash
mere-perform stage ./runs/heart-demo/run.json --serve --port 8765
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

Scene prompts are sent to `mere.run music realtime --interactive` while the run
is active. MIDI CC mappings are passed through to the native CoreMIDI surface.
Incoming note transposition is passed through to native `--midi-note-offset`.

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

Scenes should usually reference palette nodes by `promptId` instead of
duplicating prompt text:

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

The stage uses this metadata to show a MIDI source strip, activity LED, scene
pads, and piano strip. Computer-keyboard preview follows the Magenta Jam
pattern: home-row keys map to white notes, nearby top-row keys map to black
notes, and held notes pulse the heart. It is a stage/operator visualization;
live hardware ingestion remains the native `mere.run` process.

## Artifacts

Successful runs record:

- `run.json`
- `show.json`
- `events.jsonl`
- `stage/index.html`
- `stage/state.json`
- WAV capture when `mere.run` writes it

`cleanup` is a no-op by default because no remote resources are created.

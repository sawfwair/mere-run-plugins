# Animatic Tools Plugin

`mere-animatic-tools` contains local production helpers for Animatic workflows
served by a `mere.run` relay node.

It is a companion plugin, not a hosted service. Commands run on the user's node,
write a durable `run.json` before execution, emit machine-readable JSON on
stdout, and do not create paid resources.

## Commands

```bash
mere-animatic-tools doctor
mere-animatic-tools plan \
  --tool shot-kit \
  --request-json ./request.json \
  --output-dir ./out \
  --run-id shot-kit-001
mere-animatic-tools run ./out/run.json
mere-animatic-tools character-knockout \
  --request-json ./request.json \
  --output-dir ./out \
  --run-id knockout-001
mere-animatic-tools cleanup ./out/run.json
```

The production commands are:

- `character-knockout`
- `reference-pack`
- `continuity-check`
- `shot-kit`
- `storyboard-repair`
- `edit-doctor`
- `actor-voice-kit`
- `location-plates`
- `style-lock`
- `delivery-prep`

## Request Shape

Each one-shot command accepts `--request-json` with an object shaped for relay
tool jobs:

```json
{
  "inputs": {
    "prompt": "scene or shot note",
    "assets": [
      { "name": "frame", "url": "https://example.com/frame.png" }
    ]
  },
  "options": {}
}
```

Assets may be URLs or local file paths: the `url` field accepts either, and an
explicit `path` field also works for local files. Animatic sends signed asset
URLs when a project asset is selected. The plugin downloads URL inputs into its
output directory, uses local files in place, and records them in `run.json`.

## Outputs

Every successful run records uploadable artifact items in:

```json
{
  "artifacts": {
    "items": [
      {
        "name": "shot-kit.json",
        "path": "/tmp/out/shot-kit.json",
        "kind": "json",
        "label": "shot-kit",
        "contentType": "application/json"
      }
    ]
  }
}
```

The relay node uploads each artifact and returns URLs to Animatic. Animatic then
stores them as project assets under the requested parent.

## Character Knockout

`character-knockout` uses `mere-image-tools knockout` when that executable is
available. If `mere-image-tools` or native `mere.run vision segment` is not
ready, it falls back to a deterministic local alpha-threshold matte so the tool
still returns a transparent PNG and mask for review.

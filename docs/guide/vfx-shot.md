# Build a VFX shot

Use VFX Tools when the result is a shot-level package rather than one isolated
model call.

## Install and inspect

```bash
mere.run plugin install mere-vfx-tools --yes
mere-vfx-tools doctor
mere-vfx-tools manifest --json
```

## Write a request

Each tool accepts a JSON document with `inputs` and `options`:

```json
{
  "inputs": { "video": "./shot.mov" },
  "options": { "prompts": ["actor", "sword"], "alphaVideo": true }
}
```

## Plan the pass

```bash
mere-vfx-tools plan \
  --tool roto \
  --request-json ./roto-request.json \
  --output-dir ./runs/shot-010-roto \
  --run-id shot-010-roto
```

Inspect `./runs/shot-010-roto/run.json`, and then run:

```bash
mere-vfx-tools run ./runs/shot-010-roto/run.json
```

## Chain verified outputs

A production path can use the resulting masks for matte refinement, tracking,
clean-plate generation, relighting, alpha delivery, or shot QC. Each pass gets
its own manifest and artifact hashes, so the handoff stays explicit.

## Publish for review

To publish the approved artifact as a review Version or update a task, use
[ShotGrid Tools](/guide/shotgrid-publish).

See [VFX Tools](/plugins/vfx-tools) for the supported workflow families and
native handoff guarantees.

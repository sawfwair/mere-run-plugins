# Build a VFX shot

Use VFX Tools when the result is a shot-level package rather than one isolated
model call.

## 1. Install and inspect

```bash
mere.run plugin install mere-vfx-tools
mere-vfx-tools doctor
mere-vfx-tools manifest --json
```

## 2. Write a request

Each tool accepts a JSON document with `inputs` and `options`:

```json
{
  "inputs": { "video": "./shot.mov" },
  "options": { "prompts": ["actor", "sword"], "alphaVideo": true }
}
```

## 3. Plan the pass

```bash
mere-vfx-tools plan \
  --tool roto \
  --request-json ./roto-request.json \
  --output-dir ./runs/shot-010-roto \
  --run-id shot-010-roto
```

Inspect `./runs/shot-010-roto/run.json`, then execute:

```bash
mere-vfx-tools run ./runs/shot-010-roto/run.json
```

## 4. Chain verified outputs

A production path can use the resulting masks for matte refinement, tracking,
clean-plate generation, relighting, alpha delivery, or shot QC. Each pass gets
its own manifest and artifact hashes, so the handoff stays explicit.

## 5. Publish for review

Use [ShotGrid Tools](/guide/shotgrid-publish) when the approved artifact should
become a review Version or update a task.

See [VFX Tools](/plugins/vfx-tools) for the supported workflow families and
native handoff guarantees.

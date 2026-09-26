# Image Compose plugin

`mere-image-compose` turns a local image generation command into a repeatable
composition with recorded prompts, model settings, references, LoRAs, seed,
dimensions, artifacts, and hashes.

## Install and generate

```bash
mere.run plugin install mere-image-compose --yes
mere-image-compose doctor
mere-image-compose generate \
  --prompt "cinematic product render on warm paper" \
  --model image-klein-9b \
  --width 1024 \
  --height 1024 \
  --seed 42 \
  --output-dir ./image-out
```

## Add references or a LoRA

```bash
mere-image-compose generate \
  --prompt "editorial portrait" \
  --ref-image ./reference.png \
  --strength 0.55 \
  --lora ./style.safetensors \
  --lora-scale 1.5 \
  --output-dir ./portrait-out
```

## Planned composition

Use `plan` with the same generation flags to write `run.json`, then run it
with `run`. This is useful when a pipeline or reviewer must approve the complete
composition before inference.

The plugin delegates model behavior to `mere.run image generate`; it owns the
repeatable plan and production record.

## Image finishing graph nodes

The same installed plugin exposes four deterministic image nodes through the
public graph-provider protocol. They appear in Graph Studio when the selected
executor reports the `mere-image-compose` provider catalog.

| Node | Operation |
| --- | --- |
| `image.crop` | Crop to an exact pixel rectangle. |
| `image.mask` | Apply a grayscale mask as transparency. |
| `image.composite` | Place a transparent layer over a base image with position and opacity. |
| `image.inpaint` | Fill a small masked region from neighboring pixels without a model. |

All four nodes produce a PNG artifact. Inpainting is a deterministic local
repair for small defects, with a 4 megapixel source limit and a mask covering
at most 25% of the image. It does not use a generative image model. Images in
the other operations are limited to 16 megapixels.

```bash
mere-image-compose graph catalog --json
mere-graph-conformance --provider mere-image-compose --json
```

To start with a connected repair and overlay workflow, export the bundled template:

```bash
mere-image-compose graph templates export image-repair-composite --output ./finishing.workflow.json
```

Set the `source`, `mask`, and `overlay` input paths in an inputs JSON document.
The mask must match the source dimensions. White mask pixels mark the defect to
fill. The template exposes repaired and composited outputs for comparison.

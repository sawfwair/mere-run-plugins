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

## Generate with blind review

From this checkout, install the plugin with `python -m pip install ./packages/mere-workflow-tools`.
Use a local `mere.run` with Nemotron image generation and Inkling image chat.
The defaults are `image-nemotron-labs-30b-a3b` and `vision-chat-inkling-2-mini`.
For a packed checkpoint, set its path once in your shell.

```bash
export MERE_NEMOTRON_MODEL=/path/to/nemotron-q8
mere-image-compose generate-reviewed --prompt "A red enamel kettle on a blue camping stove"
```

Inkling sees the creative brief and the first render. If it accepts the image, generation ends.
If it requests a repair, Nemotron draws one new image from Inkling's standalone prompt.
Two fresh Inkling sessions compare the images in opposite orders. Each sees the original
brief and labeled images. Both must prefer the redraw with self-reported confidence of
at least 0.75 to replace the original. Ties, split votes, and lower confidence keep the original.

The command prints JSON with the path to `selected.png` and the run directory under `runs/`.
The directory contains the renders, prompts, replies, comparison sheets, and `result.json`.
Set `--output-dir` to choose a new directory, `--seed` for the first render, or
`--model` and `--reviewer` to override model IDs or paths. Use `MERE_RUN_EXECUTABLE`
to select a native binary outside your PATH. An incomplete image block gets up to two more
attempts with successive seeds. Other inference errors and invalid reviews exit with a
failed record. A successfully rendered original remains available.

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

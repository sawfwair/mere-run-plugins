# Image Compose

`mere-image-compose` turns a local image generation command into a repeatable
composition with recorded prompts, model settings, references, LoRAs, seed,
dimensions, artifacts, and hashes.

## Install and generate

```bash
mere.run plugin install mere-image-compose
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

Use `plan` with the same generation flags to write `run.json`, then execute it
with `run`. This is useful when a pipeline or reviewer must approve the complete
composition before inference.

The plugin delegates model behavior to `mere.run image generate`; it owns the
repeatable plan and production record.

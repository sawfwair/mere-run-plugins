# Image Tools Plugin

`mere-image-tools` contains local image-production helpers for `mere.run`
workflows.

The first supported workflow is subject knockout through the native
`mere.run vision segment` SAM 3.1 command.

## Why This Is A Plugin

Subject knockout needs matte post-processing and recipe-specific defaults that
are useful in production image workflows. Keeping that workflow in a companion
plugin lets the core `mere.run` CLI stay focused on model inference while still
giving production users a stable command surface built on top of the native CLI.

## Commands

```bash
mere-image-tools doctor
mere-image-tools plan \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png
mere-image-tools run ./subject.run.json
mere-image-tools knockout \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png \
  --prompt "subject"
mere-image-tools cleanup ./subject.run.json
```

`knockout` is a convenience command that writes a run manifest and executes it
immediately. Use `plan` plus `run` when you want to inspect or store the
operation before execution.

## mere.run Runtime

The plugin calls:

```bash
mere.run vision segment ./frame.png \
  --model vision-segment-sam31 \
  --prompt "subject" \
  --output ./subject.sam31/segmented.png \
  --json-output ./subject.sam31/segmented.json \
  --mask-output-dir ./subject.sam31/masks
```

Override the executable with `MERE_IMAGE_TOOLS_MERE_RUN` or
`--mere-run-command` when you need to target a source checkout or a non-standard
install path.

Prompted subject extraction is the default because it gives SAM 3.1 the clearest
target. Box and point prompts are also passed through with `--box` and
`--point`. When you pass multiple `--prompt` values, the plugin combines the
best SAM mask for each prompted label so subject-plus-prop cutouts can stay
together.

The plugin owns planning, manifests, stdout/stderr discipline, mask selection,
matte cleanup, transparent PNG composition, and artifact hashing. `mere.run`
owns SAM 3.1 model resolution and segmentation.

## Outputs

The plugin records:

- transparent PNG output
- grayscale mask output
- `mere.run vision segment` JSON and mask artifacts
- SHA-256 hashes after success
- no-op cleanup status, because no remote resources are created

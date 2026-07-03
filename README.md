# mere-run-plugins

Official companion plugins for `mere.run`.

The core `mere.run` CLI stays local-first. This repo contains explicit bridges
to user-controlled outside resources: RunPod pods, SSH-accessed GPU machines,
and future provider runners. A plugin can automate remote compute, but it must
use the user's account, credentials, spending limits, and cleanup policy.

## What Lives Here

- Contract schemas used by official plugins.
- A live plugin catalog that `mere.run` can fetch for one-shot installs.
- Canonical recipe files for repeatable workflows.
- Reference-evaluation recipes for LoRA comparisons.
- Provider-specific and local-production companion CLIs.
- Test utilities that verify plugin manifests, plans, and run manifests.

## RunPod Plugin

`mere-runpod` runs a normal `mere.run image train-lora` command on an ephemeral
RunPod pod owned by the user.

Install the plugin with `pipx`:

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-runpod"
```

```bash
mere-runpod manifest --json
mere-runpod doctor
mere-runpod volume ensure \
  --name mere-klein-cache \
  --data-center-id US-KS-2 \
  --size-gb 512 \
  --dry-run
mere-runpod plan \
  --recipe klein-style-lora \
  --data ./dataset \
  --output ./runs/style-demo
```

Real RunPod execution requires:

- `RUNPOD_API_KEY` in the environment or an env file.
- an SSH key registered with RunPod.
- a Linux CUDA `mere.run` build pack tarball.
- a paired image/caption dataset.

```bash
mere-runpod run \
  --recipe klein-style-lora \
  --data ./dataset \
  --output ./runs/style-demo \
  --build-pack ./build-packs/mere-run-linux-cuda.tar.gz \
  --network-volume-id <volume-id> \
  --data-center-id US-KS-2
```

The plugin writes `run.json`, streams remote logs, fetches the final LoRA,
archive, log, and metadata, then terminates the pod by default. Use
`--fetch-checkpoints` only when you need intermediate checkpoint safetensors.

Use `mere-runpod volume ensure --dry-run` to preview the request, then run it
without `--dry-run` once per RunPod data center to create or reuse a persistent
cache volume. The returned `volume.id` mounts at `/workspace` for training runs,
so `/workspace/mere-runpod/models` and `/workspace/mere-runpod/hub` can stay
warm across terminated pods. The plugin also caches build packs under
`/workspace/mere-runpod/build-packs` by SHA.
The bundled Klein recipes call the current core `klein-fast-style` training
preset and sample against `image-klein-9b`.

## Image Tools Plugin

`mere-image-tools` contains local image-production helpers that rely on the
installed `mere.run` CLI instead of adding a second model runtime.

Install the plugin with `pipx`:

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-image-tools"
```

The first command is `knockout`, which plans and runs a subject cutout through
`mere.run vision segment` with SAM 3.1:

```bash
mere-image-tools manifest --json
mere-image-tools doctor
mere-image-tools knockout \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png \
  --prompt "subject" \
  --prompt "prop"
```

By default, `knockout` calls `mere.run vision segment --model
vision-segment-sam31`. Set `MERE_IMAGE_TOOLS_MERE_RUN` or pass
`--mere-run-command` when you need to target a source checkout or non-standard
binary path.

## Catalog

The live catalog is published from this repo:

```text
https://raw.githubusercontent.com/sawfwair/mere-run-plugins/main/catalog/plugins.v1.json
```

`mere.run plugin install mere-runpod` can read that catalog and run the exact
`pipx install` command from the selected `main` channel:

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-runpod"
```

## Contract Philosophy

Plugins are companion executables, not dynamic code loaded into `mere.run`.
They expose a shared command fashion:

```text
<plugin> manifest --json
<plugin> doctor
<plugin> plan ...
<plugin> run ...
<plugin> resume <run.json>
<plugin> cleanup <run.json>
```

Provider-specific helper commands, such as `mere-runpod volume`, are allowed
when they keep stdout machine-readable. Helpers that can create paid resources
must expose a dry-run or plan mode.

The stdout/stderr rule matches `mere.run`: stdout is machine-readable when a
command promises JSON or paths; stderr is for diagnostics.

## Validate

```bash
./scripts/check.sh
```

## Repo Layout

```text
contracts/                 JSON schemas for plugin, recipe, run, and artifacts
catalog/                   live install catalog for official plugins
docs/plugins/              plugin contract, discovery, and security notes
docs/recipes/              captioning and LoRA recipe guidance
recipes/                   canonical machine-readable recipe files
eval-recipes/              canonical machine-readable eval protocols
packages/mere-runpod/      first official provider plugin
packages/mere-image-tools/ local image-production plugin
scripts/check.sh           repo gate
scripts/validate_repo.py   schema/manifest/recipe smoke validation
SECURITY.md                private vulnerability reporting policy
```

# RunPod Plugin

`mere-runpod` runs `mere.run` workflows on ephemeral RunPod pods owned by the
user.

The first supported workflow is FLUX.2 Klein LoRA training.

## Why This Is A Plugin

The core `mere.run` repo is local-first. RunPod creates paid remote compute, so
it belongs in an explicit companion plugin. The plugin still runs the normal
`mere.run image train-lora` command remotely, which keeps training behavior
aligned with local runs.

## Required Inputs

- `RUNPOD_API_KEY`
- SSH private/public key registered with RunPod
- paired dataset directory
- recipe id or recipe JSON file
- Linux CUDA `mere.run` build pack

For Klein recipes, set `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` in the environment
or in the `--env-file` before running. The plugin fails preflight if the token
is missing.

## Commands

```bash
mere-runpod doctor
mere-runpod volume ensure \
  --name mere-klein-cache \
  --data-center-id US-KS-2 \
  --size-gb 512 \
  --dry-run
mere-runpod plan --recipe klein-style-lora --data ./dataset --output ./runs/foo
mere-runpod run \
  --recipe klein-style-lora \
  --data ./dataset \
  --output ./runs/foo \
  --build-pack ./build-packs/mere-run-linux-cuda.tar.gz \
  --network-volume-id <volume-id> \
  --data-center-id US-KS-2
mere-runpod cleanup ./runs/foo/run.json
```

## Cleanup

The plugin terminates the pod by default after fetching the final LoRA, archive,
log, and small metadata files. Intermediate checkpoint safetensors are skipped
unless `--fetch-checkpoints` is passed. Pass `--keep-pod` only for active
debugging.

## Build Pack Strategy

The plugin requires a build pack for real remote runs. This avoids spending H100
minutes compiling Swift and CUDA dependencies on every run. The build pack must
be a prebuilt Linux CUDA package tarball, such as one produced on Linux by
`scripts/package-linux.sh`.

Bootstrap/source packs that contain `source.tar.gz` and a wrapper `bin/mere.run`
compile on the paid pod. The plugin rejects those packs by default; pass
`--allow-bootstrap-build-pack` only for an intentional slow debug run.

## Network Volume Strategy

For fast repeated training, use a RunPod network volume as the persistent model
cache:

```bash
mere-runpod volume list
mere-runpod volume ensure --name mere-klein-cache --data-center-id US-KS-2 --size-gb 512 --dry-run
mere-runpod volume ensure --name mere-klein-cache --data-center-id US-KS-2 --size-gb 512
```

`volume ensure --dry-run` prints the billable storage request without calling
RunPod. Running it without `--dry-run` returns JSON with `volume.id` and
`volume.dataCenterId`. Pass those values to `run` as `--network-volume-id` and
`--data-center-id`. The volume replaces the pod's normal `/workspace` disk, so
the plugin's existing
`/workspace/mere-runpod/models` and `/workspace/mere-runpod/hub` paths survive
after the pod is terminated. The plugin also caches Linux CUDA build packs under
`/workspace/mere-runpod/build-packs` by SHA, so repeated runs avoid re-uploading
the same package.

Remote CUDA training defaults to `MLX_CUDA_USE_CUDNN_SDPA=0` and
`MLX_CUDA_GRAPH_CACHE_SIZE=4096`. Override either environment variable before
`mere-runpod run` only when deliberately testing alternate MLX CUDA graph
behavior.

RunPod network volumes for pods are Secure Cloud resources and must be attached
when the pod is created. They are tied to a data center, so choose one with the
H100/A100 availability you plan to use.

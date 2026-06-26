# mere-runpod

RunPod companion plugin for `mere.run`.

Use it when you want to run a canonical `mere.run` recipe on a user-owned
ephemeral RunPod pod, retrieve artifacts, and terminate the pod automatically.

## Commands

```bash
pipx install "git+https://github.com/sawfwair/mere-plugins.git@main#subdirectory=packages/mere-runpod"
mere-runpod manifest --json
mere-runpod doctor
mere-runpod volume ensure --name mere-klein-cache --data-center-id US-KS-2 --size-gb 512 --dry-run
mere-runpod plan --recipe klein-style-lora --data ./dataset --output ./runs/foo
mere-runpod run --recipe klein-style-lora --data ./dataset --output ./runs/foo --build-pack ./mere-run-linux-cuda.tar.gz --network-volume-id <volume-id> --data-center-id US-KS-2
mere-runpod cleanup ./runs/foo/run.json
```

Klein recipes require `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` before a paid pod is
created. The build pack must be a prebuilt Linux CUDA package tarball; source
bootstrap packs are rejected unless `--allow-bootstrap-build-pack` is passed for
an intentional slow debug run.

RunPod network volumes are the recommended cache for Klein training. Preview the
billable storage request with `volume ensure --dry-run`, then create or reuse
one with `volume ensure`. Pass the returned `volume.id` to `run` with
`--network-volume-id` and pass the same `volume.dataCenterId` to
`--data-center-id`. The volume mounts at `/workspace`, so model and Hub caches
under `/workspace/mere-runpod` survive pod termination. Build packs are also
cached there by SHA, so repeated runs avoid re-uploading the same Linux CUDA
package. Volumes are tied to a RunPod data center; choose a data center with the
GPU class you intend to rent.

Remote CUDA training defaults to `MLX_CUDA_USE_CUDNN_SDPA=0` and
`MLX_CUDA_GRAPH_CACHE_SIZE=4096`. Override either environment variable before
`run` only when intentionally testing alternate MLX CUDA behavior.

## Safety

`run` terminates the pod by default after fetching the final LoRA, archive, log,
and small metadata files. Intermediate checkpoint safetensors can be large; pass
`--fetch-checkpoints` only when you need the full checkpoint tree. Use
`--keep-pod` only for active debugging.

All JSON-producing commands keep stdout machine-readable. Diagnostics, remote
logs, and provider errors go to stderr.

# mere-run-plugins

Official companion plugins for `mere.run`.

[Plugin catalog](https://plugins.mere.run/) ·
[Documentation](https://plugins-docs.mere.run/) ·
[Plugin contract](https://plugins-docs.mere.run/plugins/contract)

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

## Face Tools Plugin

`mere-face-tools` composes the native `mere.run vision face` detector and
embedder into a resumable SQLite photo index and reference-face search. The
plugin owns library traversal, change detection, ranking, and review artifacts;
core `mere.run` owns model download and inference.

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-face-tools"
mere.run model pull vision-face-buffalo-l
mere-face-tools index \
  --photos /Volumes/Photos \
  --database ./faces.sqlite3 \
  --output-dir ./face-index
mere-face-tools search \
  --database ./faces.sqlite3 \
  --reference ./scott.jpg \
  --output-dir ./searches/scott
```

Search writes ranked JSON and CSV, a contact sheet, and symlink-only review
folders. It never changes or copies the source photo library.

## Workflow Tools

`mere-workflow-tools` installs six focused companion commands that turn common
local inference workflows into repeatable manifests, plus graph-provider
conformance, reusable native graph templates, and conservative ComfyUI API
import:

```bash
mere-doc-tools process --input ./scan.png --output-dir ./doc-out
mere-media-scrub scrub --input ./frames --output-dir ./scrub-out
mere-dataset-tools caption --input ./dataset --output-dir ./caption-out --trigger-token STYLE
mere-transcript-tools transcribe --input ./meeting.wav --output-dir ./transcript-out
mere-image-compose generate --prompt "a product render" --output-dir ./image-out
mere-batch-runner run-jobs --jobs ./jobs.jsonl --output-dir ./batch-out
mere-graph-conformance --provider mere-dataset-tools --json
mere-graph-compile ./program.json --output ./workflow.json --report-output ./compile.json --json
mere-graph-studio --workspace ./production
mere-dataset-tools graph templates list --json
mere-dataset-tools graph comfy inspect ./comfy-workflow.json --json
```

These tools call existing `mere.run` surfaces such as `vision ocr`,
`text anonymize`, `vision caption`, `speech transcribe`, and `image generate`.
The plugin layer owns planning, artifact hashes, resumability, and local cleanup
state.

## VFX Tools Plugin

`mere-vfx-tools` turns native `mere.run` segmentation, tracking, pose,
optical-flow, depth, geometry, image generation, and start/end-frame video
generation into durable shot workflows. It delivers roto mattes and alpha
video, track exports, QC, motion passes, generative shot helpers, native
single- and multi-view geometry handoffs, verified TripoSR OBJ/PLY/GLB meshes,
and reconstruction-only InstantMesh meshes from four or six artist-supplied
views without adding a second inference runtime or generating unlicensed views.

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-vfx-tools"
mere-vfx-tools roto --request-json ./roto.json --output-dir ./shot010
```

## Animatic Tools Plugin

`mere-animatic-tools` contains local production helpers for relay-connected
Animatic workflows: character knockouts, reference packs, continuity checks,
shot kits, storyboard repair, edit review, voice kits, location plates, style
locks, and delivery prep.

```bash
mere-animatic-tools manifest --json
mere-animatic-tools doctor
mere-animatic-tools shot-kit \
  --request-json ./request.json \
  --output-dir ./animatic-out \
  --run-id shot-kit-001
```

The plugin writes local artifacts and a durable `run.json`; it does not create
paid resources.

## ShotGrid Tools Plugin

`mere-shotgrid-tools` publishes local `mere.run` artifacts into ShotGrid, now
Autodesk Flow Production Tracking, without moving inference into ShotGrid.

Install the plugin with `pipx`:

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-shotgrid-tools"
```

Use `plan` to record the exact remote mutations before any ShotGrid write:

```bash
mere-shotgrid-tools manifest --json
mere-shotgrid-tools doctor
mere-shotgrid-tools plan \
  --project-id 123 \
  --entity-type Shot \
  --entity-id 456 \
  --task-id 789 \
  --artifact ./review.mov \
  --thumbnail ./poster.png \
  --note "Ready for review." \
  --output-dir ./shotgrid-publish \
  --run-id shot010-v003
mere-shotgrid-tools run ./shotgrid-publish/run.json
```

`publish` combines planning and execution. It writes `run.json` before creating
the ShotGrid Version, then records each created Version, upload, thumbnail, Note,
Playlist link, and Task status update as it succeeds. `cleanup` skips by default;
deleting plugin-created tracking records requires explicit confirmation.

`pull-tasks` queries ShotGrid Tasks and writes JSONL job requests for local relay
or batch tooling.

## Perform Plugin

`mere-perform` plans and runs realtime Magenta Heart performances through the
installed `mere.run music realtime` command. It records a durable `run.json`,
exports a local stage UI, passes MIDI mappings through to CoreMIDI, writes event
JSONL, and captures WAV output when requested. The show file treats prompts as
a palette of blendable anchors with roles, jam/solo modes, prompt strength, and
patch-level realtime controls. By default, the initial prompt stays stable and
the MIDI controller drives the performance; timed prompt changes require
`--sequence-scenes`. Its stage UI also renders a Jam-inspired MIDI controller
surface with source/gate readouts and an interactive piano strip. Physical MIDI
ingestion stays in native `mere.run`; the live stage mirrors observed
`mere.run` note logs through a local `stage/live.json` feed and can send typed
prompts back into the running `mere.run --interactive` process.

Install the plugin with `pipx`:

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-perform"
```

```bash
mere-perform manifest --json
mere-perform doctor
mere-perform show-template --output ./show.json
mere-perform plan \
  --show ./show.json \
  --output-dir ./runs/heart-demo \
  --run-id heart-demo \
  --no-play
mere-perform stage ./runs/heart-demo/run.json
mere-perform run ./runs/heart-demo/run.json
```

The plugin does not create paid resources and does not ship another Magenta
runtime. It wraps the local `mere.run` realtime surface and owns planning,
stage export, event recording, artifact hashes, and cleanup state.

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
corepack pnpm install --frozen-lockfile
corepack pnpm docs:coverage
corepack pnpm docs:build
```

Run the docs locally with `corepack pnpm docs:dev`. The public docs site at
`plugins-docs.mere.run` is deployed separately from the built
`docs/.vitepress/dist/` output; the catalog site at `plugins.mere.run` lives in
its own repo.

## Repo Layout

```text
contracts/                 JSON schemas for plugin, recipe, run, and artifacts
catalog/                   live install catalog for official plugins
docs/                      comprehensive VitePress guide, plugin, reference, and operations docs
recipes/                   canonical machine-readable recipe files
eval-recipes/              canonical machine-readable eval protocols
packages/mere-runpod/      first official provider plugin
packages/mere-image-tools/ local image-production plugin
packages/mere-face-tools/  local face-library indexing and search plugin
packages/mere-workflow-tools/ local document, media, dataset, transcript, image, and batch tools
packages/mere-animatic-tools/ local Animatic production helpers
packages/mere-shotgrid-tools/ ShotGrid production-tracking bridge
packages/mere-perform/     realtime performance and stage UI plugin
packages/mere-vfx-tools/   local shot-oriented VFX production plugin
scripts/check.sh           repo gate
scripts/validate_repo.py   schema/manifest/recipe smoke validation
SECURITY.md                private vulnerability reporting policy
```

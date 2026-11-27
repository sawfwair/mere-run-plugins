# Check plugin readiness

## Check your installation

Use `mere.run plugin list` to check the installed version and manifest status.
Run the plugin's readiness check using its catalog ID:

```bash
mere.run plugin doctor mere-image-tools
```

For plugin-specific options, pass `doctor` through `plugin run`. For example,
check local AnyDoc conversion with redaction disabled:

```bash
mere.run plugin run mere-doc-tools -- doctor --extractor anydoc --no-redact
```

Use `mere.run plugin run PLUGIN_ID -- COMMAND` to launch signed plugins. It also
works with pipx executables on your `PATH`. Check the reported `ok`, `ready`,
or `status` and the individual checks. A basic doctor may only verify the
executable and local dependencies. It may leave model availability,
permissions, or access to a configured service for a workflow-specific check.

If a doctor reports that it cannot find `mere.run`, run
`command -v mere.run` from the same shell. For the macOS app installed in
Applications, add the directory containing the CLI to the current shell:

```bash
export PATH="/Applications/MereRun.app/Contents/Helpers:$PATH"
```

## Check the selected workflow

For a managed model, use `mere.run model info MODEL_ID` to inspect local files
and `mere.run model capabilities` to check runtime support. If needed, download
the model with `mere.run model pull MODEL_ID`. Some models require accepting
upstream terms. Use the model in your selected plan or plugin guide.

For a portable graph, check the selected executor before running it:

```bash
mere.run graph preflight ./workflow.graph.json --inputs-json ./inputs.json --json
```

| Plugin | What to check before running |
| --- | --- |
| [Frontier Handoff](/plugins/frontier-handoff) | A signed-in Claude Code or Codex CLI for the selected backend |
| [Firecrawl Local](/plugins/firecrawl-local) | The separately installed Firecrawl Local app or a configured compatible endpoint |
| [SearXNG Search](/plugins/searxng-search) | A reachable SearXNG instance with JSON results enabled. Docker is required to install the local instance. |
| [Computer Use](/plugins/computer-use) | macOS, Cua Driver with Accessibility and Screen Recording permissions, Pi, and a compatible vision model |
| [Identity Tools](/plugins/identity-tools) | The configured identity backend for training and evaluation. Local planning and report inspection have their own commands. |
| [Geospatial Tools](/plugins/geo-tools) | STAC or prepared raster inputs, a supported Core build, and the selected native model for inference. Some backends require converted checkpoints. |
| [RunPod Runner](/plugins/runpod) | RunPod API credentials, SSH keys, and the build inputs for the selected recipe |
| [Terminal-Bench](/plugins/terminal-bench) | An explicit Docker context, Harbor, and the selected local models. Use the documented deep doctor for model checks. |
| [Image Tools](/plugins/image-tools) | The Core segmentation runtime and `vision-segment-sam31` |
| [Face Tools](/plugins/face-tools) | A supported Core face runtime and `vision-face-buffalo-l` |
| [Archive Tools](/plugins/archive-tools) | Local privacy and embedding models for indexing. Web research and image-sidecar workflows have additional requirements. |
| [VFX Tools](/plugins/vfx-tools) | FFmpeg for applicable media workflows and the model selected for the shot. Check specialized runtimes such as Blender or an authenticated local API when the workflow uses them. |
| [Animatic Tools](/plugins/animatic-tools) | The model for each kit that invokes inference, and Blender for Set Kit lighting or plate rendering |
| [Film Studio](/plugins/film-tools) | Pi, Core, FFmpeg, and FFprobe. Check the approved plan for production models and any companion tools. |
| [ShotGrid Tools](/plugins/shotgrid-tools) | The Autodesk Flow Production Tracking site, credentials, and access to the selected project |
| [Perform](/plugins/perform) | The realtime music runtime and the model in the show. Connect a MIDI device if the show uses one. |
| [Document Tools](/plugins/document-tools) | AnyDoc for local conversion, or Core and the selected models for OCR, redaction, or structured extraction |
| [Media Scrub](/plugins/media-scrub) | Local OCR and redaction models for scrubbing. Frame analysis can run without models. |
| [Dataset Tools](/plugins/dataset-tools) | Captioning models and optional OCR models for dataset prep, or a compatible base model for the selected training workflow |
| [Transcript Tools](/plugins/transcript-tools) | A compatible ASR model, plus diarization and redaction models when those features are enabled |
| [Audio Post](/plugins/audio-post) | FFmpeg, plus the task-specific model for denoise, dereverb, stem separation, MIDI transcription, or Foley |
| [Reviewed Image](/plugins/image) | mere.run 0.79.0 or later, the managed Nemotron Image Q8 checkpoint with accepted NVIDIA terms, and Inkling 2 Mini. |
| [Image Compose](/plugins/image-compose) | The selected image generation model and any referenced LoRA files. Local inpainting has a model-free path. |
| [Batch Runner](/plugins/batch-runner) | Core and the models or runtimes required by the individual commands in the batch |

## Upgrade or switch installation methods

On Apple Silicon with macOS 15 or later, rerun
`mere.run plugin install PLUGIN_ID --yes` to install the current signed
release. The previous verified version is retained when a newer release
activates. Use `mere.run plugin rollback PLUGIN_ID` to preview a rollback and
add `--yes` to confirm it.

On Linux, or to choose pipx on macOS, install with
`mere.run plugin install PLUGIN_ID --source --yes`. Add `--force` to reinstall
from the catalog's source ref. If a signed bundle is active, get its package
name with `mere.run plugin info PLUGIN_ID`. Use
`mere.run plugin uninstall PACKAGE` to review the affected commands and add
`--yes` to confirm removal before installing from source. Removing a shared
package such as `mere-workflow-tools` removes all managed commands in that
package.

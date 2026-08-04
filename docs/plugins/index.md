# Official plugins

The live catalog contains 14 official companion executables.

| Plugin | Command | Primary job | Execution |
| --- | --- | --- | --- |
| [Geospatial Tools](/plugins/geo-tools) | `mere-geo-tools` | Pinned geospatial candidate models with raster provenance | Local or Relay |
| [Face Tools](/plugins/face-tools) | `mere-face-tools` | Photo-library indexing and reference-face search | Local |
| [VFX Tools](/plugins/vfx-tools) | `mere-vfx-tools` | Shot-oriented VFX and verified 3D handoffs | Local |
| [Perform](/plugins/perform) | `mere-perform` | Realtime Magenta Heart performance | Local |
| [Image Tools](/plugins/image-tools) | `mere-image-tools` | Subject knockout and matte cleanup | Local |
| [Animatic Tools](/plugins/animatic-tools) | `mere-animatic-tools` | Animatic production kits and delivery prep | Local |
| [ShotGrid Tools](/plugins/shotgrid-tools) | `mere-shotgrid-tools` | Production tracking and review publishing | User-controlled provider |
| [RunPod Runner](/plugins/runpod) | `mere-runpod` | Ephemeral GPU recipe execution | User-controlled provider |
| [Document Tools](/plugins/document-tools) | `mere-doc-tools` | OCR and PII redaction | Local |
| [Media Scrub](/plugins/media-scrub) | `mere-media-scrub` | Batch frame OCR and redaction | Local |
| [Dataset Tools](/plugins/dataset-tools) | `mere-dataset-tools` | LoRA captions, OCR, and contact sheets | Local |
| [Transcript Tools](/plugins/transcript-tools) | `mere-transcript-tools` | Speech transcription and redaction | Local |
| [Image Compose](/plugins/image-compose) | `mere-image-compose` | Repeatable image generation compositions | Local |
| [Batch Runner](/plugins/batch-runner) | `mere-batch-runner` | Resumable JSONL core-command batches | Local |

## Install by catalog ID

```bash
mere.run plugin list
mere.run plugin install mere-vfx-tools
```

Catalog IDs are stable machine identifiers. Some shared-package plugins have an
ID that matches the executable rather than the Python distribution name.

## Shared contract

```text
<plugin> manifest --json
<plugin> doctor
<plugin> plan ...
<plugin> run ...
<plugin> resume <run.json>
<plugin> cleanup <run.json>
```

Read the [plugin contract](/plugins/contract) for required behavior, streams,
exit codes, and discovery rules.

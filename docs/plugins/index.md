# Official plugins

The live catalog contains 18 official companion executables.

| Plugin | Command | Primary job | Execution |
| --- | --- | --- | --- |
| [Identity Tools](/plugins/identity-tools) | `mere-identity-tools` | Local identity curricula, text adapters, evaluation, and sanitized reports | Local or Relay |
| [Geospatial Tools](/plugins/geo-tools) | `mere-geo-tools` | Humanitarian hazard candidates and Earth-observation embeddings with raster provenance | Local or Relay |
| [Face Tools](/plugins/face-tools) | `mere-face-tools` | Photo-library indexing and reference-face search | Local |
| [Archive Tools](/plugins/archive-tools) | `mere-archive-tools` | PII-reduced shared-drive indexing and search | Local |
| [VFX Tools](/plugins/vfx-tools) | `mere-vfx-tools` | Shot-oriented VFX and verified 3D handoffs | Local |
| [Perform](/plugins/perform) | `mere-perform` | Realtime Magenta Heart performance | Local |
| [Image Tools](/plugins/image-tools) | `mere-image-tools` | Subject knockout and matte cleanup | Local |
| [Animatic Tools](/plugins/animatic-tools) | `mere-animatic-tools` | Animatic production kits and delivery prep | Local |
| [Film Studio](/plugins/film-tools) | `mere-film-tools` | Pi-directed short-film development, local production, review, and delivery | Local plus user-selected Pi provider |
| [ShotGrid Tools](/plugins/shotgrid-tools) | `mere-shotgrid-tools` | Production tracking and review publishing | User-controlled provider |
| [RunPod Runner](/plugins/runpod) | `mere-runpod` | Ephemeral GPU recipe execution | User-controlled provider |
| [Terminal-Bench](/plugins/terminal-bench) | `mere-terminal-bench` | Pinned, resource-bounded local agent evaluation | Local Docker and `mere.run` |
| [Document Tools](/plugins/document-tools) | `mere-doc-tools` | Markdown conversion, OCR, and PII redaction | Local |
| [Media Scrub](/plugins/media-scrub) | `mere-media-scrub` | Batch frame OCR and redaction | Local |
| [Dataset Tools](/plugins/dataset-tools) | `mere-dataset-tools` | LoRA captions, OCR, and contact sheets | Local |
| [Transcript Tools](/plugins/transcript-tools) | `mere-transcript-tools` | Speech transcription and redaction | Local |
| [Image Compose](/plugins/image-compose) | `mere-image-compose` | Repeatable image generation compositions | Local |
| [Batch Runner](/plugins/batch-runner) | `mere-batch-runner` | Resumable JSONL core-command batches | Local |

## Install by catalog ID

```bash
mere.run plugin list
mere.run plugin install mere-vfx-tools --yes
```

Catalog IDs are stable machine identifiers. Some shared-package plugins have an
ID that matches the executable rather than the Python distribution name.
Omit `--yes` to preview the resolved installation command.

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

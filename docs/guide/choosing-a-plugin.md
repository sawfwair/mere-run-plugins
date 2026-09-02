# Choose a plugin

This guide is for users who know the task they want to complete but don't know
which companion command owns it. Choose the narrowest plugin that owns the
complete workflow.

| Task | Plugin | Reason to choose it |
| --- | --- | --- |
| Analyze flood or fire candidates, or create Earth-observation embeddings | [Geospatial Tools](/plugins/geo-tools) | Uses typed STAC inputs, content-addressed rasters, and explicit evidence boundaries |
| Index a photo library or find photos of the same person | [Face Tools](/plugins/face-tools) | Provides resumable indexing, similarity search, and review exports without changing source photos |
| Search mixed files on a shared drive | [Archive Tools](/plugins/archive-tools) | Uses read-only traversal, sensitive-data reduction, retention policies, and local hybrid search |
| Rotoscope, key, track, relight, restore, extend, or reconstruct a shot | [VFX Tools](/plugins/vfx-tools) | Produces shot-oriented workflows and verified handoff artifacts |
| Remove the background from a still image | [Image Tools](/plugins/image-tools) | Provides a focused SAM 3.1 knockout and matte-cleanup workflow |
| Build shot, character, voice, set, or delivery kits | [Animatic Tools](/plugins/animatic-tools) | Produces artifact bundles for animatic workflows |
| Develop and produce a governed short film | [Film Studio](/plugins/film-tools) | Separates proposals, approvals, local media generation, review, and delivery |
| Perform with a local generative music model | [Perform](/plugins/perform) | Adds MIDI control, a stage interface, event logs, and audio capture |
| Publish local artifacts for production review | [ShotGrid Tools](/plugins/shotgrid-tools) | Plans and records Versions, uploads, Notes, Playlists, and task updates |
| Train a Klein LoRA on rented GPUs | [RunPod Runner](/plugins/runpod) | Uses planned, user-owned pods with artifact retrieval and cleanup by default |
| Compare local agents with Terminal-Bench | [Terminal-Bench](/plugins/terminal-bench) | Pins the benchmark protocol and records matched, resource-bounded results |
| Train and evaluate an identity adapter | [Identity Tools](/plugins/identity-tools) | Coordinates curricula, private execution, evaluation, and sanitized reports |
| Convert or process a document | [Document Tools](/plugins/document-tools) | Uses local AnyDoc conversion or OCR with optional local anonymization |
| Remove sensitive text from media frames | [Media Scrub](/plugins/media-scrub) | Applies resumable OCR and sensitive-data reduction across frame batches |
| Prepare an image-caption dataset | [Dataset Tools](/plugins/dataset-tools) | Produces captions, optional OCR sidecars, trigger tokens, and a contact sheet |
| Transcribe and reduce sensitive text in audio | [Transcript Tools](/plugins/transcript-tools) | Uses local speech recognition and optional anonymization |
| Repeat an image-generation composition | [Image Compose](/plugins/image-compose) | Records prompts, references, LoRAs, dimensions, seeds, and outputs |
| Run many explicit `mere.run` commands | [Batch Runner](/plugins/batch-runner) | Preserves resumable JSON Lines job state |

## Choose the workflow scope

For one still-image knockout, use Image Tools. For a shot that requires
rotoscoping, tracking, alpha delivery, and quality control, use VFX Tools.

For a single core inference command, use `mere.run` directly. Choose a plugin
when you need planning, multiple steps, resumability, artifact records, or a
provider boundary.

## Identify the execution boundary

Most plugins run on the local machine. The following workflows cross an
additional boundary:

- Geospatial Tools can use a configured Relay worker.
- Identity Tools uses a configured private execution backend.
- Film Studio can use a user-selected Pi provider for proposal work.
- ShotGrid Tools writes to Autodesk Flow Production Tracking.
- RunPod Runner creates resources in the user's RunPod account.
- Terminal-Bench uses the Docker context that you select.

Before you start a paid or remote workflow, read [Provider
safety](/operations/provider-safety).

# Choose a plugin

Start from the outcome, not the model.

| I need to… | Use | Why |
| --- | --- | --- |
| Segment flood/fire candidates or create Earth-observation embeddings | [`mere-geo-tools`](/plugins/geo-tools) | Typed STAC inputs, content-addressed rasters, hardware-scaled native models, and explicit evidence boundaries |
| Index a photo library or find photos of the same person | [`mere-face-tools`](/plugins/face-tools) | Resumable local indexing, similarity search, and review exports without changing source photos |
| Search years of mixed files on a shared drive | [`mere-archive-tools`](/plugins/archive-tools) | Read-only traversal, required PII reduction, three retention tiers, and local hybrid search |
| Roto, key, track, relight, restore, extend, or reconstruct a shot | [`mere-vfx-tools`](/plugins/vfx-tools) | Shot-oriented workflows and verified production handoffs |
| Cut a subject out of a still | [`mere-image-tools`](/plugins/image-tools) | Focused SAM 3.1 knockout and matte cleanup |
| Play a local generative music model live | [`mere-perform`](/plugins/perform) | MIDI, stage UI, prompt control, logs, and capture |
| Build shot, character, voice, or delivery kits | [`mere-animatic-tools`](/plugins/animatic-tools) | Animatic-specific artifact bundles |
| Publish local artifacts for production review | [`mere-shotgrid-tools`](/plugins/shotgrid-tools) | Versions, uploads, Notes, Playlists, and task updates |
| Train a Klein LoRA on rented GPUs | [`mere-runpod`](/plugins/runpod) | Planned user-owned pods, artifact fetch, cleanup by default |
| Convert or OCR a document | [`mere-doc-tools`](/plugins/document-tools) | AnyDoc Markdown or local OCR, plus optional local anonymization |
| Scrub text and PII across frames | [`mere-media-scrub`](/plugins/media-scrub) | Resumable frame-batch privacy workflow |
| Caption a LoRA dataset | [`mere-dataset-tools`](/plugins/dataset-tools) | Captions, OCR sidecars, trigger tokens, contact sheet |
| Transcribe and redact audio | [`mere-transcript-tools`](/plugins/transcript-tools) | Local ASR plus optional anonymization |
| Repeat an image generation composition | [`mere-image-compose`](/plugins/image-compose) | Records prompt, references, LoRA, dimensions, seed, and output |
| Run many explicit core commands | [`mere-batch-runner`](/plugins/batch-runner) | Durable JSONL job status and resumability |

## Narrow or broad?

Prefer the narrowest plugin that owns the whole workflow. For a single still
knockout, Image Tools is simpler than VFX Tools. For a shot that needs roto,
tracking, alpha delivery, and QC, VFX Tools owns the larger lifecycle.

## Local or provider-backed?

Fourteen catalog commands can operate locally. Geospatial Tools can also run on
a provisioned Relay fleet. RunPod Runner is provider-backed and therefore has
stronger planning and cleanup obligations. Read
[Provider safety](/operations/provider-safety) before creating paid resources.

---
layout: home

hero:
  name: 'mere.run plugins'
  text: 'Local AI, wired into real production.'
  tagline: Official companion executables for VFX, live performance, production tracking, private media workflows, automation, and user-owned GPU training.
  actions:
    - theme: brand
      text: Install your first plugin
      link: /guide/getting-started
    - theme: alt
      text: Browse all 13 plugins
      link: /plugins/
    - theme: alt
      text: Read the contract
      link: /plugins/contract

features:
  - title: Create
    details: Roto, mattes, clean plates, depth, geometry, image composition, character packs, and production-ready artifacts.
    link: /plugins/vfx-tools
  - title: Perform
    details: Play Magenta Heart locally with MIDI, live prompt control, a stage UI, event logs, and WAV capture.
    link: /plugins/perform
  - title: Produce
    details: Move local outputs through animatics and ShotGrid without moving inference into a hosted service.
    link: /guide/shotgrid-publish
  - title: Protect
    details: OCR, transcribe, caption, and redact sensitive material on the machine that owns the source files.
    link: /guide/private-workflows
  - title: Scale
    details: Run resumable JSONL batches locally or canonical LoRA recipes on user-owned ephemeral RunPod GPUs.
    link: /guide/runpod-lora
  - title: Verify
    details: Every run has a durable manifest, explicit artifacts, machine-readable output, and cleanup semantics.
    link: /guide/artifacts-and-runs
---

## The plugin boundary

`mere.run` owns canonical model loading and inference. Plugins own the production
work around it: planning, orchestration, manifests, post-processing, provider
resources, artifact handoff, and cleanup.

That boundary keeps the core runtime local and predictable while giving each
workflow a stable, automatable command surface.

```bash
mere.run plugin list
mere.run plugin install mere-vfx-tools
mere-vfx-tools doctor
mere-vfx-tools manifest --json
```

Start with the [getting-started guide](/guide/getting-started), pick from the
[complete catalog](/plugins/), or inspect the live machine-readable catalog at
[plugins.mere.run](https://plugins.mere.run/catalog/plugins.v1.json).

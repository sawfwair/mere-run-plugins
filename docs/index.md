---
layout: home

hero:
  name: 'mere.run plugins'
  text: 'Build repeatable workflows around local inference'
  tagline: Plan work, run local or user-owned resources, preserve artifacts, and clean up through 18 official companion commands.
  actions:
    - theme: brand
      text: Install a plugin
      link: /guide/getting-started
    - theme: alt
      text: Choose a plugin
      link: /guide/choosing-a-plugin
    - theme: alt
      text: View all plugins
      link: /plugins/

features:
  - title: Create media
    details: Build image, visual-effects, animatic, film, and live-performance workflows around the installed mere.run runtime.
    link: /plugins/
  - title: Process private data
    details: Convert documents, index archives, transcribe audio, and reduce sensitive text on the machine that owns the source files.
    link: /guide/private-workflows
  - title: Use external resources
    details: Publish review artifacts or run GPU training through accounts, credentials, limits, and cleanup policies that you control.
    link: /operations/provider-safety
  - title: Automate workflows
    details: Use stable manifests, graph providers, JSON output, artifact hashes, and resumable run records.
    link: /guide/artifacts-and-runs
  - title: Evaluate models
    details: Check tool selection, arguments, clarification, and fixture outcomes with 240 ATE-derived cases.
    link: /guide/ate-benchmark
  - title: Extend the system
    details: Implement a companion executable against language-neutral plugin, graph, recipe, and run contracts.
    link: /plugins/contract
---

## Understand the plugin boundary

This documentation is for `mere.run` users, automation authors, and plugin
maintainers. It explains how to choose, operate, and extend official companion
plugins.

`mere.run` owns model installation, loading, and inference. Plugins own
workflow planning, orchestration, artifact records, post-processing, provider
resources, and cleanup.

To inspect and install a plugin, run:

```bash
mere.run plugin list
mere.run plugin install mere-vfx-tools --yes
mere-vfx-tools doctor
mere-vfx-tools manifest --json
```

For your first workflow, follow the [getting-started
guide](/guide/getting-started). To select a command by task, see [Choose a
plugin](/guide/choosing-a-plugin).

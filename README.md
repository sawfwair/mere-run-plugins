# mere.run plugins

This repository is for people who use or extend `mere.run` production
workflows. It contains the official plugin catalog, shared contracts, workflow
recipes, and companion command-line interfaces (CLIs).

`mere.run` owns model installation and inference. Plugins own the work around
inference, including planning, orchestration, artifact records,
post-processing, provider resources, and cleanup.

- [Read the documentation](https://plugins-docs.mere.run/)
- [Choose a plugin](https://plugins-docs.mere.run/guide/choosing-a-plugin)
- [View the live catalog](https://plugins.mere.run/catalog/plugins.v1.json)
- [Read the plugin contract](https://plugins-docs.mere.run/plugins/contract)

## Install a plugin

To inspect the available plugins, list the catalog:

```bash
mere.run plugin list
```

To preview an installation, omit `--yes`:

```bash
mere.run plugin install mere-image-tools
```

To install the plugin, confirm the catalog command:

```bash
mere.run plugin install mere-image-tools --yes
```

After installation, check the plugin and inspect its machine-readable
manifest:

```bash
mere-image-tools doctor
mere-image-tools manifest --json
```

For task-specific installation and first-run instructions, see the
[getting-started guide](https://plugins-docs.mere.run/guide/getting-started).

## Choose a plugin

The catalog contains 18 companion executables:

| Task | Plugin |
| --- | --- |
| Analyze geospatial data | [Geospatial Tools](https://plugins-docs.mere.run/plugins/geo-tools) |
| Index and search faces in a photo library | [Face Tools](https://plugins-docs.mere.run/plugins/face-tools) |
| Index and search a shared drive | [Archive Tools](https://plugins-docs.mere.run/plugins/archive-tools) |
| Create visual-effects shot artifacts | [VFX Tools](https://plugins-docs.mere.run/plugins/vfx-tools) |
| Remove a still-image background | [Image Tools](https://plugins-docs.mere.run/plugins/image-tools) |
| Produce animatic assets | [Animatic Tools](https://plugins-docs.mere.run/plugins/animatic-tools) |
| Produce a governed short film | [Film Studio](https://plugins-docs.mere.run/plugins/film-tools) |
| Run a live local music performance | [Perform](https://plugins-docs.mere.run/plugins/perform) |
| Publish review artifacts | [ShotGrid Tools](https://plugins-docs.mere.run/plugins/shotgrid-tools) |
| Run LoRA training on a user-owned pod | [RunPod Runner](https://plugins-docs.mere.run/plugins/runpod) |
| Compare local agents with Terminal-Bench | [Terminal-Bench](https://plugins-docs.mere.run/plugins/terminal-bench) |
| Run identity-adapter workflows | [Identity Tools](https://plugins-docs.mere.run/plugins/identity-tools) |
| Convert or process documents | [Document Tools](https://plugins-docs.mere.run/plugins/document-tools) |
| Remove sensitive text from media frames | [Media Scrub](https://plugins-docs.mere.run/plugins/media-scrub) |
| Prepare image-caption datasets | [Dataset Tools](https://plugins-docs.mere.run/plugins/dataset-tools) |
| Transcribe and reduce sensitive text | [Transcript Tools](https://plugins-docs.mere.run/plugins/transcript-tools) |
| Generate images with references or adapters | [Image Compose](https://plugins-docs.mere.run/plugins/image-compose) |
| Run resumable local command batches | [Batch Runner](https://plugins-docs.mere.run/plugins/batch-runner) |

For selection guidance, see
[Choose a plugin](https://plugins-docs.mere.run/guide/choosing-a-plugin).

## Understand the safety boundary

Plugins are separate executables. `mere.run` doesn't load plugin code into the
core process.

Every provider plugin must support `doctor`, `plan`, `run`, `resume`, and
`cleanup`. Before a plugin creates a paid resource, it must write `run.json`
and provide a plan or dry run. Remote providers terminate resources by default
unless you select an explicit keep or debug option.

Commands that promise JSON write machine-readable data to stdout. They write
diagnostics to stderr. Plugins must not write credentials or secrets to either
stream.

For the complete rules, see [Provider
safety](https://plugins-docs.mere.run/operations/provider-safety) and [Plugin
security](https://plugins-docs.mere.run/plugins/security).

## Develop a plugin

The repository uses Python packages for plugin executables and VitePress for
documentation. The main directories are:

```text
benchmark-recipes/  Pinned external benchmark protocols
bundles/            Reviewed inputs for signed macOS bundles
catalog/            The official installation catalog
contracts/          Language-neutral JSON Schemas
docs/               VitePress documentation source
eval-recipes/       Reference evaluation protocols
packages/           Python plugin packages
recipes/            Executable workflow recipes
scripts/            Validation and maintenance commands
```

For repository structure and contribution steps, see [Development
guidance](https://plugins-docs.mere.run/operations/development) and
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Validate a change

Before you open a pull request, run the repository gate:

```bash
./scripts/check.sh
```

To validate and build the documentation, run:

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm docs:coverage
corepack pnpm docs:build
```

The repository gate compiles packages, runs unit tests, validates contracts and
recipes, and tests installed commands. The Terminal-Bench smoke test remains
plan-only and verifies that the plugin doesn't create a Docker runtime.

A successful local build doesn't prove that a package, catalog, or website was
published. For release boundaries, see [Releasing and
deployment](https://plugins-docs.mere.run/operations/releasing).

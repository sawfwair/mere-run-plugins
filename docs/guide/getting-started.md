# Get started with a plugin

This guide is for `mere.run` users who want to install and run an official
plugin. It uses Image Tools because the first workflow runs locally and doesn't
require provider credentials.

## Before you begin

Install `mere.run`, and verify that the core command works:

```bash
mere.run --help
mere.run model list
```

For a provider workflow, you might also need provider credentials or external
tools. The plugin's `doctor` command reports those requirements without
creating resources.

## Inspect the catalog

To list the official plugins, run:

```bash
mere.run plugin list
```

To inspect one catalog entry and its installation source, run:

```bash
mere.run plugin info mere-image-tools
```

The [live plugin catalog](https://plugins.mere.run/catalog/plugins.v1.json) is
also available as JSON.

## Install Image Tools

To preview the installation command without running it, omit `--yes`:

```bash
mere.run plugin install mere-image-tools
```

To install the plugin, confirm the command:

```bash
mere.run plugin install mere-image-tools --yes
```

## Check the installation

To verify local dependencies, run:

```bash
mere-image-tools doctor
```

To inspect the plugin's capabilities and command contract, run:

```bash
mere-image-tools manifest --json
```

The `doctor` command checks the machine. The `manifest --json` command
describes the plugin and doesn't perform a readiness check or workflow.

## Plan a subject knockout

To write a plan without running inference, run:

```bash
mere-image-tools plan \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png \
  --prompt subject
```

The command writes a `run.json` file with the `planned` status. Review the
resolved command, input paths, output paths, and cleanup policy in that file.

## Run the plan

To execute the reviewed plan, pass its manifest to `run`:

```bash
mere-image-tools run ./subject.run.json
```

The exact manifest path appears in the `plan` output. Keep the `run.json` file
with the generated artifacts.

For an interactive local task that doesn't require a separate approval step,
use the one-shot command:

```bash
mere-image-tools knockout \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png \
  --prompt subject
```

## Continue with another workflow

- To select a plugin by task, see [Choose a
  plugin](/guide/choosing-a-plugin).
- To understand shared commands, see [Plugin
  lifecycle](/guide/lifecycle).
- To preserve and inspect workflow evidence, see [Artifacts and
  runs](/guide/artifacts-and-runs).
- To operate paid resources, see [Provider
  safety](/operations/provider-safety).

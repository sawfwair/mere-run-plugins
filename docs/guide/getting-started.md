# Getting started

## Prerequisites

Install a working `mere.run` CLI first. Most plugins call it directly, so verify
the core executable before debugging a plugin:

```bash
mere.run --help
mere.run models list
```

Provider-specific workflows can require additional credentials or tools. The
plugin's `doctor` command reports those requirements without creating resources.

## Discover the catalog

```bash
mere.run plugin list
```

The catalog is also available as JSON at
[`plugins.mere.run/catalog/plugins.v1.json`](https://plugins.mere.run/catalog/plugins.v1.json).

## Install a plugin

```bash
mere.run plugin install mere-image-tools
```

For direct development installs, every catalog entry points to a package
subdirectory in the public repository:

```bash
pipx install "git+https://github.com/sawfwair/mere-run-plugins.git@main#subdirectory=packages/mere-image-tools"
```

## Check readiness

```bash
mere-image-tools doctor
mere-image-tools manifest --json
```

`doctor` checks the machine. `manifest --json` describes the command surface,
capabilities, output policy, and security posture.

## Plan before execution

```bash
mere-image-tools plan \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png \
  --prompt subject
```

Planning writes a `run.json` with status `planned`. Inspect it, then execute:

```bash
mere-image-tools run ./subject.run.json
```

Or use the one-shot workflow when you do not need a separate approval step:

```bash
mere-image-tools knockout \
  --input ./frame.png \
  --output ./subject.png \
  --mask-output ./subject-mask.png \
  --prompt subject
```

## Keep the run manifest

Do not treat `run.json` as a temporary log. It is the durable record needed to
inspect, resume, clean up, and verify a run. See
[Artifacts and runs](/guide/artifacts-and-runs).

## Next steps

- [Choose a plugin](/guide/choosing-a-plugin)
- [Understand the lifecycle](/guide/lifecycle)
- [Build a VFX shot](/guide/vfx-shot)
- [Keep sensitive workflows private](/guide/private-workflows)

# Introduction to mere.run plugins

This guide is for people who run local AI production workflows or automate
those workflows. It explains the boundary between `mere.run` and its official
companion plugins.

## Understand what plugins add

Plugins turn individual inference commands into repeatable workflows. A plugin
can:

- Validate tools, inputs, credentials, and output locations.
- Write an inspectable plan before execution.
- Call the installed `mere.run` runtime for canonical model behavior.
- Coordinate local tools or user-controlled providers.
- Record artifacts, hashes, status, and cleanup in a `run.json` file.
- Provide machine-readable output for agents and pipelines.

Plugins run as separate executables. `mere.run` doesn't load plugin code into
the core process.

## Understand what stays in the core runtime

`mere.run` owns model discovery, download, storage, loading, and inference. A
plugin can select and compose core commands, but it must not ship a competing
model runtime.

This boundary keeps local inference behavior consistent. It also isolates
plugin dependencies, permissions, provider failures, and upgrades.

## Choose a workflow category

The catalog contains 18 official commands across the following workflow
categories:

| Category | Example tasks |
| --- | --- |
| Create media | Generate images, prepare visual-effects shots, produce animatics, make short films, and perform music |
| Process data | Analyze geospatial sources, search photo libraries, index archives, convert documents, and transcribe audio |
| Automate work | Compile graphs, prepare datasets, run command batches, and preserve resumable manifests |
| Use providers | Train adapters on RunPod and publish review artifacts to Flow Production Tracking |
| Evaluate systems | Compare local agents with Terminal-Bench and run identity-adapter evaluations |

For a task-to-command mapping, see [Choose a
plugin](/guide/choosing-a-plugin). For the complete catalog, see [Official
plugins](/plugins/).

## Apply the operating guarantees

Official plugins follow these guarantees:

- Local workflows keep their source data on the local machine unless the
  documented workflow uses a provider.
- Provider resources remain in your account.
- Paid work appears in a plan before it starts.
- Remote resources terminate by default.
- Commands that promise JSON write machine-readable data to stdout.
- Commands write human-readable diagnostics to stderr.
- A durable run manifest connects inputs, execution, artifacts, and cleanup.

To install and run a plugin, continue to [Getting
started](/guide/getting-started).

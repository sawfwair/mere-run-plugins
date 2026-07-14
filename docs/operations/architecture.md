# Architecture

The system has three deliberately separate planes.

## Core runtime

`mere.run` owns model discovery, storage, loading, canonical native behavior,
and inference commands. Plugins invoke the installed CLI; they do not duplicate
its model runtime.

## Companion plugins

This repository owns:

- the stable plugin, catalog, recipe, run, and artifact contracts;
- official companion executables;
- production planning and post-processing;
- provider automation against user-controlled accounts;
- durable run and artifact records.

Plugins are separate processes discovered by manifest. This isolates
dependencies and makes permissions, streams, failure, and upgrades explicit.

## Product surfaces

[`plugins.mere.run`](https://plugins.mere.run/) is the visual catalog and public
machine-readable catalog host. [`plugins-docs.mere.run`](https://plugins-docs.mere.run/)
is this VitePress product guide and operator reference. Each has its own
Cloudflare Worker and deploy command.

## Data flow

For a local workflow:

```text
request → plugin plan → run.json → mere.run command → post-process → artifacts + hashes
```

For a provider workflow:

```text
request → plan → durable run.json → create user resource → execute → fetch → cleanup → final run.json
```

## Boundary test

If a change alters canonical model loading or inference behavior, it belongs in
the core repository. If it composes stable core commands into a production
workflow or coordinates an external resource against the contracts, it belongs
here.

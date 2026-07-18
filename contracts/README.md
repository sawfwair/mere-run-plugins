# Contracts

These schemas define the stable surfaces shared by `mere.run` and official
companion plugins.

- `plugin.v1.schema.json`: plugin self-description printed by
  `<plugin> manifest --json`.
- `catalog.v1.schema.json`: live plugin catalog consumed by `mere.run plugin`.
- `recipe.v1.schema.json`: machine-readable workflow recipes.
- `eval-recipe.v1.schema.json`: machine-readable evaluation protocols.
- `run-manifest.v1.schema.json`: durable execution record written before remote
  resources are created.
- `artifact-bundle.v1.schema.json`: fetched result bundle inventory.
- `graph-node-provider.v1.schema.json`: versioned node catalog exposed by a
  graph-capable companion plugin.
- `graph-node-invocation.v1.schema.json`: confined node request written by the
  core graph runner.
- `graph-node-preflight.v1.schema.json`: structured readiness and requirement
  report returned by a provider.
- `graph-node-event.v1.schema.json`: streamed progress, preview, artifact,
  diagnostic, metric, heartbeat, and result records.
- `workflow-graph.v1.schema.json`: mirrored portable graph contract consumed
  unchanged by local, SSH, and Relay workers.
- `graph-run.v1.schema.json`: mirrored run manifest emitted by every executor.
- `graph-template-catalog.v1.schema.json`: discoverable reusable graph templates
  shipped by this companion repository.
- `graph-template-package.v1.schema.json`: confined user-published template
  descriptor pointing at portable graph and default-input documents.
- `workflow-program.v1.schema.json`: declarative reusable composition, static
  map, branch, and parallel-policy source compiled to an ordinary graph.
- `workflow-module.v1.schema.json`: confined import format for reusable graph
  modules.
- `workflow-editor-sidecar.v1.schema.json`: canvas-only node and graph-output
  positions, groups, notes, saved selections, and viewport state stored
  separately from executable graphs.

Contracts should remain language-neutral. Provider-specific behavior belongs in
plugin code and docs, not in the schemas.

Canonical cross-runtime examples live under `fixtures/`. The graph fixtures are
copied byte-for-byte into the Swift runtime and Relay/Node test suites so Python,
Swift, TypeScript, and Rust continuously agree on the same public JSON shape.

Graph providers implement fixed `graph catalog`, `graph preflight`, and
`graph execute` commands. The contracts never supply an arbitrary executable or
argument vector for the core runtime to trust.

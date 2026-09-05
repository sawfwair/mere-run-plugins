# Contracts

These schemas define the stable surfaces shared by `mere.run` and official
companion plugins.

- `plugin.v1.schema.json`: plugin self-description printed by
  `<plugin> manifest --json`.
- `catalog.v1.schema.json`: live plugin catalog consumed by `mere.run plugin`.
- `recipe.v1.schema.json`: machine-readable workflow recipes.
- `eval-recipe.v1.schema.json`: machine-readable evaluation protocols.
- `terminal-bench-recipe.v1.schema.json`: pinned Harbor, dataset, agent,
  inference, and resource defaults for Terminal-Bench comparisons.
- `terminal-bench-report.v1.schema.json`: matched per-model Terminal-Bench
  results and pairwise task outcomes.
- `run-manifest.v1.schema.json`: durable execution record written before remote
  resources are created.
- `artifact-bundle.v1.schema.json`: fetched result bundle inventory.
- `plugin-bundle.v1.schema.json`: installable signed-plugin bundle.
- `plugin-bundle-envelope.v1.schema.json`: signed publisher statement for a
  plugin bundle.
- `archive-benchmark.v1.schema.json`: archive benchmark cases, judgments, and
  change scenarios.
- `archive-benchmark-report.v1.schema.json`: archive benchmark metrics and
  evaluation results.
- `archive-investigation.v1.schema.json`: bounded investigation results, citation
  paths, unresolved claims, and optional timing and memory observations.
- `film-brief.v1.schema.json`: user-confirmed story, audience, creative, and
  delivery requirements held at the first approval gate.
- `film-department-result.v1.schema.json`: read-only Pi department proposal
  boundary.
- `film-production-plan.v1.schema.json`: accepted cast, location, sound, and
  shot plan used to derive deterministic local media jobs.
- `film-production-readiness.v1.schema.json`: source-bound model readiness for
  every media role required by the accepted plan, including runtime-managed roles.
- `film-project.v1.schema.json`: durable film phases, approvals, work, proof,
  issues, and artifact ledger.
- `film-dialogue-qc.v1.schema.json`: source-bound TTS-to-ASR intelligibility
  evidence for timed production dialogue.
- `film-sound-qc.v1.schema.json`: source-bound stream, duration, and audibility
  validation for generated, timed sound-effect cues.
- `film-media-inspection.v1.schema.json`: per-shot local vision observations and
  canon mismatch evidence bound to generated clips.
- `film-take-selection.v1.schema.json`: local vision scores, hashes, and the
  deterministic winning candidate for every multi-take shot.
- `film-captions.v1.schema.json`: source-bound SRT and WebVTT sidecars derived
  from the accepted dialogue timeline.
- `film-human-review.v1.schema.json`: explicit approval or revision evidence
  bound to the exact rough cut and automated review set.
- `film-delivery.v1.schema.json`: checksum-backed master, caption sidecars,
  poster, thumbnail, review package, and provenance handoff.
- `film-animatic-handoff.v1.schema.json`: checksum-backed editorial handoff of
  normalized cast, locations, shot timing, deterministic seeds, and verified
  local media into Animatic.
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

Contracts must remain language-neutral. Provider-specific behavior belongs in
plugin code and docs, not in the schemas.

Document Tools reuses the open `plugin-run.v1` extension fields for AnyDoc;
no shared schema change is needed. `tool.backend` is `anydoc`, `tool.workflow`
is `markdown-redact`, and `tool.redact` records whether native anonymization
follows conversion. After conversion, `tool.backendVersion` records the
installed `firecrawl-anydoc` version. The conversion step uses the existing
local Python-step shape: `python: "anydoc-markdown"`, a one-element `inputs`
array, and `outputs.markdown`. Hosted OCR is forbidden by the implementation,
not configurable through the manifest. Generated plans are schema-validated by
`scripts/validate_repo.py`; `examples/documents` shows how to create one.

The `document.convert` node uses the existing graph invocation, preflight,
catalog, and event contracts. It emits `markdown` and `manifest` assets, inline
`text`, and JSON `stats`. Its manifest uses the same local run contract; graph
conversion never enables redaction or hosted OCR. Both the invocation example
and `document-to-markdown` template are schema-validated.

Canonical cross-runtime examples live under `fixtures/`. The graph fixtures are
copied byte-for-byte into the Swift runtime and Relay/Node test suites so Python,
Swift, TypeScript, and Rust continuously agree on the same public JSON shape.

Graph providers implement fixed `graph catalog`, `graph preflight`, and
`graph execute` commands. The contracts never supply an arbitrary executable or
argument vector for the core runtime to trust.

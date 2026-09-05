# Contract schemas

The contracts are language-neutral JSON Schemas shared by the core runtime,
plugins, recipes, and downstream automation.

| Schema | Stable surface |
| --- | --- |
| [`plugin.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/plugin.v1.schema.json) | Plugin self-description from `manifest --json` |
| [`catalog.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/catalog.v1.schema.json) | Published plugin catalog |
| [`recipe.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/recipe.v1.schema.json) | Executable workflow recipe |
| [`eval-recipe.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/eval-recipe.v1.schema.json) | Evaluation protocol |
| [`terminal-bench-recipe.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/terminal-bench-recipe.v1.schema.json) | Pinned Terminal-Bench comparison recipe |
| [`terminal-bench-report.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/terminal-bench-report.v1.schema.json) | Matched Terminal-Bench results and pairwise outcomes |
| [`run-manifest.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/run-manifest.v1.schema.json) | Durable execution state |
| [`artifact-bundle.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/artifact-bundle.v1.schema.json) | Fetched result inventory |
| [`plugin-bundle.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/plugin-bundle.v1.schema.json) | Installable signed-plugin bundle |
| [`plugin-bundle-envelope.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/plugin-bundle-envelope.v1.schema.json) | Signed publisher statement for a plugin bundle |
| [`archive-benchmark.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/archive-benchmark.v1.schema.json) | Archive benchmark cases, judgments, and change scenarios |
| [`archive-benchmark-report.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/archive-benchmark-report.v1.schema.json) | Archive benchmark metrics and evaluation results |
| [`archive-investigation.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/archive-investigation.v1.schema.json) | Bounded investigation results, citation paths, unresolved claims, and optional metrics |
| [`film-brief.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-brief.v1.schema.json) | User-confirmed film requirements and greenlight readiness |
| [`film-department-result.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-department-result.v1.schema.json) | Structured proposal returned by a read-only Pi department |
| [`film-production-plan.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-production-plan.v1.schema.json) | Accepted cast, location, sound, and shot plan |
| [`film-production-readiness.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-production-readiness.v1.schema.json) | Model readiness bound to the accepted plan, including runtime-managed roles |
| [`film-project.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-project.v1.schema.json) | Durable film phases, approvals, work, proof, and artifact ledger |
| [`film-dialogue-qc.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-dialogue-qc.v1.schema.json) | Source-bound dialogue synthesis and transcription evidence |
| [`film-sound-qc.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-sound-qc.v1.schema.json) | Source-bound generated sound-effect stream, duration, and audibility evidence |
| [`film-media-inspection.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-media-inspection.v1.schema.json) | Per-shot local generated-media inspection evidence |
| [`film-take-selection.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-take-selection.v1.schema.json) | Evidence-backed selection across deterministic local shot candidates |
| [`film-captions.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-captions.v1.schema.json) | Source-bound SRT and WebVTT dialogue captions |
| [`film-human-review.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-human-review.v1.schema.json) | Explicit decision bound to an exact cut and review evidence set |
| [`film-delivery.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-delivery.v1.schema.json) | Checksum-backed master, captions, marketing stills, review package, and provenance handoff |
| [`film-animatic-handoff.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/film-animatic-handoff.v1.schema.json) | Verified cast, locations, shot timing, deterministic seeds, and media for native Animatic import |
| [`workflow-graph.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/workflow-graph.v1.schema.json) | Portable executable graph |
| [`graph-node-provider.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/graph-node-provider.v1.schema.json) | Typed provider node catalog |
| [`graph-node-invocation.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/graph-node-invocation.v1.schema.json) | Confined graph-node request |
| [`graph-node-preflight.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/graph-node-preflight.v1.schema.json) | Structured node readiness report |
| [`graph-node-event.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/graph-node-event.v1.schema.json) | Streamed node progress, artifact, diagnostic, metric, and result events |
| [`graph-run.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/graph-run.v1.schema.json) | Portable graph execution record |
| [`graph-template-catalog.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/graph-template-catalog.v1.schema.json) | Discoverable reusable graph templates |
| [`graph-template-package.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/graph-template-package.v1.schema.json) | Confined user-published graph template |
| [`workflow-program.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/workflow-program.v1.schema.json) | Reusable composition and static expansion source |
| [`workflow-module.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/workflow-module.v1.schema.json) | Reusable imported graph module |
| [`workflow-editor-sidecar.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/workflow-editor-sidecar.v1.schema.json) | Non-executable canvas state |

For information about installable code, publisher verification, and activation,
see [Signed plugin bundles](/reference/plugin-bundles).

## Versioning

Contract identifiers carry an explicit version such as
`mere.run/plugin-catalog.v1`. Additive implementation changes can remain within
the version only when existing valid documents and consumers keep their meaning.
Breaking shape or semantic changes require another contract version.

## Change rule

If a plugin needs an additional contract field, update all affected surfaces together:

- schema;
- plugin implementation;
- catalog or recipe examples;
- docs;
- validation and unit tests.

Provider-specific behavior belongs in plugin code and documentation, not in a
shared schema unless multiple consumers genuinely need the field.

## Validation

`./scripts/check.sh` validates contracts, catalog entries, recipes, examples,
and installed plugin smoke surfaces. See [Testing](/operations/testing).

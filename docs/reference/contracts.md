# Contract schemas

The contracts are language-neutral JSON Schemas shared by the core runtime,
plugins, recipes, and downstream automation.

| Schema | Stable surface |
| --- | --- |
| [`plugin.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/plugin.v1.schema.json) | Plugin self-description from `manifest --json` |
| [`catalog.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/catalog.v1.schema.json) | Published plugin catalog |
| [`recipe.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/recipe.v1.schema.json) | Executable workflow recipe |
| [`eval-recipe.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/eval-recipe.v1.schema.json) | Evaluation protocol |
| [`run-manifest.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/run-manifest.v1.schema.json) | Durable execution state |
| [`artifact-bundle.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/artifact-bundle.v1.schema.json) | Fetched result inventory |
| [`workflow-graph.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/workflow-graph.v1.schema.json) | Portable executable graph |
| [`graph-node-provider.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/graph-node-provider.v1.schema.json) | Typed provider node catalog |
| [`workflow-program.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/workflow-program.v1.schema.json) | Reusable composition and static expansion source |
| [`workflow-module.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/workflow-module.v1.schema.json) | Reusable imported graph module |
| [`workflow-editor-sidecar.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/workflow-editor-sidecar.v1.schema.json) | Non-executable canvas state |

## Versioning

Contract identifiers carry an explicit version such as
`mere.run/plugin-catalog.v1`. Additive implementation changes can remain within
the version only when existing valid documents and consumers keep their meaning.
Breaking shape or semantic changes require a new contract version.

## Change rule

If a plugin needs a new contract field, update all affected surfaces together:

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

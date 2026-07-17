# Documentation coverage

This site covers every public product surface in the repository.

| Surface | Source of truth | Documentation |
| --- | --- | --- |
| 12 catalog entries | `catalog/plugins.v1.json` | [Plugin catalog](/plugins/) and one page per entry |
| Plugin discovery and lifecycle | `contracts/plugin.v1.schema.json` | [Plugin contract](/plugins/contract), [CLI lifecycle](/reference/cli) |
| Durable runs | `contracts/run-manifest.v1.schema.json` | [Run manifest](/reference/run-manifest), [Artifacts and runs](/guide/artifacts-and-runs) |
| Artifact fetches | `contracts/artifact-bundle.v1.schema.json` | [Contracts](/reference/contracts) |
| Catalog publication | `contracts/catalog.v1.schema.json` | [Catalog reference](/reference/catalog) |
| Workflow recipes | `contracts/recipe.v1.schema.json` | [Recipes](/reference/recipes), bundled recipe guides |
| Evaluations | `contracts/eval-recipe.v1.schema.json` | [Klein reference evaluations](/recipes/klein-reference-evals) |
| Provider safety | implementations and repository rules | [Provider safety](/operations/provider-safety) |
| Repository validation | `scripts/check.sh` | [Testing](/operations/testing) |
| Docs hosting | `site/wrangler.docs.jsonc` | [Releasing](/operations/releasing) |

`pnpm docs:coverage` verifies that each live catalog ID maps to a dedicated page
and that every contract schema is represented in this reference.

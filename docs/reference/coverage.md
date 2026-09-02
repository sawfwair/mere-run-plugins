# Documentation coverage

This site covers every public product surface in the repository.

| Surface | Source of truth | Documentation |
| --- | --- | --- |
| 18 catalog entries | `catalog/plugins.v1.json` | [Plugin catalog](/plugins/) and one page per entry |
| Plugin discovery and lifecycle | `contracts/plugin.v1.schema.json` | [Plugin contract](/plugins/contract), [CLI lifecycle](/reference/cli) |
| Durable runs | `contracts/run-manifest.v1.schema.json` | [Run manifest](/reference/run-manifest), [Artifacts and runs](/guide/artifacts-and-runs) |
| Artifact fetches | `contracts/artifact-bundle.v1.schema.json` | [Contracts](/reference/contracts) |
| Catalog publication | `contracts/catalog.v1.schema.json` | [Catalog reference](/reference/catalog) |
| Workflow recipes | `contracts/recipe.v1.schema.json` | [Recipes](/reference/recipes), bundled recipe guides |
| Evaluations | `contracts/eval-recipe.v1.schema.json` | [Klein reference evaluations](/recipes/klein-reference-evals) |
| Terminal-Bench evaluation | `contracts/terminal-bench-*.schema.json` | [Terminal-Bench plugin](/plugins/terminal-bench) |
| Film production and evidence | `contracts/film-*.schema.json` | [Film Studio](/plugins/film-tools), [Contracts](/reference/contracts) |
| Provider safety | implementations and repository rules | [Provider safety](/operations/provider-safety) |
| Documentation conventions | project rules and Google developer documentation style | [Documentation style](/operations/documentation-style) |
| Repository validation | `scripts/check.sh` | [Testing](/operations/testing) |
| Docs build and release handoff | `package.json`, `docs/.vitepress/dist/` | [Releasing](/operations/releasing) |

`pnpm docs:coverage` verifies that each live catalog ID maps to a dedicated page
and that every contract schema is represented in this reference.

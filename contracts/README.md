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

Contracts should remain language-neutral. Provider-specific behavior belongs in
plugin code and docs, not in the schemas.

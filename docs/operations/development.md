# Development

## Repository layout

```text
catalog/       published plugin index
contracts/     language-neutral JSON Schemas
docs/          VitePress source and product documentation
packages/      plugin Python packages
recipes/       executable and evaluation recipes
scripts/       repository validation and maintenance
site/          marketing and docs Workers
```

## Local Python workflow

Create changes inside the relevant package and update its tests. Keep stdout
machine-readable wherever the command promises JSON; write diagnostics to
stderr.

If a new contract field is needed, update contracts, examples, documentation,
and tests in the same change.

## Local docs workflow

```bash
corepack pnpm install
corepack pnpm docs:dev
```

The docs use VitePress with the shared Mere docs theme and a plugin-specific
copper identity. The canonical host is `plugins-docs.mere.run`.

## Catalog changes

Every catalog plugin must have a dedicated page under `docs/plugins/`. Update
`site/scripts/check-docs-coverage.mjs` only when adding a genuinely new catalog
ID and page mapping.

## Before review

Run both product gates:

```bash
./scripts/check.sh
corepack pnpm --dir site check
```

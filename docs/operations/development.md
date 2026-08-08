# Development

## Repository layout

```text
catalog/       published plugin index
contracts/     language-neutral JSON Schemas
docs/          VitePress source and product documentation
packages/      plugin Python packages
recipes/       executable and evaluation recipes
scripts/       repository validation and maintenance
package.json   root VitePress development and build commands
```

## Local Python workflow

Create changes inside the relevant package and update its tests. Keep stdout
machine-readable wherever the command promises JSON; write diagnostics to
stderr.

If a new contract field is needed, update contracts, examples, documentation,
and tests in the same change.

## Local docs workflow

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm docs:dev
```

The docs use VitePress with the shared Mere docs theme and a plugin-specific
copper identity. The canonical host is `plugins-docs.mere.run`.

## Catalog changes

Every catalog plugin must have a dedicated page under `docs/plugins/`.
`scripts/check-docs-coverage.mjs` verifies that every live catalog ID is named
by at least one plugin page.

## Before review

Run the fast gate while iterating, then both release gates before review:

```bash
./scripts/check-fast.sh
./scripts/check.sh
corepack pnpm docs:coverage
corepack pnpm docs:build
```

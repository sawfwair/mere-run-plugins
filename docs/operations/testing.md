# Testing

## Repository gate

For a sub-ten-second local/pre-commit pass with the current development
dependencies installed, run:

```bash
./scripts/check-fast.sh
```

It runs Ruff, strict mypy, compilation, repository validation, and all package
unit suites in parallel. Before review or release, run the reproducible gate:

Run:

```bash
./scripts/check.sh
```

The gate:

- creates an isolated Python environment;
- runs Ruff and mypy;
- rejects dynamic `Any` in production boundaries;
- compiles every plugin package;
- runs package unit tests with coverage reporting;
- validates repository structure, JSON contracts, catalog, and recipes;
- installs every package;
- smoke-tests manifests and planned workflows from installed executables.

## Docs gate

Run:

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm docs:coverage
corepack pnpm docs:build
```

This checks catalog documentation coverage and builds VitePress with dead-link
enforcement. Hosting and the visual catalog deploy from their owning systems,
not this repository.

## Focused docs commands

```bash
corepack pnpm docs:coverage
corepack pnpm docs:build
corepack pnpm docs:preview
```

## Production proof

A successful local build proves the documentation artifact, not DNS or live
routing. Deployment verification belongs to the docs-hosting owner.

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

On Python 3.10+, the normal package installation must include AnyDoc without
extras. The gate performs real CSV, RTF, and DOCX conversions with artifact-hash
checks, then tests document graph catalog/preflight/execution conformance. A scanned-PDF
case verifies that hosted OCR remains disabled. Python 3.9 runs the base
package and mocked boundary tests without installing AnyDoc.

## Model benchmark

To evaluate tool selection, arguments, clarification, and bounded fixture
outcomes with local inference, follow the
[ATE benchmark guide](/guide/ate-benchmark). It covers all 240 cases, an
eight-case smoke run, checkpoint resume, and the first model baseline. The
repository's fixture tests validate the scorer and expected decisions; they do
not run model inference or qualify a model for release.

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

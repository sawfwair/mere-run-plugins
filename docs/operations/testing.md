# Testing

## Repository gate

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

## Docs and Worker gate

Run:

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm --dir site install --frozen-lockfile
corepack pnpm --dir site check
```

This syncs the public catalog, checks one-page-per-plugin documentation coverage,
builds VitePress with dead-link enforcement, and dry-runs both Cloudflare Worker
deployments.

## Focused docs commands

```bash
corepack pnpm --dir site docs:coverage
corepack pnpm --dir site docs:build
corepack pnpm --dir site docs:worker:dry-run
```

## Production proof

A dry-run validates the bundle and configuration but does not prove DNS or live
routing. After deployment, verify the docs root, a clean nested URL, search
assets, and the `Content-Signal` response header on the public host.

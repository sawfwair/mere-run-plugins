# Releasing and deployment

Plugin packages, the visual catalog, and the docs host are related but separate
release surfaces. This repository builds and validates package/catalog/docs
artifacts; it does not contain a deployment command.

## Validate

```bash
./scripts/check.sh
corepack pnpm install --frozen-lockfile
corepack pnpm docs:coverage
corepack pnpm docs:build
```

## Handoff artifacts

- Python package sources live under `packages/` and are installed by the full
  gate before release.
- The canonical catalog artifact is `catalog/plugins.v1.json`.
- The VitePress build artifact is `docs/.vitepress/dist/`.

Publish or deploy each artifact through its separately owned release system.
Do not infer a deployment from a successful local build.

## Post-deploy verification

```bash
curl -sS -I https://plugins-docs.mere.run/
curl -sS -I https://plugins-docs.mere.run/plugins/vfx-tools
curl -sS -H 'Accept: text/markdown' https://plugins-docs.mere.run/
curl -sS https://plugins.mere.run/catalog/plugins.v1.json
```

Confirm status `200`, expected HTML assets, and the catalog contract version.
Only require hosting-specific headers or content negotiation when the owning
deployment contract guarantees them.

## Release discipline

Do not publish a catalog entry before its package, manifest, docs, and installed
smoke path are valid. Do not describe provider behavior as safe until plan,
resume, and cleanup paths are tested.

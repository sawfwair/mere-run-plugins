# Releasing and deployment

Plugin packages, the marketing catalog, and the docs host are related but
separate release surfaces.

## Validate

```bash
./scripts/check.sh
corepack pnpm install --frozen-lockfile
corepack pnpm --dir site install --frozen-lockfile
corepack pnpm --dir site check
```

## Deploy the marketing site

```bash
corepack pnpm --dir site deploy
```

This syncs the validated catalog and deploys `plugins.mere.run`.

## Deploy the docs site

```bash
corepack pnpm --dir site docs:deploy
```

This builds VitePress and deploys the public Worker route at
`plugins-docs.mere.run`.

## Post-deploy verification

```bash
curl -sS -I https://plugins-docs.mere.run/
curl -sS -I https://plugins-docs.mere.run/plugins/vfx-tools
curl -sS -H 'Accept: text/markdown' https://plugins-docs.mere.run/
curl -sS https://plugins.mere.run/catalog/plugins.v1.json
```

Confirm status `200`, `Content-Signal`, HTML assets, Markdown negotiation on the
docs root, and the expected catalog contract version.

## Release discipline

Do not publish a catalog entry before its package, manifest, docs, and installed
smoke path are valid. Do not describe provider behavior as safe until plan,
resume, and cleanup paths are tested.

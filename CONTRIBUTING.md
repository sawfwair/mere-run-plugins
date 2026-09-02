# Contributing

This guide is for contributors who change plugin code, contracts, recipes, or
documentation.

Before you open a pull request, run:

```bash
./scripts/check.sh
```

Keep provider plugins explicit and auditable. A plugin that creates paid or
remote resources must include:

- a manifest command
- a doctor command
- a plan command
- a durable run manifest
- cleanup by default
- tests for the non-network planning path

Do not commit secrets, real account tokens, or large training artifacts.

For developer-facing prose, follow the [documentation style
guide](https://plugins-docs.mere.run/operations/documentation-style).

For a security-sensitive issue, follow the private reporting process in
[`SECURITY.md`](SECURITY.md) instead of opening a public issue.

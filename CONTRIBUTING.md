# Contributing

Before opening a PR:

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

For security-sensitive issues, follow `SECURITY.md` instead of opening a public
issue.

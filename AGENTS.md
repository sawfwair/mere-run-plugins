# AGENTS.md

Guidance for AI coding agents working in this repo.

## Repo Scope

`mere-plugins` contains official companion plugin contracts and plugins for
`mere.run`. Plugins may coordinate user-controlled external resources such as
RunPod pods or SSH-accessed GPU hosts, but they must not turn the core
`mere.run` CLI into a hosted service.

The core `mere-run` repo owns local inference and canonical model behavior. This
repo owns the companion plugin contract package and provider-specific automation
against those contracts. If the core CLI later adds plugin discovery, it should
consume these contracts rather than duplicate them.

## Validation

Run the repo gate before opening a PR:

```bash
./scripts/check.sh
```

The gate compiles the Python plugins, runs unit tests, validates JSON contracts
and recipes, and smoke-tests the `mere-runpod` manifest and dry-run planning
surface.

## Editing Rules

- Do not commit secrets, API keys, pod IDs tied to private accounts, or local
  artifact bundles.
- Keep stdout machine-readable for plugin commands that produce JSON. Write
  human diagnostics to stderr.
- Provider plugins must support `doctor`, `plan`, `run`, `resume`, and
  `cleanup`.
- Provider plugins must write a durable `run.json` manifest before creating a
  remote resource and update it after cleanup.
- Any command that creates paid resources must have a dry-run or plan mode.
- Remote providers must default to cleanup/termination unless the user passes an
  explicit keep/debug flag.
- If a plugin needs a new contract field, update `contracts/`, docs, examples,
  and tests in the same change.

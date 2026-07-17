# Troubleshooting

## Plugin command not found

Confirm installation and shell path:

```bash
mere.run plugin list
mere.run plugin install mere-image-tools
command -v mere-image-tools
```

If the executable was installed by `pipx`, ensure the pipx binary directory is
on `PATH`.

## `doctor` fails

Read stderr and the structured result. Fix the missing core executable,
credential, provider tool, SSH key, or writable directory before running.

## Core executable is in a source checkout

Use the plugin's `--mere-run-command` option or documented environment override.
Verify the effective command is the intended build.

## A run was interrupted

Do not delete `run.json`. Use:

```bash
<plugin> resume ./out/run.json
```

For provider runs, inspect the resource identity and invoke cleanup against the
same manifest.

## JSON parsing fails

Parse stdout only. Diagnostics and child-process logs belong on stderr. If a
plugin writes human logs to stdout during a JSON command, treat it as a plugin
contract bug.

## Cleanup failed

Exit code `5` means the provider resource may still exist. Verify it in the
provider account, retry idempotent cleanup, and preserve the real manifest state.

## VitePress reports a dead link

The docs build deliberately fails on dead internal links. Fix the destination or
the source link; do not add it to an ignore list unless the target is genuinely
external and unresolvable at build time.

## Docs Worker dry-run fails

Run `corepack pnpm --dir site docs:build` first, then check
`site/wrangler.docs.jsonc` and the generated `docs/.vitepress/dist` directory.

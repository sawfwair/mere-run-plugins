# Environment and executable overrides

Plugins use environment variables for credentials and non-standard executable
locations. Do not put secret values in commands, manifests, examples, or logs.

## Core executable overrides

| Plugin family | Environment variable |
| --- | --- |
| Image Tools | `MERE_IMAGE_TOOLS_MERE_RUN` |
| Workflow Tools package | `MERE_WORKFLOW_TOOLS_MERE_RUN` |

The same tools accept `--mere-run-command` for development checkouts or unusual
install paths. Other plugins document their own equivalent flag in their plugin
page and `--help` output.

## RunPod

RunPod Runner requires provider credentials, SSH access material, and a usable
local toolchain for its selected provider path. Use `mere-runpod doctor` to see
what the installed version expects. Keep API keys in the environment or a
supported secret store, never in recipe JSON or `run.json`.

## ShotGrid

ShotGrid Tools expects the site URL, script name, and script key through its
documented environment configuration. Treat the script key as a secret and use
a least-privilege integration account.

## Output paths

Plugins need write access to their output directory. Prefer a dedicated run
directory per workflow so manifests and artifacts do not overwrite one another.

## Debugging overrides

Executable overrides are useful for source checkouts, but they change the binary
that owns canonical inference. Record the effective command and avoid treating a
development override as production proof.

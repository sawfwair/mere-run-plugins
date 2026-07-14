# Run manifest

The `mere.run/plugin-run.v1` manifest is the durable state record for a plugin
workflow. Its authoritative shape is
[`contracts/run-manifest.v1.schema.json`](https://github.com/sawfwair/mere-run-plugins/blob/main/contracts/run-manifest.v1.schema.json).

## Lifecycle states

A run begins as `planned`, moves through execution, and finishes in a success or
failure state. Cleanup status is recorded separately because a failed workflow
can still clean up successfully—and a successful provider workflow can still
need cleanup attention.

## Identity and timing

The manifest records a validated run ID, contract version, timestamps, plugin
identity, and recipe identity. Run IDs begin with a letter or digit and contain
only letters, digits, `.`, `_`, or `-`.

## Local execution

The local section records input paths, output paths, resolved commands, and
workflow-specific controls needed to understand or reproduce the run.

## Provider state

Provider plugins record requested settings and the created resource identity.
That identity must be persisted immediately after resource creation so cleanup
can recover after interruption.

## Steps

Ordered steps capture the plan and execution status. Plugins update these as the
workflow progresses rather than relying on ephemeral terminal logs.

## Artifacts

Artifact items describe outputs such as images, masks, media, JSON, models, or
reports. Successful local artifacts are hashed; remote artifact fetches can also
produce an [`artifact-bundle.v1`](/reference/contracts) inventory.

## Cleanup

Local-only plugins record a no-op or skipped remote cleanup. Provider plugins
record termination attempts and results. `cleanup` must be safe to invoke more
than once against the same manifest.

## Operational rule

Never hand-edit a provider resource ID out of a manifest to make a run appear
clean. Preserve the real state, invoke cleanup, and keep any failure details for
operator follow-up.

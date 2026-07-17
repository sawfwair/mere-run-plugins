# Core concepts

## Companion executable

A plugin is an executable such as `mere-vfx-tools`, not a shared library loaded
into `mere.run`. This keeps failure, dependencies, permissions, and upgrades at
an explicit process boundary.

## Catalog entry

The [catalog](/reference/catalog) maps a stable plugin ID to its package,
entrypoint, capabilities, source repository, and install channel.

## Manifest

`<plugin> manifest --json` describes a plugin. It is validated against the
[`plugin.v1` contract](/reference/contracts) and is safe for discovery to call.

## Plan

A plan resolves the requested workflow without beginning paid or destructive
work. It becomes a durable `run.json` with status `planned`.

## Run

A run executes the planned steps and updates the same manifest as state changes.
The manifest is written before any remote mutation.

## Artifact

An artifact is an output with a path, kind, content type, label, and—after
successful production—an integrity hash. Plugins may produce media, JSON,
reports, logs, masks, models, or artifact bundles.

## Cleanup

Cleanup is a lifecycle operation, not an afterthought. Local plugins record that
no remote cleanup is needed. Provider plugins terminate resources by default
and record the result. Cleanup must be safe to repeat.

## Recipe

A recipe is a language-neutral workflow definition. It describes inputs,
commands, provider expectations, output patterns, and safety defaults. See
[Recipes](/reference/recipes).

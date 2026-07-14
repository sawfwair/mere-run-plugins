# Introduction

The official `mere.run` plugins turn local model commands into repeatable
production workflows. They are normal companion executables discovered through
the live plugin catalog; they are not dynamically loaded into the core process.

## What plugins add

Plugins cover the work around inference:

- validate tools, inputs, credentials, and output locations;
- write an inspectable plan before execution;
- call the installed `mere.run` runtime for canonical model behavior;
- coordinate local tools or user-controlled providers;
- record artifacts, hashes, status, and cleanup in `run.json`;
- expose JSON-friendly command surfaces for agents and pipelines.

## What stays in core

Model discovery, download, loading, and native inference remain in `mere.run`.
A plugin may select and compose core commands, but it must not ship a parallel
model runtime or turn the core CLI into a hosted service.

## The product surface

The catalog currently contains 12 official commands across five outcomes:

| Outcome | Plugins |
| --- | --- |
| Create | VFX Tools, Image Tools, Image Compose |
| Perform | Perform |
| Produce | Animatic Tools, ShotGrid Tools, Dataset Tools |
| Protect | Document Tools, Media Scrub, Transcript Tools |
| Scale | RunPod Runner, Batch Runner |

See [Choose a plugin](/guide/choosing-a-plugin) for task-based routing or
[All plugins](/plugins/) for the complete catalog.

## Design promises

- Local workflows remain local.
- Provider resources remain in the user's account.
- Paid work is visible in a plan before it starts.
- Remote resources terminate by default.
- JSON output stays on stdout; diagnostics go to stderr.
- A durable run manifest connects inputs, execution, artifacts, and cleanup.

Next: [install and run a first plugin](/guide/getting-started).

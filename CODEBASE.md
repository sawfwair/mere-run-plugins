# CODEBASE.md

`mere-run-plugins` is the public companion-plugin repo for `mere.run`. The core
CLI owns local inference; this repo owns schemas, catalog entries, recipes, and
standalone plugin executables that wrap user-controlled external systems.

Key paths:

- `contracts/`: JSON schemas for plugin manifests, catalogs, recipes, run
  manifests, and artifact bundles.
- `catalog/plugins.v1.json`: public install catalog.
- `packages/mere-runpod/`: RunPod remote runner. Paid-resource paths must plan
  first and clean up by default.
- `packages/mere-image-tools/`: local image helpers around existing `mere.run`
  vision commands.
- `packages/mere-workflow-tools/`: document, media, dataset, transcript, image,
  and batch workflow CLIs.
- `packages/mere-animatic-tools/`: local Animatic production helpers.
- `packages/mere-shotgrid-tools/`: ShotGrid / Flow Production Tracking publish
  and task-pull bridge.
- `scripts/check.sh`: required readiness gate.

Do not turn plugins into hosted services, add live network tests to the default
gate, write secrets into manifests/stdout, or change contract fields without
updating schemas, docs, examples, and tests.

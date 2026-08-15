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
- `packages/mere-face-tools/`: local face-library indexing, search, and review
  exports.
- `packages/mere-workflow-tools/`: document, media, dataset, transcript, image,
  and batch workflow CLIs.
- `packages/mere-geo-tools/`: typed STAC preparation, portable Geo graph nodes,
  and native `mere.run` hazard/embedding handoffs. It consumes graph contracts
  from `mere-workflow-tools`; the reverse dependency is forbidden.
- `packages/mere-animatic-tools/`: local Animatic production helpers.
- `packages/mere-film-tools/`: Pi film-studio harness, governed creative state,
  local media execution, review, rerolls, and delivery proof.
- `packages/mere-shotgrid-tools/`: ShotGrid / Flow Production Tracking publish
  and task-pull bridge.
- `packages/mere-perform/`: local realtime performance plans and stage UI.
- `packages/mere-vfx-tools/`: local shot-oriented VFX workflows.
- `scripts/check-fast.sh`: sub-ten-second developer/pre-commit gate.
- `scripts/check.sh`: clean-environment release and CI gate.

Do not turn plugins into hosted services, add live network tests to the default
gate, write secrets into manifests/stdout, or change contract fields without
updating schemas, docs, examples, and tests.

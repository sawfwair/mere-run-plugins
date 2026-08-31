# Workflow Tools bundle inputs

For release maintainers building the macOS Apple Silicon Document Tools pilot.
The private release tools own build, signing, notarization, and publication.
This directory contains public, reviewable inputs, not release credentials.

- `recipe.json`: pinned standalone CPython archive and SHA-256, minimum macOS
  version, and the seven plugin entrypoints that share one runtime.
- `requirements.lock`: exact runtime dependencies and accepted wheel hashes.
- `build-constraints.txt`: package build dependency version.
- `builder-requirements.lock`: hashed PyInstaller build dependencies.
- `frozen_entrypoint.py`: restricted dispatch inside the frozen Python runtime.
- `launcher.c`: native launcher that finds the frozen runtime relative to its installed
  location. The frozen runtime ignores user Python configuration and prevents bytecode writes.
- `anydoc-native-inventory.json` and `anydoc-native-notices.txt`: the upstream
  Cargo dependency inventory and preserved license texts, including build dependencies.
- `BUNDLE_NOTICES.txt`: binary-distribution acknowledgments and notice locations.

Regenerate the runtime lock with uv and review the dependency changes:

```bash
uv pip compile --python-version 3.12 --python-platform aarch64-apple-darwin \
  --generate-hashes packages/mere-workflow-tools/pyproject.toml \
  -o bundles/workflow-tools/requirements.lock
```

An installed bundle does not need uv, pipx, Homebrew, or a system Python.
Do not put model weights, local artifacts, or signing keys in this directory.
See [the bundle contract](../../docs/reference/plugin-bundles.md).

## Refresh native dependency notices

Use a clean checkout of the exact AnyDoc release source. Generate Cargo metadata
with `cargo metadata --locked --filter-platform aarch64-apple-darwin
--format-version 1 --manifest-path python/Cargo.toml`. Pass that JSON file to
`scripts/update_anydoc_bundle_notices.py` with `--source`, `--metadata`,
`--missing-notices`, and `--output bundles/workflow-tools`.

For a crate that omits license texts, place the original upstream files in
`MISSING_NOTICES/NAME-VERSION/`. Include a `source.json` file with `repository`,
`commit`, and `files` fields. The commit must match the published crate's
`.cargo_vcs_info.json`. The inventory records that supplemental source.
AnyDoc 0.2.4 requires this for `defmt-parser` 1.0.0; its notices come from
the upstream commit recorded in the inventory. The repository gate checks
the dependency version and combined notice-file hash.

The inventory is a conservative Cargo dependency set, not an attestation of
the contents of an upstream wheel. Keep the wheel hashes pinned separately.

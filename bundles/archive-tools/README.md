# Archive Tools bundle inputs

These are the reviewed public inputs for building the macOS Apple Silicon
Archive Tools plugin bundle. Private release infrastructure owns building,
signing, notarization, and publication; release credentials do not belong in
this repository.

- `recipe.json` pins standalone CPython, the package, and the sole entrypoint.
- `requirements.lock` pins runtime dependencies and accepted artifact hashes.
- `builder-requirements.lock` pins the PyInstaller build environment.
- `frozen_entrypoint.py` restricts dispatch to the reviewed Archive Tools CLI.
- `launcher.c` finds the frozen runtime relative to the installed app.
- `anydoc-native-inventory.json` and `anydoc-native-notices.txt` preserve the
  reviewed AnyDoc Cargo dependency inventory and license texts.
- `BUNDLE_NOTICES.txt` explains where binary-distribution notices are kept.

Regenerate and review the runtime lock with:

```bash
uv --no-config pip compile \
  --python-version 3.12 \
  --python-platform aarch64-apple-darwin \
  --generate-hashes \
  packages/mere-archive-tools/pyproject.toml \
  -o bundles/archive-tools/requirements.lock
```

An installed bundle doesn't need uv, pipx, Homebrew, or a system Python. Do not
put model weights, local indexes, source-drive content, credentials, or signing
keys in this directory.

See [the bundle contract](../../docs/reference/plugin-bundles.md).

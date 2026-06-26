#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CHECK_TMP="$(mktemp -d "${TMPDIR:-/tmp}/mere-plugins-check.XXXXXX")"
trap 'rm -rf "$CHECK_TMP"' EXIT

python3 -m venv "$CHECK_TMP/venv"
PYTHON="$CHECK_TMP/venv/bin/python"

"$PYTHON" -m pip install -q --disable-pip-version-check --upgrade pip
"$PYTHON" -m pip install -q --disable-pip-version-check -r requirements-dev.txt

export PYTHONPATH="$ROOT/packages/mere-runpod/src"

"$PYTHON" -m compileall -q packages/mere-runpod/src scripts
"$PYTHON" -m unittest discover -s packages/mere-runpod/tests
"$PYTHON" scripts/validate_repo.py

unset PYTHONPATH
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-runpod
"$PYTHON" - <<'PY'
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(tempfile.mkdtemp(prefix="mere-runpod-installed-smoke."))
cli = pathlib.Path(sys.executable).with_name("mere-runpod")
dataset = root / "dataset"
output = root / "run"
dataset.mkdir()
for index in range(1, 17):
    stem = f"{index:03d}"
    (dataset / f"{stem}.png").write_bytes(b"fake")
    (dataset / f"{stem}.txt").write_text("stylemark, a test image\n")
result = subprocess.run(
    [
        str(cli),
        "plan",
        "--recipe",
        "klein-style-lora",
        "--data",
        str(dataset),
        "--output",
        str(output),
        "--run-id",
        "installed-smoke",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"runId": "installed-smoke"' not in result.stdout:
    raise SystemExit("installed smoke did not produce expected run manifest")
PY

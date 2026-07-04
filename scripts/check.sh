#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CHECK_TMP="$(mktemp -d "${TMPDIR:-/tmp}/mere-run-plugins-check.XXXXXX")"
trap 'rm -rf "$CHECK_TMP"' EXIT

python3 -m venv "$CHECK_TMP/venv"
PYTHON="$CHECK_TMP/venv/bin/python"

"$PYTHON" -m pip install -q --disable-pip-version-check --upgrade pip
"$PYTHON" -m pip install -q --disable-pip-version-check -r requirements-dev.txt

export PYTHONPATH="$ROOT/packages/mere-runpod/src:$ROOT/packages/mere-image-tools/src:$ROOT/packages/mere-workflow-tools/src"

"$PYTHON" -m compileall -q packages/mere-runpod/src packages/mere-image-tools/src packages/mere-workflow-tools/src scripts
"$PYTHON" -m unittest discover -s packages/mere-runpod/tests
"$PYTHON" -m unittest discover -s packages/mere-image-tools/tests
"$PYTHON" -m unittest discover -s packages/mere-workflow-tools/tests
"$PYTHON" scripts/validate_repo.py

unset PYTHONPATH
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-runpod
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-image-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-workflow-tools
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

image_cli = pathlib.Path(sys.executable).with_name("mere-image-tools")
source = root / "frame.png"
subject = root / "subject.png"
source.write_bytes(b"fake")
result = subprocess.run(
    [
        str(image_cli),
        "plan",
        "--input",
        str(source),
        "--output",
        str(subject),
        "--run-id",
        "installed-image-smoke",
        "--mere-run-command",
        "fake-mere-run",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"runId": "installed-image-smoke"' not in result.stdout:
    raise SystemExit("installed image-tools smoke did not produce expected run manifest")

for executable in [
    "mere-doc-tools",
    "mere-media-scrub",
    "mere-dataset-tools",
    "mere-transcript-tools",
    "mere-image-compose",
    "mere-batch-runner",
]:
    cli = pathlib.Path(sys.executable).with_name(executable)
    result = subprocess.run(
        [str(cli), "manifest", "--json"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    if f'"executable": "{executable}"' not in result.stdout:
        raise SystemExit(f"installed workflow smoke did not report {executable}")
PY

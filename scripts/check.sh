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

export PYTHONPATH="$ROOT/packages/mere-runpod/src:$ROOT/packages/mere-image-tools/src:$ROOT/packages/mere-face-tools/src:$ROOT/packages/mere-workflow-tools/src:$ROOT/packages/mere-animatic-tools/src:$ROOT/packages/mere-shotgrid-tools/src:$ROOT/packages/mere-perform/src:$ROOT/packages/mere-vfx-tools/src"

"$PYTHON" -m ruff check .
"$PYTHON" -m mypy
if rg -n "\bAny\b" packages/*/src scripts; then
  echo "Production code must not use the dynamic top type; define typed JSON/provider boundaries instead." >&2
  exit 1
fi
"$PYTHON" -m compileall -q packages/mere-runpod/src packages/mere-image-tools/src packages/mere-face-tools/src packages/mere-workflow-tools/src packages/mere-animatic-tools/src packages/mere-shotgrid-tools/src packages/mere-perform/src packages/mere-vfx-tools/src scripts
"$PYTHON" -m coverage erase
"$PYTHON" -m coverage run -m unittest discover -s packages/mere-runpod/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-image-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-face-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-workflow-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-animatic-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-shotgrid-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-perform/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-vfx-tools/tests
"$PYTHON" -m coverage report
"$PYTHON" scripts/check_structure.py
"$PYTHON" scripts/validate_repo.py

unset PYTHONPATH
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-runpod
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-image-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-face-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-workflow-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-animatic-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-shotgrid-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-perform
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-vfx-tools
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

face_cli = pathlib.Path(sys.executable).with_name("mere-face-tools")
face_photos = root / "face-photos"
face_photos.mkdir()
(face_photos / "face.jpg").write_bytes(b"fake")
result = subprocess.run(
    [
        str(face_cli),
        "plan",
        "--photos",
        str(face_photos),
        "--database",
        str(root / "faces.sqlite3"),
        "--output-dir",
        str(root / "face-index"),
        "--run-id",
        "installed-face-smoke",
        "--mere-run-command",
        "fake-mere-run",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"runId": "installed-face-smoke"' not in result.stdout:
    raise SystemExit("installed face-tools smoke did not produce expected run manifest")

animatic_cli = pathlib.Path(sys.executable).with_name("mere-animatic-tools")
request = root / "animatic-request.json"
request.write_text('{"inputs":{"prompt":"installed smoke"}}')
result = subprocess.run(
    [
        str(animatic_cli),
        "plan",
        "--tool",
        "shot-kit",
        "--request-json",
        str(request),
        "--output-dir",
        str(root / "animatic"),
        "--run-id",
        "installed-animatic-smoke",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"runId": "installed-animatic-smoke"' not in result.stdout:
    raise SystemExit("installed animatic-tools smoke did not produce expected run manifest")

shotgrid_cli = pathlib.Path(sys.executable).with_name("mere-shotgrid-tools")
review = root / "review.mov"
review.write_bytes(b"fake movie")
result = subprocess.run(
    [
        str(shotgrid_cli),
        "plan",
        "--project-id",
        "123",
        "--entity-type",
        "Shot",
        "--entity-id",
        "456",
        "--artifact",
        str(review),
        "--output-dir",
        str(root / "shotgrid"),
        "--run-id",
        "installed-shotgrid-smoke",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"runId": "installed-shotgrid-smoke"' not in result.stdout:
    raise SystemExit("installed shotgrid-tools smoke did not produce expected run manifest")

perform_cli = pathlib.Path(sys.executable).with_name("mere-perform")
show = root / "show.json"
show.write_text('{"contractVersion":"mere.run/perform-show.v1","title":"installed smoke","durationSeconds":0.2,"prompts":[{"id":"pulse","text":"soft synth pulse"}],"scenes":[{"id":"one","durationSeconds":0.2,"prompt":"soft synth pulse"}]}')
result = subprocess.run(
    [
        str(perform_cli),
        "plan",
        "--show",
        str(show),
        "--output-dir",
        str(root / "perform"),
        "--run-id",
        "installed-perform-smoke",
        "--mere-run-command",
        "fake-mere-run",
        "--no-play",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"runId": "installed-perform-smoke"' not in result.stdout:
    raise SystemExit("installed perform smoke did not produce expected run manifest")

vfx_cli = pathlib.Path(sys.executable).with_name("mere-vfx-tools")
vfx_request = root / "vfx-request.json"
vfx_request.write_text('{"inputs":{"masks":"' + str(root) + '"}}')
result = subprocess.run(
    [
        str(vfx_cli),
        "plan",
        "--tool",
        "matte-refine",
        "--request-json",
        str(vfx_request),
        "--output-dir",
        str(root / "vfx"),
        "--run-id",
        "installed-vfx-smoke",
        "--mere-run-command",
        "fake-mere-run",
        "--ffmpeg-command",
        "fake-ffmpeg",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"runId": "installed-vfx-smoke"' not in result.stdout:
    raise SystemExit("installed vfx-tools smoke did not produce expected run manifest")

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

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

export PYTHONPATH="$ROOT/packages/mere-runpod/src:$ROOT/packages/mere-terminal-bench/src:$ROOT/packages/mere-image-tools/src:$ROOT/packages/mere-face-tools/src:$ROOT/packages/mere-film-tools/src:$ROOT/packages/mere-workflow-tools/src:$ROOT/packages/mere-geo-tools/src:$ROOT/packages/mere-animatic-tools/src:$ROOT/packages/mere-shotgrid-tools/src:$ROOT/packages/mere-perform/src:$ROOT/packages/mere-vfx-tools/src"

"$PYTHON" -m ruff check .
"$PYTHON" -m mypy
if rg -n "\bAny\b" packages scripts --glob '*.py'; then
  echo "Production code must not use the dynamic top type; define typed JSON/provider boundaries instead." >&2
  exit 1
fi
if rg -n 'type:\s*ignore|#\s*noqa' packages scripts --glob '*.py'; then
  echo "Narrow the boundary instead of suppressing type or lint findings." >&2
  exit 1
fi
if rg -n 'ignore_errors\s*=\s*true' pyproject.toml; then
  echo "Whole-module mypy exemptions are forbidden." >&2
  exit 1
fi
"$PYTHON" -m compileall -q packages/mere-runpod/src packages/mere-terminal-bench/src packages/mere-image-tools/src packages/mere-face-tools/src packages/mere-film-tools/src packages/mere-workflow-tools/src packages/mere-geo-tools/src packages/mere-animatic-tools/src packages/mere-shotgrid-tools/src packages/mere-perform/src packages/mere-vfx-tools/src scripts
"$PYTHON" -m coverage erase
"$PYTHON" -m coverage run -m unittest discover -s packages/mere-runpod/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-terminal-bench/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-image-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-face-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-film-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-workflow-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-geo-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-animatic-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-shotgrid-tools/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-perform/tests
"$PYTHON" -m coverage run --append -m unittest discover -s packages/mere-vfx-tools/tests
"$PYTHON" -m coverage report
"$PYTHON" scripts/check_structure.py
"$PYTHON" scripts/validate_repo.py
"$PYTHON" scripts/check_plugin_bundles.py

unset PYTHONPATH
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-runpod
if "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  "$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-terminal-bench
else
  "$PYTHON" -m pip install -q --disable-pip-version-check --no-deps --ignore-requires-python \
    ./packages/mere-terminal-bench
fi
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-image-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-face-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-film-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-workflow-tools
if "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  "$PYTHON" -m pip install -q --disable-pip-version-check --no-deps ./packages/mere-geo-tools
  "$CHECK_TMP/venv/bin/mere-geo-tools" manifest --json >/dev/null
  "$CHECK_TMP/venv/bin/mere-geo-tools" graph catalog --json >/dev/null
fi
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-animatic-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-shotgrid-tools
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-perform
"$PYTHON" -m pip install -q --disable-pip-version-check ./packages/mere-vfx-tools
"$PYTHON" - <<'PY'
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import zipfile
from importlib import resources

source_notices = pathlib.Path("packages/mere-workflow-tools/src/mere_workflow_tools/THIRD_PARTY_NOTICES.txt")
installed_notices = resources.files("mere_workflow_tools").joinpath("THIRD_PARTY_NOTICES.txt")
if not installed_notices.is_file() or installed_notices.read_bytes() != source_notices.read_bytes():
    raise SystemExit("installed workflow package omitted or changed third-party notices")
print("installed workflow package: third-party notices preserved")

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

terminal_source_notices = pathlib.Path(
    "packages/mere-terminal-bench/src/mere_terminal_bench/THIRD_PARTY_NOTICES.txt"
)
terminal_installed_notices = resources.files("mere_terminal_bench").joinpath("THIRD_PARTY_NOTICES.txt")
if (
    not terminal_installed_notices.is_file()
    or terminal_installed_notices.read_bytes() != terminal_source_notices.read_bytes()
):
    raise SystemExit("installed Terminal-Bench package omitted or changed third-party notices")

terminal_source_recipe = pathlib.Path("benchmark-recipes/terminal-bench-2-1.json")
terminal_installed_recipe = resources.files("mere_terminal_bench").joinpath(
    "recipes/terminal-bench-2-1.json"
)
if (
    not terminal_installed_recipe.is_file()
    or terminal_installed_recipe.read_bytes() != terminal_source_recipe.read_bytes()
):
    raise SystemExit("installed Terminal-Bench package omitted or changed its pinned recipe")

terminal_cli = pathlib.Path(sys.executable).with_name("mere-terminal-bench")
terminal_output = root / "terminal-bench"
result = subprocess.run(
    [
        str(terminal_cli),
        "plan",
        "--output",
        str(terminal_output),
        "--run-id",
        "installed-terminal-bench",
        "--docker-context",
        "validation-context",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
terminal_manifest = json.loads(result.stdout)
terminal_runtime = terminal_manifest["runtime"]
if terminal_manifest["runId"] != "installed-terminal-bench":
    raise SystemExit("installed Terminal-Bench smoke reported the wrong run id")
if terminal_runtime["createsDockerRuntime"] is not False:
    raise SystemExit("installed Terminal-Bench smoke attempted to create a Docker runtime")
if terminal_runtime["maximumAdditionalStorageBytes"] != 64 * 1024**3:
    raise SystemExit("installed Terminal-Bench smoke reported the wrong storage limit")

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

film_cli = pathlib.Path(sys.executable).with_name("mere-film-tools")
result = subprocess.run(
    [
        str(film_cli),
        "plan",
        "--idea",
        "A lighthouse keeper receives a signal from a vanished ship.",
        "--title",
        "The Last Signal",
        "--output-dir",
        str(root / "film"),
        "--run-id",
        "installed-film-smoke",
        "--audience",
        "science-fiction viewers",
        "--genre",
        "science-fiction drama",
        "--tone",
        "tense then hopeful",
        "--rating",
        "PG",
        "--reference",
        "restrained maritime chamber drama",
        "--usage",
        "noncommercial",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"runId": "installed-film-smoke"' not in result.stdout:
    raise SystemExit("installed film-tools smoke did not produce expected run manifest")
agent = subprocess.run(
    [
        str(film_cli),
        "agent",
        "--run-manifest",
        str(root / "film" / "run.json"),
        "--print-command",
    ],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if 'film-studio.ts' not in agent.stdout or 'MERE_FILM_RUN_MANIFEST' not in agent.stdout:
    raise SystemExit("installed film-tools smoke did not expose bundled Pi resources")

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

conformance_cli = pathlib.Path(sys.executable).with_name("mere-graph-conformance")
dataset_cli = pathlib.Path(sys.executable).with_name("mere-dataset-tools")
result = subprocess.run(
    [str(conformance_cli), "--provider", str(dataset_cli), "--json"],
    cwd=root,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    check=True,
)
if '"status": "passed"' not in result.stdout or '"dataset.prepare"' not in result.stdout:
    raise SystemExit("installed graph provider conformance smoke failed")

if sys.version_info >= (3, 10):
    from unittest.mock import patch

    from PIL import Image

    from mere_workflow_tools import anydoc_backend

    doc_cli = pathlib.Path(sys.executable).with_name("mere-doc-tools")
    subprocess.run(
        [str(doc_cli), "doctor", "--extractor", "anydoc", "--no-redact"],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    csv = root / "report.csv"
    csv.write_text("item,quantity\nNotebook,3\n", encoding="utf-8")
    rtf = root / "report.rtf"
    rtf.write_text(r"{\rtf1\ansi Notebook document.}", encoding="utf-8")
    docx = root / "report.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>'
        ))
        archive.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Notebook document.</w:t></w:r></w:p></w:body></w:document>'
        ))
    for source in (csv, rtf, docx):
        output = root / f"anydoc-{source.suffix[1:]}"
        result = subprocess.run(
            [str(doc_cli), "process", "--extractor", "anydoc", "--input", str(source),
             "--output-dir", str(output), "--no-redact", "--mere-run-command", "missing-mere-run"],
            cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        manifest = json.loads(result.stdout)
        markdown = output / "report.md"
        expected_hash = "sha256:" + hashlib.sha256(markdown.read_bytes()).hexdigest()
        if (manifest["status"] != "succeeded" or not manifest["tool"].get("backendVersion")
                or manifest["artifacts"]["sha256"].get(str(markdown.resolve())) != expected_hash
                or "Notebook" not in markdown.read_text(encoding="utf-8")):
            raise SystemExit(f"installed AnyDoc conversion failed for {source.suffix}")
    fixture = json.loads(pathlib.Path("examples/documents/convert.invocation.json").read_text())
    fixture["arguments"]["input"] = str(csv)
    invocation_path = root / "document.invocation.json"
    invocation_path.write_text(json.dumps(fixture))
    result = subprocess.run(
        [str(conformance_cli), "--provider", str(doc_cli), "--invocation", str(invocation_path),
         "--run-dir", str(root / "document-graph"), "--execute", "--json"],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    conformance = json.loads(result.stdout)
    if conformance["status"] != "passed" or not conformance["fixture"]["executed"]:
        raise SystemExit("installed document graph execution conformance smoke failed")
    scanned = root / "scanned.pdf"
    Image.new("RGB", (80, 60), (240, 240, 240)).save(scanned, "PDF")
    with (
        patch("urllib.request.urlopen", side_effect=AssertionError("hosted OCR must never run")),
        patch.dict("os.environ", {
            "FIRECRAWL_API_KEY": "synthetic-test-key",
            "FIRECRAWL_API_URL": "https://must-not-upload.invalid",
        }),
    ):
        try:
            anydoc_backend.convert(scanned, root / "scanned.md")
        except anydoc_backend.AnyDocError as error:
            if "Hosted OCR is disabled" not in str(error):
                raise
        else:
            raise SystemExit("installed AnyDoc accepted a scanned PDF instead of requiring local OCR")
    if (root / "scanned.md").exists():
        raise SystemExit("failed AnyDoc conversion left a Markdown artifact")
    print("installed AnyDoc smoke: base dependency, CSV, RTF, DOCX, graph execution, hashes, and scanned-PDF rejection passed")
PY

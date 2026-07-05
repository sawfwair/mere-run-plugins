from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from PIL import Image

from mere_workflow_tools import cli


def write_png(path: pathlib.Path, color: tuple[int, int, int] = (120, 140, 220)) -> None:
    Image.new("RGB", (32, 24), color).save(path)


def write_fake_mere_run(path: pathlib.Path) -> None:
    path.write_text(
        "import argparse, json, pathlib, sys\n"
        "from PIL import Image\n"
        "argv = sys.argv[1:]\n"
        "def value(flag, default=None):\n"
        "    return argv[argv.index(flag)+1] if flag in argv else default\n"
        "def outputs_after(flag):\n"
        "    out = []\n"
        "    if flag not in argv:\n"
        "        return out\n"
        "    start = argv.index(flag) + 2\n"
        "    for item in argv[start:]:\n"
        "        if item.startswith('--'):\n"
        "            continue\n"
        "        out.append(item)\n"
        "    return out\n"
        "if argv[:2] == ['vision', 'ocr']:\n"
        "    out_dir = pathlib.Path(value('--output-dir'))\n"
        "    out_dir.mkdir(parents=True, exist_ok=True)\n"
        "    images = [pathlib.Path(item) for item in argv if pathlib.Path(item).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}]\n"
        "    for image in images:\n"
        "        (out_dir / f'{image.stem}.txt').write_text('Alice Smith, alice@example.com, 555-1234')\n"
        "elif argv[:2] == ['text', 'anonymize']:\n"
        "    out = pathlib.Path(value('--output'))\n"
        "    out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    text = sys.stdin.read() or 'Alice Smith, alice@example.com'\n"
        "    redacted = text.replace('Alice Smith', '[NAME]').replace('alice@example.com', '[EMAIL]').replace('555-1234', '[PHONE]')\n"
        "    if '--json' in argv:\n"
        "        out.write_text(json.dumps({'redactedText': redacted, 'spans': [{'label': 'EMAIL'}]}))\n"
        "    else:\n"
        "        out.write_text(redacted)\n"
        "elif argv[:2] == ['vision', 'caption']:\n"
        "    out_dir = pathlib.Path(value('--output-dir'))\n"
        "    out_dir.mkdir(parents=True, exist_ok=True)\n"
        "    images = [pathlib.Path(item) for item in argv if pathlib.Path(item).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}]\n"
        "    trigger = value('--trigger-token', '')\n"
        "    for image in images:\n"
        "        prefix = (trigger + ', ') if trigger else ''\n"
        "        (out_dir / f'{image.stem}.txt').write_text(prefix + 'a training image with clean details')\n"
        "elif argv[:2] == ['speech', 'transcribe']:\n"
        "    out = pathlib.Path(value('--output'))\n"
        "    out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    out.write_text('Alice Smith discusses a project at alice@example.com')\n"
        "elif argv[:2] == ['image', 'generate']:\n"
        "    out = pathlib.Path(value('--output'))\n"
        "    out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    Image.new('RGB', (32, 32), (30, 180, 120)).save(out)\n"
        "else:\n"
        "    raise SystemExit('unsupported fake mere.run argv: ' + ' '.join(argv))\n"
    )


class MereWorkflowToolsTests(unittest.TestCase):
    def test_manifests_have_common_commands(self) -> None:
        for kind, spec in cli.TOOLS.items():
            manifest = cli.plugin_manifest(spec)
            self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
            self.assertEqual(manifest["name"], spec.plugin_name)
            names = {command["name"] for command in manifest["commands"]}
            self.assertTrue({"manifest", "doctor", "plan", "run", "resume", "cleanup", spec.one_shot}.issubset(names))
            self.assertEqual(manifest["security"]["cleanupDefault"], "none")

    def test_all_workflows_execute_with_fake_mere_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            command = f"{sys.executable} {fake}"

            image = root / "doc.png"
            write_png(image)
            media = root / "media"
            media.mkdir()
            write_png(media / "a.png")
            write_png(media / "b.png", (200, 100, 80))
            audio = root / "clip.wav"
            audio.write_bytes(b"fake wav")
            jobs = root / "jobs.jsonl"
            batch_output = root / "batch" / "redacted.txt"
            jobs.write_text(json.dumps({
                "argv": ["text", "anonymize", "--output", str(batch_output)],
                "outputs": {"redacted": str(batch_output)},
            }) + "\n")

            cases = [
                ("doc", ["process", "--input", str(image), "--output-dir", str(root / "doc-out")]),
                ("media", ["scrub", "--input", str(media), "--output-dir", str(root / "media-out")]),
                (
                    "dataset",
                    [
                        "caption",
                        "--input",
                        str(media),
                        "--output-dir",
                        str(root / "dataset-out"),
                        "--trigger-token",
                        "TESTSTYLE",
                        "--ocr",
                    ],
                ),
                ("transcript", ["transcribe", "--input", str(audio), "--output-dir", str(root / "transcript-out")]),
                (
                    "image_compose",
                    [
                        "generate",
                        "--prompt",
                        "a polished local image",
                        "--output-dir",
                        str(root / "image-out"),
                        "--seed",
                        "42",
                    ],
                ),
                ("batch", ["run-jobs", "--jobs", str(jobs), "--output-dir", str(root / "batch-out")]),
            ]

            for kind, args in cases:
                stdout = StringIO()
                full_args = args + ["--mere-run-command", command, "--run-id", f"unit-{kind}"]
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    exit_code = cli.main_for(kind, full_args)
                self.assertEqual(exit_code, 0, kind)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["status"], "succeeded", kind)
                self.assertGreater(len(payload["artifacts"]["files"]), 0, kind)
                self.assertEqual(payload["cleanup"]["default"], "none", kind)

    def test_plan_does_not_require_mere_run_command_to_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "doc.png"
            write_png(source)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main_for("doc", [
                    "plan",
                    "--input",
                    str(source),
                    "--output-dir",
                    str(root / "out"),
                    "--mere-run-command",
                    "missing-mere-run",
                    "--run-id",
                    "unit-plan",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["tool"]["backend"], "mere.run")


if __name__ == "__main__":
    unittest.main()

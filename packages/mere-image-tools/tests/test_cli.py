from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from PIL import Image, ImageDraw

from mere_image_tools import cli


def write_png(path: pathlib.Path) -> None:
    image = Image.new("RGBA", (24, 24), (10, 20, 30, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((7, 5, 17, 19), fill=(240, 180, 90, 255))
    image.save(path)


def write_fake_mere_run(path: pathlib.Path) -> None:
    path.write_text(
        "import argparse, json, pathlib, sys\n"
        "from PIL import Image, ImageDraw\n"
        "if sys.argv[1:3] != ['vision', 'segment']:\n"
        "    raise SystemExit('expected vision segment command')\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('input')\n"
        "parser.add_argument('--model', required=True)\n"
        "parser.add_argument('--output', required=True)\n"
        "parser.add_argument('--json-output', required=True)\n"
        "parser.add_argument('--mask-output-dir', required=True)\n"
        "parser.add_argument('--threshold')\n"
        "parser.add_argument('--resolution')\n"
        "parser.add_argument('--prompt', action='append', default=[])\n"
        "parser.add_argument('--box', action='append', default=[])\n"
        "parser.add_argument('--point', action='append', default=[])\n"
        "args = parser.parse_args(sys.argv[3:])\n"
        "image = Image.open(args.input).convert('RGBA')\n"
        "pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)\n"
        "image.save(args.output)\n"
        "mask_dir = pathlib.Path(args.mask_output_dir)\n"
        "mask_dir.mkdir(parents=True, exist_ok=True)\n"
        "detections = []\n"
        "mask_path = mask_dir / 'mask-0.png'\n"
        "mask = Image.new('L', image.size, 0)\n"
        "draw = ImageDraw.Draw(mask)\n"
        "draw.rectangle((7, 5, 17, 13), fill=255)\n"
        "draw.rectangle((9, 17, 16, 23), fill=255)\n"
        "mask.save(mask_path)\n"
        "detections.append({\n"
        "    'label': args.prompt[0] if args.prompt else 'subject',\n"
        "    'score': 0.91,\n"
        "    'maskAreaPixels': 165,\n"
        "    'maskPath': str(mask_path),\n"
        "})\n"
        "if len(args.prompt) > 1:\n"
        "    prop_path = mask_dir / 'mask-1.png'\n"
        "    prop = Image.new('L', image.size, 0)\n"
        "    ImageDraw.Draw(prop).rectangle((1, 1, 8, 8), fill=255)\n"
        "    prop.save(prop_path)\n"
        "    detections.append({\n"
        "        'label': args.prompt[1],\n"
        "        'score': 0.72,\n"
        "        'maskAreaPixels': 64,\n"
        "        'maskPath': str(prop_path),\n"
        "    })\n"
        "payload = {'detections': detections}\n"
        "pathlib.Path(args.json_output).write_text(json.dumps(payload))\n"
    )


class MereImageToolsCLITests(unittest.TestCase):
    def test_manifest_has_required_commands(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        names = {command["name"] for command in manifest["commands"]}
        self.assertTrue({"manifest", "doctor", "plan", "run", "resume", "cleanup", "knockout"}.issubset(names))
        self.assertEqual(manifest["security"]["cleanupDefault"], "none")
        self.assertIn("knockout", manifest["capabilities"])

    def test_plan_writes_knockout_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "frame.png"
            output = root / "subject.png"
            write_png(source)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--run-id",
                    "unit-plan",
                    "--mere-run-command",
                    "fake-mere-run",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["runId"], "unit-plan")
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["tool"]["backend"], "mere.run/vision-segment")
            self.assertEqual(payload["tool"]["prompts"], ["subject"])
            self.assertIn("--prompt", payload["command"])
            self.assertTrue((root / "subject.run.json").is_file())

    def test_knockout_executes_mere_run_and_records_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "frame.png"
            output = root / "subject.png"
            mask = root / "mask.png"
            fake_mere_run = root / "fake_mere_run.py"
            write_png(source)
            write_fake_mere_run(fake_mere_run)
            stdout = StringIO()
            command = f"{sys.executable} {fake_mere_run}"
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "knockout",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--mask-output",
                    str(mask),
                    "--run-id",
                    "unit-knockout",
                    "--mere-run-command",
                    command,
                    "--prompt",
                    "fox character",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "succeeded")
            self.assertTrue(output.is_file())
            self.assertTrue(mask.is_file())
            self.assertGreater(Image.open(mask).convert("L").getpixel((12, 20)), 0)
            self.assertEqual(payload["artifacts"]["selectedSourceMask"].endswith("mask-0.png"), True)
            self.assertEqual(payload["artifacts"]["selectedSourceMasks"], [payload["artifacts"]["selectedSourceMask"]])
            self.assertRegex(payload["artifacts"]["sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(payload["artifacts"]["maskSha256"], r"^sha256:[0-9a-f]{64}$")

    def test_knockout_combines_best_mask_per_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "frame.png"
            output = root / "subject.png"
            mask = root / "mask.png"
            fake_mere_run = root / "fake_mere_run.py"
            write_png(source)
            write_fake_mere_run(fake_mere_run)
            stdout = StringIO()
            command = f"{sys.executable} {fake_mere_run}"
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "knockout",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--mask-output",
                    str(mask),
                    "--run-id",
                    "unit-combined-knockout",
                    "--mere-run-command",
                    command,
                    "--prompt",
                    "fox character",
                    "--prompt",
                    "plate",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "succeeded")
            self.assertEqual(len(payload["artifacts"]["selectedSourceMasks"]), 2)
            combined = Image.open(mask).convert("L")
            self.assertGreater(combined.getpixel((12, 20)), 0)
            self.assertGreater(combined.getpixel((4, 4)), 0)

    def test_run_missing_mere_run_returns_readiness_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "frame.png"
            output = root / "subject.png"
            manifest = root / "subject.run.json"
            write_png(source)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                plan_exit = cli.main([
                    "plan",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--manifest",
                    str(manifest),
                    "--mere-run-command",
                    "missing-mere-run-command",
                ])
                run_exit = cli.main(["run", str(manifest)])
            self.assertEqual(plan_exit, 0)
            self.assertEqual(run_exit, 3)
            payload = json.loads(manifest.read_text())
            self.assertEqual(payload["status"], "failed")

    def test_cleanup_is_local_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "frame.png"
            output = root / "subject.png"
            manifest = root / "subject.run.json"
            write_png(source)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--manifest",
                    str(manifest),
                    "--mere-run-command",
                    "fake-mere-run",
                ]), 0)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["cleanup", str(manifest)])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["cleanup"]["status"], "skipped")
            self.assertEqual(payload["cleanup"]["default"], "none")


if __name__ == "__main__":
    unittest.main()

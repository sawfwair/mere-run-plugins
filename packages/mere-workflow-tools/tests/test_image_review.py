from __future__ import annotations

import json
import os
import pathlib
import shlex
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from mere_workflow_tools import cli, image_prompt_cli, image_review

# A real subprocess boundary catches argument splitting and state leaks between judges.
RUNTIME = """
import json, pathlib, sys
from PIL import Image
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
if args == ["--version"]:
    print("0.78.0" if (root / "old-runtime").exists() else "0.79.0")
    sys.exit(0)
value = lambda flag: args[args.index(flag) + 1]
with (root / "calls").open("a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["image", "generate"]:
    dest = pathlib.Path(value("--output"))
    if (root / "retry").exists() and value("--seed") == "42":
        sys.exit("Generation ended without a complete image block.")
    color = "red" if dest.stem == "original" else "blue"
    Image.new("RGB", (int(value("--width")), int(value("--height"))), color).save(dest)
else:
    image = pathlib.Path(value("--image"))
    if image.stem.startswith("pair-"):
        with Image.open(image) as sheet:
            left = sheet.getpixel((256, 300))
            right = sheet.getpixel((768, 300))
            assert (left, right) == (((0,0,255), (255,0,0)) if image.stem == "pair-1" else ((255,0,0), (0,0,255)))
    print((root / (image.stem + ".reply")).read_text())
"""


class ReviewedGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "config")})
        environment.start()
        self.addCleanup(environment.stop)
        for key in ("MERE_NEMOTRON_MODEL", "MERE_RUN_EXECUTABLE", "MERE_WORKFLOW_TOOLS_MERE_RUN"):
            os.environ.pop(key, None)
        self.config = self.root / "config/mere-image-compose/defaults.json"
        self.config.parent.mkdir(parents=True)
        self.runtime = self.root / "runtime.py"
        self.runtime.write_text(RUNTIME)
        self.out = self.root / "out"
        self.brief = 'A paper moon with the inscription "dream".'
        self.revision = "A paper moon with crisp lettering."

    def reply(self, stage: str, value: object) -> None:
        (self.root / f"{stage}.reply").write_text(json.dumps(value))

    def invoke(self) -> int:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return cli.main_for("image_compose", ["generate-reviewed", "--output-dir", str(self.out),
                                "--prompt", self.brief, "--width", "80", "--height", "48",
                                "--mere-run-command", f'"{sys.executable}" "{self.runtime}"'])

    def report(self) -> dict[str, object]:
        return json.loads((self.out / "result.json").read_text())

    def test_prompt_shortcut_uses_saved_settings_from_another_directory(self) -> None:
        wrapper = self.root / "local runtime"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, str(self.runtime)]) + ' "$@"\n')
        wrapper.chmod(0o700)
        self.config.write_text(json.dumps({"runtime": str(wrapper), "model": "test-q8", "reviewer": "test-vlm"}))
        self.reply("original", {"decision": "keep"})
        self.addCleanup(os.chdir, pathlib.Path.cwd())
        os.chdir(self.root)
        output = StringIO()
        with patch.object(sys, "argv", ["mere-image", self.brief]), redirect_stdout(output), redirect_stderr(StringIO()):
            self.assertEqual(image_prompt_cli.main(), 0)
        report = json.loads(output.getvalue())
        self.assertEqual((report["generator"], report["reviewer"], report["prompt"]),
                         ("test-q8", "test-vlm", self.brief))
        self.assertTrue(pathlib.Path(report["output"]).is_file())

    def test_default_generator_uses_mixed_six_bit_checkpoint(self) -> None:
        parser = cli.build_parser(cli.TOOLS["image_compose"])
        args = parser.parse_args(["generate-reviewed", "--prompt", self.brief])
        image_review.configured_runtime(args)
        self.assertEqual(args.model, "image-nemotron-labs-30b-a3b-q6")

    def test_environment_and_flags_override_saved_defaults(self) -> None:
        self.config.write_text(json.dumps({"runtime": "saved", "model": "saved-model"}))
        base = ["generate-reviewed", "--prompt", self.brief]
        with patch.dict(os.environ, {"MERE_NEMOTRON_MODEL": "env-model", "MERE_RUN_EXECUTABLE": "env runtime"}):
            parser = cli.build_parser(cli.TOOLS["image_compose"])
            args = parser.parse_args(base)
            self.assertEqual(image_review.configured_runtime(args), ["env runtime"])
            self.assertEqual(args.model, "env-model")
            args = parser.parse_args([*base, "--mere-run-command", "'flag runtime'", "--model", "flag-model"])
            self.assertEqual(image_review.configured_runtime(args), ["flag runtime"])
            self.assertEqual(args.model, "flag-model")

    def test_old_runtime_fails_before_generation(self) -> None:
        (self.root / "old-runtime").touch()
        self.assertNotEqual(self.invoke(), 0)
        self.assertFalse(self.out.exists())
        self.assertFalse((self.root / "calls").exists())

    def test_invalid_settings_fail_before_rendering(self) -> None:
        self.config.write_text('{"runtime": []}')
        self.assertNotEqual(self.invoke(), 0)
        self.assertFalse(self.out.exists())

    def test_keep_only_renders_once_and_preserves_prior_run(self) -> None:
        self.reply("original", {"decision": "keep"})
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.report()["selected"], "original")
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(len((self.root / "calls").read_text().splitlines()), 2)
        self.assertEqual((self.out / "original.png").read_bytes(), (self.out / "selected.png").read_bytes())

    def test_repair_requires_two_blind_votes_and_retries_incomplete_generation(self) -> None:
        (self.root / "retry").touch()
        self.reply("original", {"decision": "repair", "generator_prompt": self.revision, "evidence": "private critique"})
        self.reply("pair-1", {"winner": "A", "confidence": 0.75})
        self.reply("pair-2", {"winner": "B", "confidence": 1})
        self.assertEqual(self.invoke(), 0)
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertEqual([a[a.index("--seed") + 1] for a in calls if "--seed" in a], ["42", "43", "44"])
        self.assertEqual(calls[3][calls[3].index("--prompt") + 1], self.revision)
        for argv in (calls[2], calls[4], calls[5]):
            prompt = argv[argv.index("--prompt") + 1]
            self.assertIn(self.brief, prompt)
            self.assertNotIn("private critique", prompt)
            self.assertNotIn(self.revision, prompt)
        self.assertEqual(calls[4][calls[4].index("--prompt") + 1], calls[5][calls[5].index("--prompt") + 1])
        self.assertEqual(self.report()["selected"], "candidate")
        self.assertEqual((self.out / "candidate.png").read_bytes(), (self.out / "selected.png").read_bytes())

    def test_disagreement_ties_low_confidence_and_bad_reply_keep_original(self) -> None:
        self.reply("original", {"decision": "repair", "generator_prompt": self.revision})
        self.reply("pair-1", {"winner": "A", "confidence": 0.9})
        for i, (winner, confidence, expected) in enumerate([("A", 1, 0), ("tie", 1, 0), ("B", 0.74, 0), ("B", True, 1)]):
            with self.subTest(winner=winner, confidence=confidence):
                self.out = self.root / str(i)
                self.reply("pair-2", {"winner": winner, "confidence": confidence})
                self.assertEqual(self.invoke(), expected)
                self.assertEqual(self.report()["selected"], "original")
                self.assertEqual(self.report()["status"], "failed" if expected else "complete")
                self.assertEqual((self.out / "original.png").read_bytes(), (self.out / "selected.png").read_bytes())

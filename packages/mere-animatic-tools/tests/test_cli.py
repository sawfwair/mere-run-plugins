from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from PIL import Image

from mere_animatic_tools import cli


def write_png(path: pathlib.Path) -> None:
    Image.new("RGBA", (32, 24), (220, 120, 80, 255)).save(path)


class MereAnimaticToolsTests(unittest.TestCase):
    def test_manifest_has_contract_commands_and_all_tools(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        self.assertEqual(manifest["name"], "mere-animatic-tools")
        names = {command["name"] for command in manifest["commands"]}
        self.assertTrue({"manifest", "doctor", "plan", "run", "resume", "cleanup"}.issubset(names))
        self.assertTrue(set(cli.TOOLS).issubset(names))
        self.assertEqual(manifest["security"]["cleanupDefault"], "none")

    def test_plan_writes_manifest_from_request_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            request = root / "request.json"
            request.write_text(json.dumps({"inputs": {"prompt": "a hallway beat"}}))
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan",
                    "--tool",
                    "shot-kit",
                    "--request-json",
                    str(request),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "unit-plan",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["tool"]["name"], "shot-kit")
            self.assertTrue((root / "out" / "run.json").is_file())

    def test_all_tools_execute_without_remote_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            image = root / "frame.png"
            write_png(image)
            request = root / "request.json"
            request.write_text(json.dumps({
                "inputs": {
                    "prompt": "a small scene",
                    "assets": [{"name": "frame", "path": str(image)}],
                    "lines": ["I know where the key is."],
                }
            }))
            for name in cli.TOOLS:
                stdout = StringIO()
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    exit_code = cli.main([
                        name,
                        "--request-json",
                        str(request),
                        "--output-dir",
                        str(root / name),
                        "--run-id",
                        f"unit-{name}",
                    ])
                self.assertEqual(exit_code, 0, name)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["status"], "succeeded", name)
                self.assertGreater(len(payload["artifacts"]["items"]), 0, name)
                self.assertTrue((root / name / "run.json").is_file())

    def test_cleanup_is_local_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--tool",
                    "delivery-prep",
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "unit-cleanup",
                ]), 0)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["cleanup", str(root / "out" / "run.json")])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["cleanup"]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()

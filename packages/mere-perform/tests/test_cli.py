from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from mere_perform import cli


class MerePerformTests(unittest.TestCase):
    def write_show(self, root: pathlib.Path) -> pathlib.Path:
        show = root / "show.json"
        show.write_text(json.dumps({
            "contractVersion": "mere.run/perform-show.v1",
            "title": "Unit Heart",
            "durationSeconds": 0.2,
            "promptStrategy": {"resetAfterPrompt": True, "promptDebounceMs": 0},
            "audio": {"play": False, "capture": "unit.wav"},
            "midi": {
                "input": "OP-1",
                "channel": "all",
                "noteOffset": 12,
                "cc": ["1=temp:0.2:1.4"],
                "keyboard": {"enabled": True, "baseNote": 48, "octaveRange": 2},
                "gate": {"enabled": True, "releaseMs": 700, "idleStopSeconds": 20},
                "pads": [
                    {"id": "pad-one", "label": "1", "sceneId": "one", "target": "scene"},
                    {"id": "pad-two", "label": "2", "sceneId": "two", "target": "scene"},
                ],
                "activity": {"demoNotes": [48, 52, 55]},
            },
            "heart": {"x": 0.45, "y": 0.55, "color": "#ff2fb3"},
            "prompts": [
                {"id": "pulse", "role": "texture", "mode": "jam", "text": "soft synth pulse", "x": 0.5, "y": 0.2, "cfgMusicCoCa": 2.2},
                {"id": "tilt", "role": "lead", "mode": "solo", "text": "tape bass tilt", "x": 0.8, "y": 0.5, "cfgMusicCoCa": 3.4},
            ],
            "scenes": [
                {"id": "one", "title": "One", "durationSeconds": 0.1, "promptId": "pulse"},
                {"id": "two", "title": "Two", "durationSeconds": 0.1, "promptId": "tilt", "temperature": 1.1},
            ],
        }))
        return show

    def test_manifest_has_required_commands(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        self.assertEqual(manifest["name"], "mere-perform")
        names = {command["name"] for command in manifest["commands"]}
        self.assertTrue({"manifest", "doctor", "plan", "run", "resume", "cleanup", "stage", "devices", "show-template", "perform"}.issubset(names))
        self.assertEqual(manifest["security"]["createsPaidResources"], False)
        self.assertEqual(manifest["security"]["cleanupDefault"], "none")

    def test_plan_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            show = self.write_show(root)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan",
                    "--show",
                    str(show),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "unit-heart",
                    "--mere-run-command",
                    "fake-mere-run",
                    "--no-play",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["plugin"]["name"], "mere-perform")
            self.assertEqual(payload["runtime"]["backend"], "mere.run/music-realtime")
            self.assertIn("--interactive", payload["command"])
            self.assertIn("--no-play", payload["command"])
            self.assertIn("--midi-note-offset", payload["command"])
            self.assertIn("12", payload["command"])
            self.assertEqual(payload["performance"]["show"]["prompts"][1]["role"], "lead")
            self.assertEqual(payload["performance"]["show"]["midi"]["noteOffset"], 12)
            self.assertEqual(payload["performance"]["show"]["midi"]["keyboard"]["baseNote"], 48)
            self.assertEqual(payload["performance"]["show"]["midi"]["gate"]["releaseMs"], 700)
            self.assertEqual(payload["performance"]["show"]["midi"]["pads"][1]["sceneId"], "two")
            self.assertEqual(payload["performance"]["show"]["scenes"][1]["runtimePrompt"], "SOLO tape bass tilt")
            self.assertEqual(payload["performance"]["show"]["scenes"][1]["cfgMusicCoCa"], 3.4)
            self.assertEqual(payload["performance"]["show"]["scenes"][1]["unmaskWidth"], 127.0)
            self.assertTrue((root / "out" / "run.json").is_file())

    def test_stage_exports_static_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            show = self.write_show(root)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--show",
                    str(show),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "stage-heart",
                    "--mere-run-command",
                    "fake-mere-run",
                ]), 0)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["stage", str(root / "out" / "run.json")])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            html_path = pathlib.Path(payload["stageHtml"])
            state_path = pathlib.Path(payload["stageState"])
            self.assertTrue(html_path.is_file())
            self.assertTrue(state_path.is_file())
            self.assertIn("mere.perform", html_path.read_text())
            self.assertIn("midi-pads", html_path.read_text())
            self.assertIn("piano", html_path.read_text())
            state = json.loads(state_path.read_text())
            self.assertEqual(state["show"]["title"], "Unit Heart")
            self.assertEqual(state["show"]["prompts"][1]["mode"], "solo")
            self.assertEqual(state["show"]["midi"]["activity"]["demoNotes"], [48, 52, 55])

    def test_run_executes_fake_realtime_and_records_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            fake = root / "fake-mere-run"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "if '--output' in args:\n"
                "    pathlib.Path(args[args.index('--output') + 1]).write_bytes(b'fake wav')\n"
                "pathlib.Path('stdin.txt').write_text(sys.stdin.read())\n"
                "print('fake realtime ok')\n"
            )
            fake.chmod(fake.stat().st_mode | 0o111)
            show = self.write_show(root)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--show",
                    str(show),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "run-heart",
                    "--mere-run-command",
                    str(fake),
                    "--no-play",
                ]), 0)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["run", str(root / "out" / "run.json")])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "succeeded")
            self.assertTrue((root / "out" / "unit.wav").is_file())
            self.assertTrue((root / "out" / "events.jsonl").is_file())
            self.assertTrue((root / "out" / "stage" / "index.html").is_file())
            commands = (root / "out" / "stdin.txt").read_text()
            self.assertIn("prompt SOLO tape bass tilt", commands)
            self.assertIn("mc 3.4", commands)
            self.assertIn("unmask 127.0", commands)
            self.assertIn("reset", commands)

    def test_cleanup_and_devices_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            show = self.write_show(root)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--show",
                    str(show),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "cleanup-heart",
                    "--mere-run-command",
                    "fake-mere-run",
                ]), 0)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(cli.main(["cleanup", str(root / "out" / "run.json")]), 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["cleanup"]["status"], "skipped")

        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            self.assertEqual(cli.main(["devices", "--mere-run-command", "fake-mere-run", "--dry-run"]), 0)
        self.assertTrue(json.loads(stdout.getvalue())["dryRun"])

    def test_doctor_uses_environment_override(self) -> None:
        stdout = StringIO()
        with (
            redirect_stdout(stdout),
            redirect_stderr(StringIO()),
            mock.patch.dict(os.environ, {"MERE_PERFORM_MERE_RUN": "fake-mere-run"}),
        ):
            exit_code = cli.main(["doctor"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["checks"][0]["detail"], "fake-mere-run")


if __name__ == "__main__":
    unittest.main()

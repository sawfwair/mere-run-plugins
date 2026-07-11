from __future__ import annotations

import json
import os
import pathlib
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from mere_perform import cli


class MerePerformTests(unittest.TestCase):
    def free_port(self) -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

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
                "logEvents": False,
                "logRaw": False,
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
                    "--stage-port",
                    "8880",
                    "--open-stage",
                    "--midi-log-events",
                    "--midi-log-raw",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["plugin"]["name"], "mere-perform")
            self.assertEqual(payload["runtime"]["backend"], "mere.run/music-realtime")
            self.assertEqual(payload["performance"]["show"]["model"], "music-magenta-rt2-base")
            self.assertIn("music-magenta-rt2-base", payload["command"])
            self.assertIn("--interactive", payload["command"])
            self.assertIn("--no-play", payload["command"])
            self.assertIn("--midi-note-offset", payload["command"])
            self.assertIn("12", payload["command"])
            self.assertIn("SOLO tape bass tilt", payload["command"])
            self.assertIn("--midi-log-events", payload["command"])
            self.assertIn("--midi-log-raw", payload["command"])
            self.assertEqual(payload["performance"]["show"]["prompts"][1]["role"], "lead")
            self.assertEqual(payload["performance"]["initialPrompt"], "tape bass tilt")
            self.assertEqual(payload["performance"]["initialRuntimePrompt"], "SOLO tape bass tilt")
            self.assertEqual(payload["performance"]["show"]["midi"]["noteOffset"], 12)
            self.assertEqual(payload["performance"]["show"]["midi"]["instrumentMode"], True)
            self.assertEqual(payload["performance"]["show"]["midi"]["logEvents"], True)
            self.assertEqual(payload["performance"]["show"]["midi"]["logRaw"], True)
            self.assertEqual(payload["performance"]["show"]["midi"]["keyboard"]["baseNote"], 48)
            self.assertEqual(payload["performance"]["show"]["midi"]["gate"]["releaseMs"], 700)
            self.assertEqual(payload["performance"]["show"]["midi"]["pads"][1]["sceneId"], "two")
            self.assertEqual(payload["performance"]["show"]["scenes"][1]["runtimePrompt"], "SOLO tape bass tilt")
            self.assertEqual(payload["performance"]["show"]["scenes"][1]["cfgMusicCoCa"], 3.4)
            self.assertEqual(payload["performance"]["show"]["scenes"][1]["unmaskWidth"], 127.0)
            self.assertEqual(payload["performance"]["stage"]["port"], 8880)
            self.assertEqual(payload["performance"]["stage"]["open"], True)
            self.assertEqual(payload["performance"]["sequenceScenes"], False)
            self.assertTrue((root / "out" / "run.json").is_file())

    def test_run_marks_missing_runtime_failed(self) -> None:
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
                    "missing-heart",
                    "--mere-run-command",
                    str(root / "does-not-exist"),
                ]), 0)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main(["run", str(root / "out" / "run.json")])
            self.assertEqual(exit_code, 3)
            manifest = json.loads((root / "out" / "run.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertIn("command not found", manifest["error"])
            state = json.loads((root / "out" / "stage" / "state.json").read_text())
            self.assertEqual(state["status"], "failed")

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
            html = html_path.read_text()
            self.assertIn("mere.perform", html)
            self.assertIn("midi-pads", html)
            self.assertIn("piano", html)
            self.assertIn("useDemoNotes", html)
            self.assertIn("live.json", html)
            self.assertIn("pollLiveState", html)
            self.assertIn("waiting midi", html)
            self.assertIn("prompt-form", html)
            self.assertIn("/control/prompt", html)
            self.assertIn("lastMidiEventAt", html)
            self.assertIn("midiLevel", html)
            self.assertIn("prompt-section", html)
            live_path = (root / "out" / "stage" / "live.json").resolve()
            self.assertTrue(live_path.is_file())
            state = json.loads(state_path.read_text())
            self.assertEqual(state["show"]["title"], "Unit Heart")
            self.assertEqual(state["show"]["prompts"][1]["mode"], "solo")
            self.assertEqual(state["performance"]["sequenceScenes"], False)
            live = json.loads(live_path.read_text())
            self.assertEqual(live["midi"]["activeNotes"], [])
            self.assertEqual(live["midi"]["eventCount"], 0)
            self.assertEqual(live["control"], {})
            args = cli.build_parser().parse_args(["stage", str(root / "out" / "run.json"), "--serve", "--open"])
            self.assertTrue(args.open)
            self.assertEqual(state["show"]["midi"]["activity"]["demoNotes"], [48, 52, 55])

    def test_stage_control_bridge_sends_prompt_to_interactive_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            show = self.write_show(root)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--show",
                    str(show),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "control-heart",
                    "--mere-run-command",
                    "fake-mere-run",
                    "--stage-port",
                    "9999",
                ]), 0)
            manifest = json.loads(stdout.getvalue())
            stdin = StringIO()
            control = cli.StageControlBridge(manifest)
            control.attach_stdin(stdin)
            worker = threading.Thread(target=control.run)
            worker.start()
            result = control.submit_prompt("granular piano over tape hiss")
            control.stop()
            worker.join(timeout=2)
            self.assertEqual(result["lastPrompt"], "granular piano over tape hiss")
            self.assertEqual(stdin.getvalue(), "prompt granular piano over tape hiss\n")
            live = json.loads((root / "out" / "stage" / "live.json").read_text())
            self.assertEqual(live["control"]["lastPrompt"], "granular piano over tape hiss")
            events = (root / "out" / "events.jsonl").read_text()
            self.assertIn('"type": "web-prompt"', events)

    def test_stage_server_control_endpoint_accepts_prompt_posts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            show = self.write_show(root)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--show",
                    str(show),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "endpoint-heart",
                    "--mere-run-command",
                    "fake-mere-run",
                    "--stage-port",
                    "9999",
                ]), 0)
            manifest = json.loads(stdout.getvalue())
            stdin = StringIO()
            control = cli.StageControlBridge(manifest)
            control.attach_stdin(stdin)
            worker = threading.Thread(target=control.run)
            worker.start()
            server, url = cli.create_stage_server(manifest, "127.0.0.1", 0, control)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                with redirect_stderr(StringIO()):
                    request = urllib.request.Request(
                        f"{url}control/prompt",
                        data=json.dumps({"prompt": "warm brass swells"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(payload["ok"])
                    self.assertEqual(payload["prompt"], "warm brass swells")
                    self.assertEqual(payload["control"]["lastPrompt"], "warm brass swells")
                    empty = urllib.request.Request(
                        f"{url}control/prompt",
                        data=json.dumps({"prompt": "   "}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(empty, timeout=5)
                    self.assertEqual(denied.exception.code, 400)
            finally:
                server.shutdown()
                server_thread.join(timeout=2)
                server.server_close()
                control.stop()
                worker.join(timeout=2)
            self.assertEqual(stdin.getvalue(), "prompt warm brass swells\n")
            live = json.loads((root / "out" / "stage" / "live.json").read_text())
            self.assertEqual(live["control"]["lastPrompt"], "warm brass swells")

    def test_stage_serve_without_live_run_rejects_prompt_posts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            show = self.write_show(root)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--show",
                    str(show),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "static-heart",
                    "--mere-run-command",
                    "fake-mere-run",
                ]), 0)
            manifest = json.loads(stdout.getvalue())
            server, url = cli.create_stage_server(manifest, "127.0.0.1", 0)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            try:
                with redirect_stderr(StringIO()):
                    request = urllib.request.Request(
                        f"{url}control/prompt",
                        data=json.dumps({"prompt": "warm brass swells"}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        urllib.request.urlopen(request, timeout=5)
                    self.assertEqual(denied.exception.code, 409)
                    payload = json.loads(denied.exception.read().decode("utf-8"))
                    self.assertFalse(payload["ok"])
                    self.assertIn("not attached", payload["error"])
            finally:
                server.shutdown()
                server_thread.join(timeout=2)
                server.server_close()

    def test_live_midi_bridge_tracks_mere_run_note_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            show = self.write_show(root)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(cli.main([
                    "plan",
                    "--show",
                    str(show),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "bridge-heart",
                    "--mere-run-command",
                    "fake-mere-run",
                    "--stage-port",
                    "9999",
                ]), 0)
            manifest = json.loads(stdout.getvalue())
            bridge = cli.LiveMidiBridge(manifest)
            self.assertTrue(bridge.handle_line("MIDI note-on ch=4 note=60 velocity=127"))
            self.assertTrue(bridge.handle_line("MIDI note-on ch=4 note=64 velocity=127"))
            self.assertTrue(bridge.handle_line("MIDI note-off ch=4 note=60"))
            live = json.loads((root / "out" / "stage" / "live.json").read_text())
            self.assertEqual(live["midi"]["activeNotes"], [64])
            self.assertEqual(live["midi"]["eventCount"], 3)
            self.assertEqual(live["midi"]["lastEvent"], {"channel": 4, "note": 60, "type": "note-off"})

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
                "pathlib.Path('stdin.txt').write_text('')\n"
                "print('MIDI note-on ch=4 note=60 velocity=127')\n"
                "print('MIDI note-on ch=4 note=64 velocity=127')\n"
                "print('MIDI note-off ch=4 note=60')\n"
                "print('MIDI note-off ch=4 note=64')\n"
                "print('fake realtime ok')\n"
            )
            fake.chmod(fake.stat().st_mode | 0o111)
            show = self.write_show(root)
            port = self.free_port()
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
                    "--stage-port",
                    str(port),
                ]), 0)
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli.main(["run", str(root / "out" / "run.json")])
            self.assertEqual(exit_code, 0)
            self.assertIn("serving live stage UI", stderr.getvalue())
            self.assertIn("live stage server stopped", stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "succeeded")
            self.assertTrue((root / "out" / "unit.wav").is_file())
            self.assertTrue((root / "out" / "events.jsonl").is_file())
            self.assertTrue((root / "out" / "stage" / "index.html").is_file())
            live_path = (root / "out" / "stage" / "live.json").resolve()
            self.assertTrue(live_path.is_file())
            self.assertIn(str(live_path), payload["artifacts"]["files"])
            self.assertEqual(payload["artifacts"]["stageLive"], str(live_path))
            live = json.loads(live_path.read_text())
            self.assertEqual(live["status"], "succeeded")
            self.assertEqual(live["midi"]["activeNotes"], [])
            self.assertEqual(live["midi"]["eventCount"], 4)
            self.assertEqual(live["midi"]["lastEvent"], {"channel": 4, "note": 64, "type": "note-off"})
            self.assertIn("--midi-log-events", payload["command"])
            commands = (root / "out" / "stdin.txt").read_text()
            self.assertNotIn("prompt SOLO tape bass tilt", commands)
            self.assertNotIn("mc 3.4", commands)
            self.assertNotIn("unmask 127", commands)

    def test_sequence_scenes_opt_in_sends_prompt_changes(self) -> None:
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
                    "sequence-heart",
                    "--mere-run-command",
                    str(fake),
                    "--no-play",
                    "--sequence-scenes",
                ]), 0)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["run", str(root / "out" / "run.json")])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["performance"]["sequenceScenes"], True)
            commands = (root / "out" / "stdin.txt").read_text()
            self.assertIn("prompt SOLO tape bass tilt", commands)
            self.assertIn("mc 3.4", commands)
            self.assertIn("unmask 127", commands)
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

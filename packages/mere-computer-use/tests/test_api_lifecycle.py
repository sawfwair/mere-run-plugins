from __future__ import annotations

import argparse
import os
import pathlib
import socket
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

from mere_computer_use import api_lifecycle, cli


class APILifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.server = self.root / "fake-mere-run"
        self.server.write_text(f"#!{sys.executable}\n" + '''
import http.server
import json
import os
import sys

args = sys.argv[1:]
if args[:2] == ["model", "info"]:
    print(json.dumps({"id": args[2], "usageTerms": [{"component": "Muse Glimmer"}],
                      "usageTermsAcknowledged": os.environ.get("FAKE_TERMS_ACK") != "0"}))
    raise SystemExit(0)
model = args[args.index("--model") + 1]
if "--preflight" in args:
    installed = os.environ.get("FAKE_MODEL_INSTALLED") != "0"
    print(json.dumps({"status": "ok" if installed else "blocked",
                      "result": {"model": {"id": model, "installed": installed}}}))
    raise SystemExit(0 if installed else 1)

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        payload = {"data": [{"id": model, "tool_call": True,
                              "modalities": {"input": ["text", "image"]}}]}
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass

port = int(args[args.index("--port") + 1])
http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
''', encoding="utf-8")
        self.server.chmod(0o755)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}/v1"

    def environment(self) -> mock._patch_dict[str, str]:
        return mock.patch.dict(os.environ, {"MERE_COMPUTER_USE_MERE_RUN": str(self.server)})

    def test_starts_installed_model_and_stops_owned_server(self) -> None:
        with self.environment():
            server = api_lifecycle.ensure_model(self.base_url, cli.DEFAULT_MODEL, cli.model_ready, self.root, 10)
            self.assertIsNotNone(server)
            assert server is not None
            self.assertTrue(cli.model_ready(self.base_url, cli.DEFAULT_MODEL))
            self.assertIsNone(server.process.poll())
            server.stop()
            self.assertIsNotNone(server.process.poll())
            self.assertTrue(server.log.closed)

    def test_existing_server_is_reused_and_not_stopped(self) -> None:
        with self.environment():
            server = api_lifecycle.ensure_model(self.base_url, cli.DEFAULT_MODEL, cli.model_ready, self.root, 10)
            assert server is not None
            try:
                reused = api_lifecycle.ensure_model(self.base_url, cli.DEFAULT_MODEL, cli.model_ready, self.root, 10)
                self.assertIsNone(reused)
                self.assertIsNone(server.process.poll())
            finally:
                server.stop()

    def test_preflight_refuses_missing_model_and_incompatible_endpoint(self) -> None:
        with self.environment(), mock.patch.dict(os.environ, {"FAKE_MODEL_INSTALLED": "0"}):
            with self.assertRaises(api_lifecycle.APIServerError):
                api_lifecycle.ensure_model(self.base_url, cli.DEFAULT_MODEL, cli.model_ready, self.root, 10)
        self.assertFalse((self.root / "api-server.log").exists())
        with mock.patch.object(api_lifecycle, "preflight") as preflight:
            with self.assertRaises(api_lifecycle.APIServerError):
                api_lifecycle.ensure_model(self.base_url, cli.DEFAULT_MODEL, lambda *_: False, self.root, 10)
            preflight.assert_not_called()

    def test_preflight_refuses_unacknowledged_model_terms(self) -> None:
        with self.environment(), mock.patch.dict(os.environ, {"FAKE_TERMS_ACK": "0"}):
            with self.assertRaisesRegex(api_lifecycle.APIServerError, "unacknowledged upstream usage terms"):
                api_lifecycle.ensure_model(self.base_url, cli.DEFAULT_MODEL, cli.model_ready, self.root, 10)
        self.assertFalse((self.root / "api-server.log").exists())

    def test_run_stops_owned_server_after_pi_exits(self) -> None:
        plan_path = self.root / "run.json"
        plan = cli.plan(argparse.Namespace(pid=101, window_id=202, task="Read", output=self.root,
                                           model=cli.DEFAULT_MODEL, base_url=self.base_url, max_actions=2))
        self.assertEqual(plan["status"], "planned")
        pi = self.root / "fake-pi"
        pi.write_text(f"#!{sys.executable}\n" + '''
import json
import os
import urllib.request
request = urllib.request.Request(os.environ["MERERUN_BASE_URL"] + "/models")
with urllib.request.urlopen(request, timeout=3) as response:
    print(json.load(response)["data"][0]["id"])
''', encoding="utf-8")
        pi.chmod(0o755)
        with self.environment(), mock.patch.dict(os.environ, {"MERE_COMPUTER_USE_PI": str(pi)}), \
             mock.patch.object(cli, "windows", return_value={"windows": [{"pid": 101, "window_id": 202}]}), \
             mock.patch.object(cli, "permissions", return_value={"accessibility": True, "screen_recording": True}):
            result = cli.run_plan(plan_path, 10, api_start_timeout=10)
        self.assertEqual(result["status"], "finished")
        self.assertEqual(result["result"], cli.DEFAULT_MODEL)
        self.assertEqual(result["apiServer"]["ownership"], "plugin")
        self.assertEqual(result["apiServer"]["status"], "stopped")

    def test_doctor_reports_installed_model_startable_without_starting(self) -> None:
        unavailable = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        with self.environment(), mock.patch.object(cli.shutil, "which", return_value="/fixture/bin"), \
             mock.patch.object(cli, "model_ready", side_effect=unavailable), \
             mock.patch.object(cli, "driver_call", return_value={"windows": []}), \
             mock.patch.object(cli, "permissions", return_value={"accessibility": True, "screen_recording": True}):
            result = cli.doctor(argparse.Namespace(base_url=self.base_url, model=cli.DEFAULT_MODEL))
        self.assertTrue(result["ready"])
        self.assertFalse(result["modelReady"])
        self.assertTrue(result["modelStartable"])
        self.assertIsNone(result["modelStartError"])
        self.assertFalse((self.root / "api-server.log").exists())


if __name__ == "__main__":
    unittest.main()

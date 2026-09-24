from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from mere_computer_use import cli


class ComputerUseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)

    def planned(self, max_actions: int = 2) -> pathlib.Path:
        cli.plan(argparse.Namespace(
            pid=101, window_id=202, task="Read the total", output=self.root / "run",
            model=cli.DEFAULT_MODEL, base_url=cli.DEFAULT_BASE_URL, max_actions=max_actions,
        ))
        return self.root / "run" / "run.json"

    def tool_args(self, action: str, **values: str) -> argparse.Namespace:
        return argparse.Namespace(action=action, element_token=values.get("element_token"),
                                  text=values.get("text"), key=values.get("key"),
                                  x=float(values["x"]) if "x" in values else None,
                                  y=float(values["y"]) if "y" in values else None,
                                  capture_id=values.get("capture_id"))

    @staticmethod
    def fake_driver(tool: str, _arguments: cli.JsonMap) -> cli.JsonMap:
        if tool == "check_permissions":
            return {"accessibility": True, "screen_recording": True}
        return {"elements": []}

    def test_manifest_and_packaged_extensions(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["name"], "mere-computer-use")
        self.assertGreaterEqual(len(manifest["commands"]), 5)
        self.assertTrue(all(path.is_file() for path in cli.pi_extensions()))

    def test_loopback_only(self) -> None:
        self.assertEqual(cli.loopback_url("http://127.0.0.1:8080/v1/"), cli.DEFAULT_BASE_URL)
        for invalid in ("https://127.0.0.1:8080/v1", "http://example.com/v1", "http://127.0.0.1:8080/other",
                        "http://user:secret@127.0.0.1/v1", "http://192.168.1.2/v1"):
            with self.subTest(invalid=invalid), self.assertRaises(cli.PluginError):
                cli.loopback_url(invalid)

    def test_plan_is_local_and_does_not_replace_existing_record(self) -> None:
        with mock.patch.object(cli, "driver_call") as driver:
            path = self.planned()
            driver.assert_not_called()
        run = cli.load(path)
        self.assertEqual(run["status"], "planned")
        self.assertEqual(run["target"], {"pid": 101, "windowId": 202})
        self.assertNotIn("apiKey", json.dumps(run))
        with self.assertRaises(cli.PluginError):
            self.planned()

    def test_observe_action_observe_enforced_and_bounded(self) -> None:
        path = self.planned(max_actions=1)
        run = cli.load(path)
        run["status"] = "running"
        cli.save(path, run)
        with self.assertRaises(cli.PluginError):
            cli.tool(path, self.tool_args("click", element_token="token"))
        with mock.patch.object(cli, "driver_call", side_effect=[
            {"elements": [], "screenshot_png_b64": "AA=="},
            {"effect": "unverifiable"},
            {"elements": []},
        ]) as driver:
            observed = cli.tool(path, self.tool_args("observe"))
            self.assertEqual(observed["screenshot_png_b64"], "AA==")
            clicked = cli.tool(path, self.tool_args("click", element_token="token"))
            self.assertEqual(clicked["effect"], "unverifiable")
            with self.assertRaises(cli.PluginError):
                cli.tool(path, self.tool_args("type", element_token="token", text="hello"))
            cli.tool(path, self.tool_args("observe"))
            with self.assertRaises(cli.PluginError):
                cli.tool(path, self.tool_args("click", element_token="token"))
            self.assertEqual(driver.call_args_list[1].args[0], "click")
            self.assertEqual(driver.call_args_list[1].args[1]["window_id"], 202)
        self.assertEqual(cli.load(path)["actionCount"], 1)
        self.assertFalse(cli.load(path)["needsObservation"])
        self.assertNotIn("screenshot", path.read_text())

    def test_window_identity_must_remain_present(self) -> None:
        path = self.planned()
        with mock.patch.object(cli, "windows", return_value={"windows": [{"pid": 101, "window_id": 202}]}):
            cli.verify_target(cli.load(path))
        with mock.patch.object(cli, "windows", return_value={"windows": [{"pid": 101, "window_id": 203}]}):
            with self.assertRaises(cli.PluginError):
                cli.verify_target(cli.load(path))

    def test_pixel_click_requires_latest_capture(self) -> None:
        path = self.planned()
        run = cli.load(path)
        run["status"] = "running"
        cli.save(path, run)
        with mock.patch.object(cli, "driver_call", side_effect=[
            {"capture_id": "cap-1", "screenshot_png_b64": "AA=="},
            {"effect": "unverifiable"},
        ]) as driver:
            cli.tool(path, self.tool_args("observe"))
            with self.assertRaises(cli.PluginError):
                cli.tool(path, self.tool_args("click", x="10", y="20", capture_id="old"))
            cli.tool(path, self.tool_args("click", x="10", y="20", capture_id="cap-1"))
        self.assertEqual(driver.call_args_list[1].args[1]["capture_id"], "cap-1")
        self.assertEqual(driver.call_args_list[1].args[1]["x"], 10.0)

    def test_run_records_final_observation_without_claiming_independent_success(self) -> None:
        path = self.planned()

        def fake_pi(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            self.assertEqual(args[0][0], "pi")
            self.assertIn("--no-builtin-tools", args[0])
            cli.tool(path, self.tool_args("observe"))
            cli.tool(path, self.tool_args("click", element_token="token"))
            cli.tool(path, self.tool_args("observe"))
            return subprocess.CompletedProcess(args[0], 0, stdout="Total is 42", stderr="")

        with mock.patch.object(cli, "windows", return_value={"windows": [{"pid": 101, "window_id": 202}]}), \
             mock.patch.object(cli, "model_ready", return_value=True), \
             mock.patch.object(cli, "driver_call", side_effect=self.fake_driver), \
             mock.patch.object(cli.subprocess, "run", side_effect=fake_pi):
            result = cli.run_plan(path, 10)
        self.assertEqual(result["status"], "finished")
        self.assertEqual(result["verification"], "model-report-with-final-observation")
        self.assertEqual(result["actionCount"], 1)
        self.assertEqual(result["result"], "Total is 42")

    def test_no_final_observation_is_reported(self) -> None:
        path = self.planned()

        def fake_pi(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            cli.tool(path, self.tool_args("observe"))
            cli.tool(path, self.tool_args("key", key="return"))
            return subprocess.CompletedProcess(args[0], 0, stdout="Done", stderr="")

        with mock.patch.object(cli, "windows", return_value={"windows": [{"pid": 101, "window_id": 202}]}), \
             mock.patch.object(cli, "model_ready", return_value=True), \
             mock.patch.object(cli, "driver_call", side_effect=self.fake_driver), \
             mock.patch.object(cli.subprocess, "run", side_effect=fake_pi):
            result = cli.run_plan(path, 10)
        self.assertEqual(result["verification"], "incomplete-or-unobserved")

    def test_run_requires_driver_permissions_before_pi(self) -> None:
        path = self.planned()
        with mock.patch.object(cli, "windows", return_value={"windows": [{"pid": 101, "window_id": 202}]}), \
             mock.patch.object(cli, "permissions", return_value={
                 "accessibility": True, "screen_recording": False,
             }), \
             mock.patch.object(cli.subprocess, "run") as pi:
            with self.assertRaises(cli.PluginError):
                cli.run_plan(path, 10)
            pi.assert_not_called()
        self.assertEqual(cli.load(path)["status"], "planned")

    def test_cleanup_rejects_active_run(self) -> None:
        path = self.planned()
        run = cli.load(path)
        run["status"] = "running"
        cli.save(path, run)
        with self.assertRaises(cli.PluginError):
            cli.cleanup(path)
        run["status"] = "finished"
        cli.save(path, run)
        self.assertEqual(cli.cleanup(path)["cleanup"]["status"], "local-record-only")


if __name__ == "__main__":
    unittest.main()

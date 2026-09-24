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
                                  snapshot_id=values.get("snapshot_id"), modifier=None)

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
            with self.assertRaisesRegex(cli.PluginError, "latest observation is current"):
                cli.tool(path, self.tool_args("observe"))
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

    def test_observation_keeps_only_selected_window_elements(self) -> None:
        path = self.planned()
        run = cli.load(path)
        run["status"] = "running"
        cli.save(path, run)
        raw = {
            "snapshot_id": "s00000002", "screenshot_png_b64": "AA==", "tree_markdown": "recent private file",
            "elements": [
                {"element_index": 0, "role": "AXWindow", "label": "Selected"},
                {"element_index": 1, "parent_index": 0, "role": "AXTextArea", "value": "hello"},
                {"element_index": 2, "role": "AXMenuBar"},
                {"element_index": 3, "parent_index": 2, "role": "AXMenuItem", "label": "recent private file"},
            ],
        }
        with mock.patch.object(cli, "driver_call", return_value=raw) as driver:
            observed = cli.tool(path, self.tool_args("observe"))
        self.assertEqual([item["element_index"] for item in observed["elements"]], [0, 1])
        self.assertNotIn("tree_markdown", observed)
        self.assertNotIn("recent private file", json.dumps(observed))
        self.assertEqual(observed["snapshot_id"], "s00000002")
        self.assertEqual(driver.call_args.args[1]["max_dimension"], 960)
        self.assertNotIn("max_image_dimension", driver.call_args.args[1])

    def test_pixel_click_requires_latest_screenshot_snapshot(self) -> None:
        path = self.planned()
        run = cli.load(path)
        run["status"] = "running"
        cli.save(path, run)
        with mock.patch.object(cli, "driver_call", side_effect=[
            {"snapshot_id": "s00000002", "screenshot_png_b64": "AA=="},
            {"effect": "unverifiable"},
        ]) as driver:
            cli.tool(path, self.tool_args("observe"))
            with self.assertRaises(cli.PluginError):
                cli.tool(path, self.tool_args("click", x="10", y="20", snapshot_id="old"))
            cli.tool(path, self.tool_args("click", x="10", y="20", snapshot_id="s00000002"))
        self.assertNotIn("snapshot_id", driver.call_args_list[1].args[1])
        self.assertEqual(driver.call_args_list[1].args[1]["x"], 10.0)

    def test_key_passes_command_modifier_to_driver(self) -> None:
        path = self.planned()
        run = cli.load(path)
        run["status"] = "running"
        run["needsObservation"] = False
        cli.save(path, run)
        arguments = cli.parser().parse_args([
            "_tool", str(path), "key", "--key", "s", "--modifier", "cmd",
        ])
        with mock.patch.object(cli, "driver_call", return_value={"effect": "unverifiable"}) as driver:
            cli.tool(path, arguments)
        self.assertEqual(driver.call_args.args[0], "press_key")
        self.assertEqual(driver.call_args.args[1]["modifiers"], ["cmd"])

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

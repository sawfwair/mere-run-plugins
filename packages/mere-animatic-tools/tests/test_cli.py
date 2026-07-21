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
                if name in {"build-set-proxy", "solve-set-lighting", "render-set-plate"}:
                    continue
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

    def test_download_assets_accepts_local_paths_in_url_field(self) -> None:
        # Regression: the documented request shape allows local file paths in the
        # `url` field, but urlopen() rejected them so the assets were skipped.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            local = root / "frame.png"
            write_png(local)
            fetched = root / "plate.png"
            write_png(fetched)
            request = {
                "inputs": {
                    "assets": [
                        {"name": "bare-path-in-url", "url": str(local)},
                        str(local),
                        {"name": "path-key", "path": str(local)},
                        {"name": "file-url", "url": fetched.as_uri()},
                        {"name": "missing-path", "url": str(root / "nope.png")},
                        {"name": "bad-url", "url": (root / "gone.png").as_uri()},
                        {"name": "no-source"},
                    ]
                }
            }
            stderr = StringIO()
            with redirect_stderr(stderr):
                downloaded = cli.download_assets(request, root / "out")
            resolved = local.resolve()
            self.assertEqual(downloaded[:3], [resolved, resolved, resolved])
            self.assertEqual(len(downloaded), 4)
            copied = downloaded[3]
            self.assertEqual(copied.parent, root / "out" / "inputs")
            self.assertEqual(copied.read_bytes(), fetched.read_bytes())
            self.assertIn("Skipping missing asset file", stderr.getvalue())
            self.assertIn("Skipping asset download", stderr.getvalue())

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

    def test_build_set_proxy_emits_usd_bundle_without_blender(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            request = root / "request.json"
            request.write_text(json.dumps({
                "inputs": {
                    "spec": {
                        "id": "version_1",
                        "name": "Ferry Slip Proxy",
                        "locationId": "location_1",
                        "proxyType": "spatial",
                        "summary": "Reusable ferry slip blocking proxy.",
                        "boxes": [{
                            "name": "PierDeck",
                            "role": "floor",
                            "center": [0, 0, 0],
                            "size": [4, 0.1, 2],
                        }],
                        "cameraAnchors": [{
                            "name": "Master",
                            "label": "Master",
                            "transform": {"translate": [0, -8, 3]},
                        }],
                        "lightingRigs": [{"name": "Key", "label": "Key"}],
                    }
                }
            }))
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli.main([
                    "build-set-proxy",
                    "--request-json", str(request),
                    "--output-dir", str(root / "bundle"),
                    "--run-id", "unit-set-proxy",
                ])
            self.assertEqual(exit_code, 0, stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "succeeded")
            usd = (root / "bundle" / "proxy.usda").read_text()
            self.assertIn('def Xform "SetProxy"', usd)
            self.assertIn('def Mesh "PierDeck"', usd)
            self.assertIn('def Camera "Master"', usd)
            self.assertIn('def DistantLight "Key"', usd)
            labels = [item["label"] for item in payload["artifacts"]["items"]]
            self.assertEqual(labels[0], "usd-set-proxy")
            self.assertIn("set-proxy-manifest", labels)

    @unittest.skipUnless(cli.set_proxy.blender_binary(), "Blender is not installed")
    def test_render_set_plate_creates_editable_scene_and_camera_plate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            request = root / "request.json"
            request.write_text(json.dumps({
                "inputs": {
                    "spec": {
                        "id": "version_blender",
                        "name": "Minimal Stage",
                        "meshes": [{
                            "name": "FloorMesh",
                            "role": "floor",
                            "points": [[-2, -2, 0], [2, -2, 0], [2, 2, 0], [-2, 2, 0]],
                            "faceVertexCounts": [4],
                            "faceVertexIndices": [0, 1, 2, 3],
                        }],
                        "stagingZones": [{"name": "Blocking", "center": [0, 0, 0.05]}],
                        "maskRegions": [{"name": "Holdout", "center": [1, 1, 0.05]}],
                        "cameraAnchors": [{"name": "Master", "transform": {"translate": [0, -8, 3]}}],
                        "lightingRigs": [{"name": "Key", "type": "sun", "intensity": 3}],
                        "renderSettings": {"width": 64, "height": 64},
                    }
                }
            }))
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli.main([
                    "render-set-plate",
                    "--request-json", str(request),
                    "--output-dir", str(root / "render"),
                    "--run-id", "unit-blender-set",
                ])
            self.assertEqual(exit_code, 0, stderr.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "succeeded")
            self.assertTrue((root / "render" / "proxy.blend").is_file())
            self.assertEqual(len(list((root / "render" / "plates").glob("*.png"))), 1)


if __name__ == "__main__":
    unittest.main()

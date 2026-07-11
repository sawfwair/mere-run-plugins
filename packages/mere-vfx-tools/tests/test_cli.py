from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from PIL import Image, ImageDraw

from mere_vfx_tools import cli


def write_image(path: pathlib.Path, color: tuple[int, int, int, int] = (20, 220, 30, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (32, 24), color)
    ImageDraw.Draw(image).rectangle((8, 5, 23, 20), fill=(220, 40, 30, color[3]))
    image.save(path)


def write_request(path: pathlib.Path, inputs: dict[str, str], options: dict[str, object] | None = None) -> None:
    path.write_text(json.dumps({"inputs": inputs, "options": options or {}}))


def write_fake_mere_run(path: pathlib.Path) -> None:
    path.write_text(
        "import json, pathlib, sys\n"
        "from PIL import Image, ImageDraw\n"
        "args = sys.argv[1:]\n"
        "def value(flag): return args[args.index(flag) + 1]\n"
        "if args[:2] == ['vision', 'track']:\n"
        "    pathlib.Path(value('--output')).write_bytes(b'review')\n"
        "    raw = pathlib.Path(value('--mask-output-dir'))\n"
        "    frames = []\n"
        "    for index in range(2):\n"
        "        frame_dir = raw / f'frame-{index:06d}'\n"
        "        frame_dir.mkdir(parents=True, exist_ok=True)\n"
        "        mask_path = frame_dir / 'actor.png'\n"
        "        mask = Image.new('L', (32, 24), 0)\n"
        "        ImageDraw.Draw(mask).rectangle((7 + index, 4, 24, 21), fill=255)\n"
        "        mask.save(mask_path)\n"
        "        frames.append({'frameIndex': index, 'detections': [{'objectID': 'actor-1', 'label': 'actor', 'visible': True, 'box': [7 + index, 4, 17, 17], 'maskPath': str(mask_path)}]})\n"
        "    pathlib.Path(value('--json-output')).write_text(json.dumps({'fps': 24, 'frames': frames}))\n"
        "elif args[:2] == ['vision', 'pose']:\n"
        "    output = pathlib.Path(value('--json-output'))\n"
        "    output.parent.mkdir(parents=True, exist_ok=True)\n"
        "    output.write_text(json.dumps({'schemaVersion': 1, 'imageWidth': 32, 'imageHeight': 24, 'coordinateSpace': 'normalized-bottom-left', 'subjects': [{'kind': 'body', 'index': 0, 'confidence': 0.9, 'points': [{'name': 'head_joint', 'x': 0.5, 'y': 0.75, 'confidence': 0.8}]}, {'kind': 'hand', 'index': 0, 'confidence': 0.7, 'points': [{'name': 'wrist', 'x': 0.6, 'y': 0.4, 'confidence': 0.6}]}]}))\n"
        "elif args[:2] == ['vision', 'flow']:\n"
        "    flow = pathlib.Path(value('--output'))\n"
        "    metadata = pathlib.Path(value('--json-output'))\n"
        "    flow.parent.mkdir(parents=True, exist_ok=True)\n"
        "    flow.write_bytes(b'PIEH' + bytes(32))\n"
        "    metadata.write_text(json.dumps({'schemaVersion': 1, 'width': 32, 'height': 24, 'vectorCount': 768, 'meanMagnitude': 1.25, 'maximumMagnitude': 3.5, 'accuracy': value('--accuracy')}))\n"
        "elif args[:2] == ['video', 'generate']:\n"
        "    pathlib.Path(value('--output')).write_bytes(b'video')\n"
        "elif args[:2] == ['image', 'generate']:\n"
        "    output = pathlib.Path(value('--output'))\n"
        "    output.parent.mkdir(parents=True, exist_ok=True)\n"
        "    Image.new('RGB', (32, 24), (80, 100, 140)).save(output)\n"
        "else:\n"
        "    raise SystemExit('unexpected mere.run args: ' + repr(args))\n"
    )


def write_fake_ffmpeg(path: pathlib.Path) -> None:
    path.write_text(
        "import pathlib, sys\n"
        "from PIL import Image\n"
        "output = pathlib.Path(sys.argv[-1])\n"
        "if '%' in output.name:\n"
        "    output.parent.mkdir(parents=True, exist_ok=True)\n"
        "    for index in range(1, 3):\n"
        "        target = pathlib.Path(str(output).replace('%06d', f'{index:06d}'))\n"
        "        Image.new('RGB', (32, 24), (20 * index, 40, 80)).save(target)\n"
        "else:\n"
        "    output.parent.mkdir(parents=True, exist_ok=True)\n"
        "    output.write_bytes(b'encoded')\n"
    )


class MereVFXToolsTests(unittest.TestCase):
    def invoke(self, argv: list[str]) -> tuple[int, dict[str, object], str]:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        payload = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
        return code, payload, stderr.getvalue()

    def test_manifest_and_plan_contract(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        names = {command["name"] for command in manifest["commands"]}
        self.assertTrue(set(cli.TOOLS).issubset(names))
        self.assertEqual(manifest["security"]["cleanupDefault"], "none")
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            image = root / "mask.png"
            request = root / "request.json"
            write_image(image)
            write_request(request, {"masks": str(image)})
            code, payload, _ = self.invoke([
                "plan", "--tool", "matte-refine", "--request-json", str(request),
                "--output-dir", str(root / "out"), "--run-id", "vfx-plan",
                "--mere-run-command", "fake-mere", "--ffmpeg-command", "fake-ffmpeg",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["tool"]["name"], "matte-refine")
            self.assertTrue((root / "out" / "run.json").is_file())

    def test_matte_refine_key_and_qc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            frames = root / "frames"
            write_image(frames / "a.png", (0, 255, 0, 255))
            write_image(frames / "b.png", (250, 250, 250, 20))

            refine_request = root / "refine.json"
            write_request(refine_request, {"masks": str(frames)}, {"growPixels": 1, "chokePixels": 1, "featherRadius": 1.5})
            code, payload, _ = self.invoke([
                "matte-refine", "--request-json", str(refine_request), "--output-dir", str(root / "refined"),
                "--run-id", "refine-test", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "succeeded")
            self.assertEqual(len(list((root / "refined" / "refined-mattes").glob("*.png"))), 2)

            key_request = root / "key.json"
            write_request(key_request, {"images": str(frames)}, {"threshold": 15, "softness": 80, "despill": 1.0})
            code, payload, _ = self.invoke([
                "key", "--request-json", str(key_request), "--output-dir", str(root / "keyed"),
                "--run-id", "key-test", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 0)
            keyed = Image.open(root / "keyed" / "keyed" / "frame_000001.png").convert("RGBA")
            self.assertEqual(keyed.getpixel((0, 0))[3], 0)
            self.assertEqual(payload["status"], "succeeded")

            qc_request = root / "qc.json"
            write_request(qc_request, {"frames": str(frames)}, {"lumaJumpThreshold": 5, "alphaJumpThreshold": 0.1})
            code, payload, _ = self.invoke([
                "shot-qc", "--request-json", str(qc_request), "--output-dir", str(root / "qc"),
                "--run-id", "qc-test", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 0)
            report = json.loads((root / "qc" / "shot-qc.json").read_text())
            self.assertFalse(report["ok"])
            self.assertGreaterEqual(len(report["issues"]), 1)
            self.assertEqual(payload["status"], "succeeded")

    def test_track_export_writes_all_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            tracking = root / "tracking.json"
            tracking.write_text(json.dumps({
                "fps": 24,
                "frames": [{"frameIndex": 7, "detections": [{"objectID": "hero", "label": "actor", "box": [1, 2, 3, 4], "visible": True}]}],
            }))
            request = root / "request.json"
            write_request(request, {"trackingJson": str(tracking)})
            code, payload, _ = self.invoke([
                "track-export", "--request-json", str(request), "--output-dir", str(root / "export"),
                "--run-id", "track-export-test", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 0)
            self.assertTrue((root / "export" / "tracks.csv").is_file())
            self.assertTrue((root / "export" / "tracks-after-effects.json").is_file())
            self.assertTrue((root / "export" / "tracks-blender.json").is_file())
            self.assertEqual(len(payload["artifacts"]["items"]), 4)

    def test_roto_delivers_mattes_review_tracking_and_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            video = root / "shot.mov"
            video.write_bytes(b"source")
            request = root / "request.json"
            mere = root / "mere.py"
            ffmpeg = root / "ffmpeg.py"
            write_fake_mere_run(mere)
            write_fake_ffmpeg(ffmpeg)
            write_request(request, {"video": str(video)}, {"prompts": ["actor"], "alphaVideo": True, "featherRadius": 0.5})
            code, payload, stderr = self.invoke([
                "roto", "--request-json", str(request), "--output-dir", str(root / "roto"),
                "--run-id", "roto-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", f"{sys.executable} {ffmpeg}",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            self.assertTrue((root / "roto" / "roto-alpha.mov").is_file())
            self.assertEqual(len(list((root / "roto" / "mattes").glob("*.png"))), 2)
            self.assertEqual(payload["vfx"]["alphaFrameIndices"], [0, 1])
            self.assertRegex(payload["artifacts"]["items"][0]["sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_native_generation_orchestration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            start = root / "start.png"
            end = root / "end.png"
            write_image(start)
            write_image(end, (40, 60, 220, 255))
            mere = root / "mere.py"
            ffmpeg = root / "ffmpeg.py"
            write_fake_mere_run(mere)
            write_fake_ffmpeg(ffmpeg)
            mere_command = f"{sys.executable} {mere}"
            ffmpeg_command = f"{sys.executable} {ffmpeg}"

            request = root / "inbetween.json"
            write_request(request, {"startImage": str(start), "endImage": str(end)}, {"prompt": "actor turns", "numFrames": 17})
            code, payload, stderr = self.invoke([
                "inbetween", "--request-json", str(request), "--output-dir", str(root / "inbetween"),
                "--run-id", "inbetween-test", "--mere-run-command", mere_command, "--ffmpeg-command", ffmpeg_command,
            ])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "inbetween" / "inbetween.mp4").is_file())
            self.assertEqual(payload["status"], "succeeded")

            request = root / "turntable.json"
            write_request(request, {"image": str(start)}, {"prompt": "orbit clockwise"})
            code, payload, stderr = self.invoke([
                "turntable", "--request-json", str(request), "--output-dir", str(root / "turntable"),
                "--run-id", "turntable-test", "--mere-run-command", mere_command, "--ffmpeg-command", ffmpeg_command,
            ])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "turntable" / "turntable-contact-sheet.jpg").is_file())
            self.assertEqual(payload["status"], "succeeded")

            request = root / "character.json"
            write_request(request, {"referenceImage": str(start)}, {"views": ["front", "back"], "lora": "/tmp/hero.safetensors"})
            code, payload, stderr = self.invoke([
                "character-sheet", "--request-json", str(request), "--output-dir", str(root / "character"),
                "--run-id", "character-test", "--mere-run-command", mere_command, "--ffmpeg-command", ffmpeg_command,
            ])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "character" / "character-sheet.jpg").is_file())
            self.assertEqual(len(list((root / "character" / "character-views").glob("*.png"))), 2)
            self.assertEqual(payload["status"], "succeeded")

    def test_pose_sequence_exports_motion_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            frames = root / "frames"
            write_image(frames / "frame-1.png")
            write_image(frames / "frame-2.png", (40, 60, 220, 255))
            request = root / "pose.json"
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            write_request(request, {"frames": str(frames)}, {"fps": 12, "minimumConfidence": 0.2})
            code, payload, stderr = self.invoke([
                "pose-sequence", "--request-json", str(request), "--output-dir", str(root / "pose-out"),
                "--run-id", "pose-sequence-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            sequence = json.loads((root / "pose-out" / "pose-sequence.json").read_text())
            self.assertEqual(sequence["fps"], 12)
            self.assertEqual(len(sequence["frames"]), 2)
            after_effects = json.loads((root / "pose-out" / "pose-after-effects.json").read_text())
            self.assertEqual(after_effects["origin"], "top-left")
            self.assertEqual(len(after_effects["layers"]), 2)
            self.assertTrue((root / "pose-out" / "pose-blender.json").is_file())
            self.assertTrue((root / "pose-out" / "pose-sequence.csv").is_file())

    def test_motion_pass_exports_adjacent_native_flow_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            frames = root / "frames"
            write_image(frames / "frame-1.png")
            write_image(frames / "frame-2.png", (40, 60, 220, 255))
            write_image(frames / "frame-3.png", (220, 60, 40, 255))
            request = root / "motion.json"
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            write_request(request, {"frames": str(frames)}, {"fps": 12, "accuracy": "very-high"})
            code, payload, stderr = self.invoke([
                "motion-pass", "--request-json", str(request), "--output-dir", str(root / "motion-out"),
                "--run-id", "motion-pass-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            motion = json.loads((root / "motion-out" / "motion-pass.json").read_text())
            self.assertEqual(motion["flowCount"], 2)
            self.assertEqual(motion["accuracy"], "very-high")
            self.assertEqual(len(list((root / "motion-out" / "motion-flow").glob("*.flo"))), 2)
            self.assertRegex(motion["flows"][0]["flowSha256"], r"^sha256:[0-9a-f]{64}$")

    def test_clean_plate_preserves_pixels_outside_mask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            mask = root / "mask.png"
            write_image(source)
            matte = Image.new("L", (32, 24), 0)
            ImageDraw.Draw(matte).rectangle((10, 7, 20, 18), fill=255)
            matte.save(mask)
            request = root / "clean-plate.json"
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            write_request(
                request,
                {"images": str(source), "masks": str(mask)},
                {"featherRadius": 0, "growPixels": 0, "boundingBoxPadding": 0},
            )
            code, payload, stderr = self.invoke([
                "clean-plate", "--request-json", str(request), "--output-dir", str(root / "clean-out"),
                "--run-id", "clean-plate-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "clean-out" / "clean-plate.json").read_text())
            self.assertEqual(delivery["maskMode"], "bounding-box")
            self.assertTrue(delivery["colorMatched"])
            self.assertRegex(delivery["frames"][0]["cleanPlateSha256"], r"^sha256:[0-9a-f]{64}$")
            result = Image.open(root / "clean-out" / "clean-plates" / "frame_000001.png").convert("RGB")
            original = Image.open(source).convert("RGB")
            self.assertEqual(result.getpixel((0, 0)), original.getpixel((0, 0)))
            self.assertNotEqual(result.getpixel((15, 10)), original.getpixel((15, 10)))

    def test_set_extension_preserves_source_and_restore_upscales(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            write_image(source)
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            mere_command = f"{sys.executable} {mere}"

            request = root / "extension.json"
            write_request(request, {"image": str(source)}, {"width": 64, "height": 48, "edgeFeather": 0})
            code, payload, stderr = self.invoke([
                "set-extension", "--request-json", str(request), "--output-dir", str(root / "extension-out"),
                "--run-id", "set-extension-test", "--mere-run-command", mere_command,
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            extended = Image.open(root / "extension-out" / "set-extension.png").convert("RGB")
            original = Image.open(source).convert("RGB")
            self.assertEqual(extended.size, (64, 48))
            self.assertEqual(extended.crop((16, 12, 48, 36)).tobytes(), original.tobytes())

            request = root / "restore.json"
            write_request(request, {"images": str(source)}, {"scale": 2})
            code, payload, stderr = self.invoke([
                "restore", "--request-json", str(request), "--output-dir", str(root / "restore-out"),
                "--run-id", "restore-test", "--mere-run-command", mere_command,
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            with Image.open(root / "restore-out" / "restored" / "frame_000001.png") as restored:
                self.assertEqual(restored.size, (64, 48))
            delivery = json.loads((root / "restore-out" / "restoration.json").read_text())
            self.assertTrue(delivery["synthesizedDetail"])
            self.assertFalse(delivery["identityPreservationGuaranteed"])
            self.assertRegex(delivery["frames"][0]["sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertTrue((root / "restore-out" / "upscale-baseline" / "frame_000001.png").is_file())

    def test_depth_normal_exports_hashed_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            write_image(source)
            mere = root / "mere.py"
            write_fake_mere_run(mere)
            request = root / "depth.json"
            write_request(request, {"images": str(source)}, {"normalStrength": 3})
            code, payload, stderr = self.invoke([
                "depth-normal", "--request-json", str(request), "--output-dir", str(root / "depth-out"),
                "--run-id", "depth-normal-test", "--mere-run-command", f"{sys.executable} {mere}",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "depth-out" / "depth-normal.json").read_text())
            self.assertFalse(delivery["metricDepth"])
            self.assertEqual(delivery["depthSource"], "generative proxy")
            self.assertRegex(delivery["frames"][0]["normalSha256"], r"^sha256:[0-9a-f]{64}$")
            normal = Image.open(root / "depth-out" / "normals" / "frame_000001.png").convert("RGB")
            self.assertEqual(normal.getpixel((16, 12)), (127, 127, 255))

    def test_relight_exports_diffuse_and_shadow_catcher_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            normal = root / "normal.png"
            mask = root / "mask.png"
            write_image(source)
            Image.new("RGB", (32, 24), (128, 128, 255)).save(normal)
            matte = Image.new("L", (32, 24), 0)
            ImageDraw.Draw(matte).rectangle((8, 5, 23, 20), fill=255)
            matte.save(mask)
            request = root / "relight.json"
            write_request(
                request,
                {"images": str(source), "normalMaps": str(normal), "masks": str(mask)},
                {
                    "lightDirection": [0, 0, 1],
                    "ambient": 0.25,
                    "intensity": 0.75,
                    "shadowOffsetX": 2,
                    "shadowOffsetY": 2,
                    "shadowScaleX": 1.2,
                    "shadowScaleY": 0.25,
                    "shadowBlur": 1,
                },
            )
            code, payload, stderr = self.invoke([
                "relight", "--request-json", str(request), "--output-dir", str(root / "relight-out"),
                "--run-id", "relight-test", "--mere-run-command", "missing-mere",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "relight-out" / "relight.json").read_text())
            self.assertEqual(delivery["shadowMode"], "projected-matte-proxy")
            self.assertRegex(delivery["frames"][0]["shadowCatcherSha256"], r"^sha256:[0-9a-f]{64}$")
            shadow = Image.open(root / "relight-out" / "shadow-catchers" / "frame_000001.png").convert("RGBA")
            self.assertGreater(shadow.getchannel("A").getextrema()[1], 0)
            self.assertTrue((root / "relight-out" / "shadow-previews" / "frame_000001.png").is_file())

    def test_image_to_3d_exports_point_cloud_and_mesh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source.png"
            depth = root / "depth.png"
            write_image(source)
            Image.new("L", (32, 24), 128).save(depth)
            request = root / "geometry.json"
            write_request(request, {"images": str(source), "depthImages": str(depth)}, {"stride": 8})
            code, payload, stderr = self.invoke([
                "image-to-3d", "--request-json", str(request), "--output-dir", str(root / "geometry-out"),
                "--run-id", "image-to-3d-test", "--mere-run-command", "missing-mere",
                "--ffmpeg-command", "missing-ffmpeg",
            ])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(payload["status"], "succeeded")
            delivery = json.loads((root / "geometry-out" / "image-to-3d.json").read_text())
            self.assertFalse(delivery["metricGeometry"])
            self.assertEqual(delivery["frames"][0]["vertexCount"], 12)
            self.assertEqual(delivery["frames"][0]["faceCount"], 12)
            self.assertTrue((root / "geometry-out" / "geometry" / "frame_000001.ply").is_file())
            self.assertTrue((root / "geometry-out" / "geometry" / "frame_000001.obj").is_file())

    def test_resume_cleanup_dry_run_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            image = root / "mask.png"
            request = root / "request.json"
            write_image(image)
            write_request(request, {"masks": str(image)})
            common = [
                "--request-json", str(request), "--output-dir", str(root / "out"), "--run-id", "lifecycle-test",
                "--mere-run-command", "missing-mere", "--ffmpeg-command", "missing-ffmpeg",
            ]
            code, payload, _ = self.invoke(["matte-refine", *common, "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "planned")
            manifest = root / "out" / "run.json"
            code, payload, _ = self.invoke(["resume", str(manifest)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "planned")
            code, payload, _ = self.invoke(["cleanup", str(manifest)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["cleanup"]["status"], "skipped")
            code, payload, _ = self.invoke(["doctor", "--mere-run-command", "missing-mere", "--ffmpeg-command", "missing-ffmpeg"])
            self.assertEqual(code, 3)
            self.assertFalse(payload["ok"])
            code, _, stderr = self.invoke([
                "plan", "--tool", "matte-refine", "--request-json", str(request), "--output-dir", str(root / "bad"),
                "--run-id", "bad id", "--mere-run-command", "fake", "--ffmpeg-command", "fake",
            ])
            self.assertEqual(code, 2)
            self.assertIn("invalid --run-id", stderr)


if __name__ == "__main__":
    unittest.main()

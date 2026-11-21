from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from mere_vfx_tools import cli


class IdolHandoffTests(unittest.TestCase):
    def test_native_gaussian_assets_and_validation(self) -> None:
        properties = (
            "x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
            "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
        )
        checkpoints = (
            "birefnet.safetensors", "denoiser.safetensors", "decoder.safetensors",
            "decoder_gs.safetensors", "idol/config.json", "dinov3/config.json", "dinov3/model.safetensors",
            "flux2-vae/config.json", "flux2-vae/diffusion_pytorch_model.safetensors",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.png"
            Image.new("RGB", (12, 8)).save(source)
            reported_source = root / "source-alias.png"
            reported_source.symlink_to(source)
            request = root / "request.json"
            request.write_text(json.dumps({
                "inputs": {"image": str(source)},
                "options": {
                    "reconstructionMode": "native-idol", "model": directory, "dino": directory, "vae": directory,
                    "numGaussians": 32768, "inputMode": "real", "steps": 12, "seed": 7, "alreadyFramed": True,
                },
            }))

            def native_run(argv: list[str], label: str) -> cli.JsonMap:
                self.assertEqual(label, "mere.run vision image-to-3d-idol")
                self.assertEqual(argv[1:4], ["vision", "image-to-3d-idol", str(source)])
                self.assertEqual(argv[-2:], ["--already-framed", "--json"])
                self.assertEqual(argv[argv.index("--mode") + 1], "real")
                output = Path(argv[argv.index("--output") + 1])
                output.mkdir()
                ply = output / "object.ply"
                header = "ply\nformat binary_little_endian 1.0\nelement vertex 32768\n"
                header += "".join(f"property float {name}\n" for name in properties)
                payload = bytes(32768 * len(properties) * 4)
                if output.parent.name == "short-ply":
                    payload = payload[:-4]
                ply.write_bytes((header + "end_header\n").encode() + payload)
                Image.new("RGB", (1024, 1024)).save(output / "input.png")
                camera = {"yaw": 0, "pitch": 0, "radius": 2, "fov": 34}
                (output / "camera.json").write_text(json.dumps(camera))
                document: cli.JsonMap = {
                    "schemaVersion": 1, "status": "completed", "backend": "mere.run-native-mlx",
                    "repository": "speridlabs/idol", "revision": "a" * 40, "referenceRevision": "b" * 40,
                    "inputPath": str(reported_source), "inputSHA256": cli.sha256(source)[7:], "mode": "real",
                    "alreadyFramed": True, "gaussianCount": 32768, "camera": camera,
                    "settings": {"steps": 12, "seed": 7, "gaussianCount": 32768},
                    "checkpoints": [{"filename": name, "byteCount": 1, "sha256": "1" * 64} for name in checkpoints],
                    "artifacts": [
                        {"filename": path.name, "sha256": cli.sha256(path)[7:], "byteCount": path.stat().st_size}
                        for path in (ply, output / "input.png", output / "camera.json")
                    ],
                }
                (output / "manifest.json").write_text(json.dumps(document))
                if output.parent.name == "modified-camera":
                    (output / "camera.json").write_text("{}")
                return document

            for name, expected, diagnostic in (
                ("good", 0, ""),
                ("short-ply", 1, "binary Gaussian-splat PLY"),
                ("modified-camera", 1, "does not match its recorded bytes"),
            ):
                with self.subTest(name=name), patch.object(cli, "run_json_process", side_effect=native_run):
                    output = root / name
                    stderr = StringIO()
                    with redirect_stdout(StringIO()), redirect_stderr(stderr):
                        result = cli.main([
                            "image-to-3d", "--request-json", str(request), "--output-dir", str(output),
                        ])
                    self.assertEqual(result, expected, stderr.getvalue())
                    self.assertIn(diagnostic, stderr.getvalue())
                    handoff = output / "image-to-3d.json"
                    self.assertEqual(handoff.is_file(), expected == 0)
                    if expected == 0:
                        delivery = json.loads(handoff.read_text())
                        self.assertEqual(delivery["representation"], "gaussian-splats")
                        self.assertEqual(delivery["coordinateSystem"], "model-y-up")
                        self.assertEqual(delivery["camera"]["coordinateSystem"], "model-z-up")
                        self.assertEqual(delivery["assets"]["splat"]["sha256"], cli.sha256(output / "native-idol/object.ply"))

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

from mere_geo_tools import embedding_runtime, runtime
from mere_geo_tools.constants import OLMOEARTH_MODELS, TESSERA_MODELS
from mere_workflow_tools.graph_sdk import GraphProviderError


class NativeTilingTests(unittest.TestCase):
    def test_tiling_reconstructs_spatial_logits_without_seams(self) -> None:
        height = 256
        width = 320
        spatial = np.arange(height * width, dtype=np.float32).reshape(height, width) / 10_000
        inputs = {
            "S2L2A": np.broadcast_to(spatial, (1, 12, 4, height, width)).copy(),
            "S1RTC": np.zeros((1, 2, 4, height, width), dtype=np.float32),
            "DEM": np.zeros((1, 1, 4, height, width), dtype=np.float32),
        }
        batches: list[int] = []

        def fixture_forward(
            batch: dict[str, np.ndarray], _executable: str, _model_root: str | None
        ) -> tuple[np.ndarray, dict[str, object]]:
            batches.append(batch["S2L2A"].shape[0])
            logits = np.zeros((batch["S2L2A"].shape[0], 2, 256, 256), dtype=np.float32)
            logits[:, 1] = batch["S2L2A"][:, 0, 0]
            return logits, {"status": "completed", "device": "metal"}

        with mock.patch.object(runtime, "native_flood_forward", side_effect=fixture_forward):
            logits, native_runs = runtime.tiled_native_inference(inputs, "/tmp/mere.run", None)

        self.assertEqual(batches, [4])
        self.assertEqual(len(native_runs), 1)
        np.testing.assert_allclose(logits[0, 1], spatial, rtol=1e-6, atol=1e-6)

    def test_fire_tiling_routes_to_the_fire_native_command(self) -> None:
        inputs = {
            "S2L2A": np.zeros((1, 12, 4, 256, 256), dtype=np.float32),
            "S1RTC": np.zeros((1, 2, 4, 256, 256), dtype=np.float32),
            "DEM": np.zeros((1, 1, 4, 256, 256), dtype=np.float32),
        }

        def fixture_forward(
            batch: dict[str, np.ndarray], _executable: str, _model_root: str | None, command: str
        ) -> tuple[np.ndarray, dict[str, object]]:
            self.assertEqual(command, "fire")
            return (
                np.zeros((batch["S2L2A"].shape[0], 2, 256, 256), dtype=np.float32),
                {"status": "completed", "model_id": "vision-fire-terramind-base"},
            )

        with mock.patch.object(runtime, "native_hazard_forward", side_effect=fixture_forward) as forward:
            logits, runs = runtime.tiled_native_inference(inputs, "/tmp/mere.run", None, command="fire")
        self.assertEqual(tuple(logits.shape), (1, 2, 256, 256))
        self.assertEqual(runs[0]["model_id"], "vision-fire-terramind-base")
        forward.assert_called_once()

    def test_runtime_helpers_validate_boundaries_and_compute_local_cues(self) -> None:
        self.assertEqual(runtime.artifact_path({"S2": {"path": "S2/input.zip"}}, "S2"), "S2/input.zip")
        with self.assertRaises(GraphProviderError):
            runtime.artifact_path({"S2": {"path": 42}}, "S2")
        self.assertEqual(runtime.numeric_value(10, "resolution"), 10.0)
        with self.assertRaises(GraphProviderError):
            runtime.numeric_value(True, "resolution")

        normalized = runtime.normalized_array(
            np.ones((1, 1, 2, 2), dtype=np.float32), [1.0], [2.0]
        )
        self.assertEqual(tuple(normalized.shape), (1, 1, 1, 2, 2))
        self.assertTrue(np.all(normalized == 0))
        self.assertTrue(np.all(runtime.blend_mask(4, 4, 0) > 0))

        s2 = np.zeros((3, 8, 2, 2), dtype=np.float32)
        s2[1, 7] = 1.0
        s2[1, 3] = 1.0
        s2[2, 3] = 1.0
        mask = np.array([[1, 0], [0, 0]], dtype=np.uint8)
        cue = runtime.ndvi_comparison(s2, mask)
        self.assertEqual(cue["cue_pixels"], 4)
        self.assertEqual(cue["intersection_pixels"], 1)

    def test_runtime_executable_override_is_confined_to_real_executables(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            executable = pathlib.Path(raw_root) / "mere.run"
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o755)
            with mock.patch.dict("os.environ", {"MERE_RUN_EXECUTABLE": str(executable)}, clear=True):
                self.assertEqual(runtime.resolve_mere_run_executable(), str(executable.resolve()))
            with mock.patch.dict("os.environ", {"MERE_RUN_EXECUTABLE": str(executable) + "-missing"}, clear=True):
                self.assertIsNone(runtime.resolve_mere_run_executable())
            with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(
                runtime.shutil, "which", return_value="/usr/local/bin/mere.run"
            ):
                self.assertEqual(runtime.resolve_mere_run_executable(), "/usr/local/bin/mere.run")

    def test_tiling_rejects_invalid_input_and_native_shapes(self) -> None:
        with self.assertRaisesRegex(GraphProviderError, "B,C,T,H,W"):
            runtime.tiled_native_inference({}, "/tmp/mere.run", None)
        mismatched = {
            "S2L2A": np.zeros((1, 1, 1, 256, 256), dtype=np.float32),
            "DEM": np.zeros((1, 1, 1, 256, 300), dtype=np.float32),
        }
        with self.assertRaisesRegex(GraphProviderError, "share batch"):
            runtime.tiled_native_inference(mismatched, "/tmp/mere.run", None)
        valid = {"S2L2A": np.zeros((1, 1, 1, 256, 256), dtype=np.float32)}
        with mock.patch.object(
            runtime,
            "native_flood_forward",
            return_value=(np.zeros((1, 1, 2, 2), dtype=np.float32), {}),
        ), self.assertRaisesRegex(GraphProviderError, "invalid shape"):
            runtime.tiled_native_inference(valid, "/tmp/mere.run", None)

    def test_native_handoff_reports_process_and_payload_failures(self) -> None:
        inputs = {"S2L2A": np.zeros((1, 1, 1, 2, 2), dtype=np.float32)}
        safetensors_package = types.ModuleType("safetensors")
        safetensors_numpy = types.ModuleType("safetensors.numpy")
        safetensors_numpy.save_file = mock.Mock()
        safetensors_numpy.load_file = mock.Mock(return_value={})
        with mock.patch.dict(
            sys.modules,
            {"safetensors": safetensors_package, "safetensors.numpy": safetensors_numpy},
        ):
            failed = mock.Mock(returncode=2, stderr="native failed", stdout="")
            with mock.patch.object(runtime.subprocess, "run", return_value=failed):
                with self.assertRaisesRegex(GraphProviderError, "native failed"):
                    runtime.native_hazard_forward(inputs, "/tmp/mere.run", None, "fire")

            invalid = mock.Mock(returncode=0, stderr="", stdout="not-json")
            with mock.patch.object(runtime.subprocess, "run", return_value=invalid):
                with self.assertRaisesRegex(GraphProviderError, "invalid JSON"):
                    runtime.native_hazard_forward(inputs, "/tmp/mere.run", None, "flood")

            completed = mock.Mock(returncode=0, stderr="", stdout='{"status":"completed","device":"metal"}')
            with mock.patch.object(runtime.subprocess, "run", return_value=completed):
                with self.assertRaisesRegex(GraphProviderError, "did not emit logits"):
                    runtime.native_hazard_forward(inputs, "/tmp/mere.run", "/models/flood", "flood")

            logits = np.ones((1, 2, 2, 2), dtype=np.float64)
            safetensors_numpy.load_file = mock.Mock(return_value={"logits": logits})
            with mock.patch.object(runtime.subprocess, "run", return_value=completed):
                output, metadata = runtime.native_flood_forward(inputs, "/tmp/mere.run", None)
        self.assertEqual(output.dtype, np.float32)
        self.assertEqual(metadata["device"], "metal")


class EmbeddingRuntimeTests(unittest.TestCase):
    def test_tessera_pixel_batch_applies_cloud_valid_temporal_sampling(self) -> None:
        s2 = np.arange(3 * 10 * 1 * 2, dtype=np.float32).reshape(3, 10, 1, 2)
        valid = np.array([[[1, 0]], [[0, 1]], [[1, 0]]], dtype=np.uint8)
        radar = {"S1_ASC": np.arange(2 * 2 * 1 * 2, dtype=np.float32).reshape(2, 2, 1, 2)}
        bundle = {"S2_DOY": [10, 20, 30], "S1_ASC_DOY": [11, 21]}
        batch = embedding_runtime.tessera_pixel_batch(
            bundle,
            s2,
            valid,
            radar,
            np.array([0, 1], dtype=np.int64),
            8,
        )
        self.assertEqual(tuple(batch["S2"].shape), (2, 8, 10))
        self.assertEqual(tuple(batch["S1_ASC"].shape), (2, 2, 2))
        self.assertEqual(batch["S2_DOY"][0, 0], 10)
        self.assertEqual(batch["S2_DOY"][0, -1], 30)
        self.assertTrue(np.all(batch["S2_DOY"][1] == 20))

    def test_sequence_bucket_scales_to_full_annual_history(self) -> None:
        self.assertIsNone(embedding_runtime.sequence_bucket(0))
        self.assertEqual(embedding_runtime.sequence_bucket(1), 8)
        self.assertEqual(embedding_runtime.sequence_bucket(17), 32)
        self.assertEqual(embedding_runtime.sequence_bucket(256), 256)

    def test_native_tessera_handoff_preserves_explicit_tier_and_dimensions(self) -> None:
        payload = {
            "status": "completed",
            "model_id": "vision-embed-tessera-v2-large",
            "variant": "large",
            "batch_size": 2,
            "device": "metal",
        }
        arrays = {"embeddings": np.ones((2, 64), dtype=np.float32)}
        inputs = {
            "S2": np.zeros((2, 8, 10), dtype=np.float32),
            "S2_DOY": np.ones((2, 8), dtype=np.int32),
            "S1_ASC": np.zeros((2, 2, 2), dtype=np.float32),
            "S1_ASC_DOY": np.ones((2, 2), dtype=np.int32),
        }
        with mock.patch.object(embedding_runtime, "save_safetensors"), mock.patch.object(
            embedding_runtime, "run_native", return_value=payload
        ) as run, mock.patch.object(embedding_runtime, "load_safetensors", return_value=arrays):
            embeddings, metadata = embedding_runtime.native_tessera_forward(
                inputs,
                "/tmp/mere.run",
                "vision-embed-tessera-v2-large",
                64,
            )
        command = run.call_args.args[0]
        self.assertIn("vision-embed-tessera-v2-large", command)
        self.assertEqual(command[command.index("--dimensions") + 1], "64")
        self.assertEqual(tuple(embeddings.shape), (2, 64))
        self.assertEqual(metadata["variant"], "large")

    def test_native_olmoearth_handoff_preserves_spatial_controls(self) -> None:
        inputs = {
            "TIMESTAMPS": np.array([[[1, 0, 2026]]], dtype=np.int32),
            "S2L2A": np.zeros((1, 8, 8, 1, 12), dtype=np.float32),
        }
        def run_fixture(command: list[str], _name: str, timeout: int) -> dict[str, object]:
            self.assertEqual(timeout, 3_600)
            pathlib.Path(command[command.index("--output") + 1]).write_bytes(b"embeddings")
            return {"status": "completed", "model_id": "vision-embed-olmoearth-v12-base"}

        with tempfile.TemporaryDirectory() as raw_directory:
            output_path = pathlib.Path(raw_directory) / "embeddings"
            with mock.patch.object(embedding_runtime, "save_safetensors"), mock.patch.object(
                embedding_runtime,
                "run_native",
                side_effect=run_fixture,
            ) as run:
                embedding_runtime.native_olmoearth_forward(
                    inputs,
                    output_path,
                    "/tmp/mere.run",
                    "vision-embed-olmoearth-v12-base",
                    2,
                    10.0,
                    True,
                )
            self.assertEqual(output_path.read_bytes(), b"embeddings")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--patch-size") + 1], "2")
        self.assertTrue(command[command.index("--output") + 1].endswith(".safetensors"))
        self.assertIn("--include-tokens", command)

    def test_execute_tessera_embedding_builds_spatial_manifest(self) -> None:
        model_id = str(TESSERA_MODELS["nano"]["id"])
        bundle = {
            "input_digest": "digest",
            "sources": {},
            "grid": {"height": 2, "width": 2, "crs": "EPSG:32617", "resolution_m": 10},
            "artifacts": {
                "S2": {"path": "S2/input.zip"},
                "S2_VALID": {"path": "S2_VALID/input.zip"},
                "S1_ASC": {"path": "S1_ASC/input.zip"},
            },
            "S2_DOY": [10, 20],
            "S1_ASC_DOY": [11, 21],
        }
        s2 = np.ones((2, 10, 2, 2), dtype=np.float32)
        valid = np.ones((2, 2, 2), dtype=np.uint8)
        radar = np.ones((2, 2, 2, 2), dtype=np.float32)
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            locations = {"embeddings": root / "embeddings.safetensors", "manifest": root / "manifest.json"}

            def save_fixture(
                _arrays: dict[str, np.ndarray], path: pathlib.Path, _metadata: dict[str, str]
            ) -> None:
                path.write_bytes(b"embeddings")

            with mock.patch.object(embedding_runtime, "load_bundle", return_value=bundle), mock.patch.object(
                embedding_runtime, "load_zarr", side_effect=[s2, valid, radar]
            ), mock.patch.object(embedding_runtime, "require_runtime", return_value="/tmp/mere.run"), mock.patch.object(
                embedding_runtime,
                "native_tessera_forward",
                return_value=(np.ones((4, 16), dtype=np.float32), {"model_id": model_id}),
            ), mock.patch.object(embedding_runtime, "save_safetensors", side_effect=save_fixture):
                result = embedding_runtime.execute_tessera_embedding(root, locations, "metal", None, 16, 8)

            manifest = json.loads(locations["manifest"].read_text())
            self.assertEqual(manifest["summary"]["dimensions"], 16)
            self.assertEqual(result.metrics["value"], 1.0)

    def test_execute_olmoearth_embedding_builds_spatial_manifest(self) -> None:
        model_id = str(OLMOEARTH_MODELS["base"]["id"])
        bundle = {
            "input_digest": "digest",
            "sources": {},
            "timestamps": [[1, 0, 2026]],
            "grid": {"height": 4, "width": 4, "crs": "EPSG:32617", "resolution_m": 10},
            "artifacts": {"S2L2A": {"path": "S2L2A/input.zip"}},
        }
        s2 = np.ones((1, 12, 4, 4), dtype=np.float32)
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            locations = {"embeddings": root / "embeddings.safetensors", "manifest": root / "manifest.json"}

            def native_fixture(
                _inputs: dict[str, np.ndarray],
                output_path: pathlib.Path,
                _executable: str,
                _model: str | None,
                _patch_size: int,
                _resolution: float,
                _include_tokens: bool,
            ) -> dict[str, object]:
                output_path.write_bytes(b"embeddings")
                return {"status": "completed", "model_id": model_id}

            with mock.patch.object(embedding_runtime, "load_bundle", return_value=bundle), mock.patch.object(
                embedding_runtime, "load_zarr", return_value=s2
            ), mock.patch.object(embedding_runtime, "require_runtime", return_value="/tmp/mere.run"), mock.patch.object(
                embedding_runtime, "native_olmoearth_forward", side_effect=native_fixture
            ), mock.patch.object(
                embedding_runtime,
                "load_safetensors",
                return_value={"S2L2A_EMBEDDINGS": np.ones((1, 2, 2, 8), dtype=np.float32)},
            ):
                result = embedding_runtime.execute_olmoearth_embedding(
                    root, locations, "auto", None, 2, None, True
                )

            manifest = json.loads(locations["manifest"].read_text())
            self.assertEqual(manifest["summary"]["grid_height"], 2)
            self.assertEqual(result.metrics["value"], 4)

    def test_embedding_runtime_rejects_invalid_controls_and_native_results(self) -> None:
        with self.assertRaises(GraphProviderError):
            embedding_runtime.require_metal("cpu", "TESSERA")
        with mock.patch.object(embedding_runtime, "resolve_mere_run_executable", return_value=None):
            with self.assertRaises(GraphProviderError):
                embedding_runtime.require_runtime("TESSERA")
        self.assertEqual(embedding_runtime.sequence_bucket(999), 256)
        self.assertEqual(
            embedding_runtime.native_metadata({"status": "completed", "ignored": True}),
            {"status": "completed"},
        )
        self.assertEqual(
            embedding_runtime.model_manifest(TESSERA_MODELS, "missing")["native_model_id"],
            "missing",
        )

        with mock.patch.object(embedding_runtime.subprocess, "run", side_effect=OSError("missing")):
            with self.assertRaisesRegex(GraphProviderError, "missing"):
                embedding_runtime.run_native(["mere.run"], "tessera", 1)
        failed = mock.Mock(returncode=1, stderr="boom", stdout="")
        with mock.patch.object(embedding_runtime.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(GraphProviderError, "boom"):
                embedding_runtime.run_native(["mere.run"], "tessera", 1)
        invalid = mock.Mock(returncode=0, stderr="", stdout="[]")
        with mock.patch.object(embedding_runtime.subprocess, "run", return_value=invalid):
            with self.assertRaisesRegex(GraphProviderError, "invalid JSON"):
                embedding_runtime.run_native(["mere.run"], "tessera", 1)


if __name__ == "__main__":
    unittest.main()

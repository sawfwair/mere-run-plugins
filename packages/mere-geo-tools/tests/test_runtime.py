from __future__ import annotations

import pathlib
import unittest
from unittest import mock

import numpy as np

from mere_geo_tools import embedding_runtime, runtime


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
        with mock.patch.object(embedding_runtime, "save_safetensors"), mock.patch.object(
            embedding_runtime,
            "run_native",
            return_value={"status": "completed", "model_id": "vision-embed-olmoearth-v12-base"},
        ) as run:
            embedding_runtime.native_olmoearth_forward(
                inputs,
                pathlib.Path("/tmp/output.safetensors"),
                "/tmp/mere.run",
                "vision-embed-olmoearth-v12-base",
                2,
                10.0,
                True,
            )
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--patch-size") + 1], "2")
        self.assertIn("--include-tokens", command)


if __name__ == "__main__":
    unittest.main()

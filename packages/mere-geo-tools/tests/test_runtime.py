from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from mere_geo_tools import runtime


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


if __name__ == "__main__":
    unittest.main()

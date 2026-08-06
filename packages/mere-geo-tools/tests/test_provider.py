from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from mere_geo_tools import cli, prepare, provider
from mere_geo_tools.bundle import BUNDLE_KIND, BUNDLE_VERSION, canonical_digest, load_bundle, sha256_file
from mere_geo_tools.constants import MODEL_ID, MODEL_REVISION, S1_BANDS, S2_BANDS, TEMPORAL_ROLES
from mere_workflow_tools.graph_sdk import (
    GraphProviderError,
    validate_catalog,
    validate_event_stream,
    validate_preflight,
)


class GeoProviderTests(unittest.TestCase):
    def source_recipe(self, crs: str = "EPSG:32617") -> dict[str, object]:
        return {
            "kind": "mere.geo/terramind-flood-source-recipe",
            "version": 1,
            "sample_id": "fixture",
            "target": {"aoi": [32.6772, 46.5981, 32.7801, 46.6358], "crs": crs},
            "timesteps": [
                {
                    "role": role,
                    "S2L2A": {"collection": "sentinel-2-l2a", "item": f"s2-{role}"},
                    "S1RTC": {"collection": "sentinel-1-rtc", "item": f"s1-{role}"},
                }
                for role in TEMPORAL_ROLES
            ],
            "DEM": {"collection": "cop-dem-glo-30", "item": "dem"},
        }

    def make_bundle(self, root: pathlib.Path) -> pathlib.Path:
        bundle = root / "bundle"
        bundle.mkdir(parents=True)
        files = {
            "S2L2A": "S2L2A/fixture_S2L2A.zarr.zip",
            "S1RTC": "S1RTC/fixture_S1RTC.zarr.zip",
            "DEM": "DEM/fixture_DEM.tif",
        }
        artifacts = {}
        entries = []
        for name, relative in files.items():
            path = bundle / relative
            path.parent.mkdir()
            path.write_bytes(f"fixture-{name}".encode())
            digest = sha256_file(path)
            artifacts[name] = {"path": relative, "bytes": path.stat().st_size, "sha256": digest}
            entries.append({"name": name, "path": relative, "sha256": digest})
        grid = {
            "crs": "EPSG:32617",
            "transform": [10, 0, 385000, 0, -10, 3924000],
            "width": 256,
            "height": 256,
            "resolution_m": 10,
        }
        manifest = {
            "kind": BUNDLE_KIND,
            "version": BUNDLE_VERSION,
            "sample_id": "fixture",
            "model": {"id": MODEL_ID, "revision": MODEL_REVISION},
            "grid": grid,
            "timesteps": [{"role": role} for role in TEMPORAL_ROLES],
            "modalities": {
                "S2L2A": {"bands": S2_BANDS, "shape": [4, 12, 256, 256]},
                "S1RTC": {"bands": S1_BANDS, "shape": [4, 2, 256, 256]},
                "DEM": {"bands": ["elevation"], "shape": [1, 256, 256]},
            },
            "artifacts": artifacts,
            "input_digest": canonical_digest(entries),
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest))
        return bundle

    def invocation(self, bundle: pathlib.Path) -> dict[str, object]:
        return {
            "contract_version": "mere.run/plugin-graph-invocation.v1",
            "kind": provider.NODE_KIND,
            "arguments": {"input_bundle": str(bundle), "device": "auto"},
            "outputs": {
                "mask": {"type": "asset", "path": "artifacts/flood-mask.tif"},
                "probability": {"type": "asset", "path": "artifacts/flood-probability.tif"},
                "manifest": {"type": "asset", "path": "artifacts/flood-candidate.json"},
                "preview": {"type": "asset", "path": "artifacts/flood-preview.png"},
            },
        }

    def test_catalog_and_plugin_manifest_expose_candidate_provider(self) -> None:
        value = provider.catalog()
        validate_catalog(value)
        self.assertEqual(value["provider_id"], "mere-geo-tools")
        self.assertEqual(value["nodes"][0]["kind"], "geo.flood.segment")
        self.assertIn("metal", value["nodes"][0]["requirements"]["accelerator_backends"])
        self.assertEqual(
            value["nodes"][0]["requirements"]["model_ids"],
            ["vision-flood-terramind-base"],
        )
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["graphProvider"]["contractVersion"], "mere.run/plugin-graph-provider.v1")
        self.assertIn("flood-segmentation", manifest["capabilities"])

    def test_doctor_requires_only_native_provider_dependencies(self) -> None:
        with mock.patch(
            "mere_geo_tools.runtime.resolve_mere_run_executable", return_value="/tmp/mere.run"
        ), mock.patch.object(cli.importlib.util, "find_spec", return_value=object()), mock.patch.object(
            cli.platform, "system", return_value="Darwin"
        ):
            report = cli.doctor_report()

        self.assertEqual(set(report["modules"]), {"numpy", "rasterio", "safetensors", "zarr"})
        self.assertNotIn("impactmesh", report["modules"])
        self.assertEqual(report["native_runtime"]["command"], "mere.run geo flood")
        self.assertEqual(report["native_runtime"]["accelerator"], "metal")

    def test_source_recipe_accepts_projected_crs_for_arbitrary_aoi(self) -> None:
        prepare.validate_recipe(self.source_recipe("EPSG:32617"))
        prepare.validate_recipe(self.source_recipe("EPSG:32636"))

    def test_source_recipe_rejects_invalid_aoi_and_non_metric_crs(self) -> None:
        reversed_aoi = self.source_recipe("EPSG:32636")
        reversed_aoi["target"]["aoi"] = [32.7801, 46.5981, 32.6772, 46.6358]
        with self.assertRaisesRegex(GraphProviderError, "finite ordered WGS84 bounds"):
            prepare.validate_recipe(reversed_aoi)
        with self.assertRaisesRegex(GraphProviderError, "WGS84 UTM projected CRS with metre units"):
            prepare.validate_recipe(self.source_recipe("EPSG:4326"))
        with self.assertRaisesRegex(GraphProviderError, "target.crs is invalid"):
            prepare.validate_recipe(self.source_recipe("not-a-crs"))

    def test_bundle_rejects_wrong_temporal_order_and_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            bundle = self.make_bundle(root)
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["timesteps"][0]["role"] = "event"
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(GraphProviderError, "roles must be ordered"):
                load_bundle(bundle)
            bundle = self.make_bundle(root / "second")
            (bundle / "DEM/fixture_DEM.tif").write_bytes(b"drift")
            with self.assertRaisesRegex(GraphProviderError, "hash mismatch"):
                load_bundle(bundle)

    def test_preflight_blocks_non_native_device(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            bundle = self.make_bundle(root)
            invocation = self.invocation(bundle)
            invocation["arguments"]["device"] = "cpu"
            with mock.patch("mere_geo_tools.runtime.resolve_mere_run_executable", return_value="/tmp/mere.run"), mock.patch.object(
                provider, "probe_native_geo_flood", return_value=None
            ), mock.patch.object(provider.platform, "system", return_value="Darwin"):
                report = provider.preflight(invocation, root / "run")
            validate_preflight(report)
            self.assertEqual(report["status"], "blocked")
            self.assertIn("device_invalid", [item["id"] for item in report["diagnostics"]])

    def test_preflight_accepts_native_geo_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            invocation = self.invocation(self.make_bundle(root))
            with mock.patch("mere_geo_tools.runtime.resolve_mere_run_executable", return_value="/tmp/mere.run"), mock.patch.object(
                provider, "probe_native_geo_flood", return_value=None
            ), mock.patch.object(provider.platform, "system", return_value="Darwin"):
                report = provider.preflight(invocation, root / "run")
            validate_preflight(report)
            self.assertEqual(report["status"], "ok")

    def test_fixture_execution_preserves_candidate_only_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            bundle = self.make_bundle(root)
            run_root = root / "run"
            run_root.mkdir()
            invocation = self.invocation(bundle)

            def fixture_candidate(
                _bundle: pathlib.Path, locations: dict[str, pathlib.Path], _device: str
            ) -> provider.CandidateResult:
                for name, path in locations.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(("candidate-only-" + name).encode())
                return provider.CandidateResult(
                    outputs=locations,
                    metrics={"name": "candidate_flood_fraction", "value": 0.25, "evidence_class": "candidate-only"},
                )

            events = []
            with mock.patch("mere_geo_tools.runtime.resolve_mere_run_executable", return_value="/tmp/mere.run"), mock.patch.object(
                provider, "probe_native_geo_flood", return_value=None
            ), mock.patch.object(provider.platform, "system", return_value="Darwin"), mock.patch.object(
                provider, "run_candidate", side_effect=fixture_candidate
            ):
                provider.graph_execute(invocation, run_root, events.append)
            validate_event_stream(events, invocation, run_root)
            self.assertEqual(events[-1]["type"], "node_result")
            artifacts = [event["artifact"] for event in events if event["type"] == "artifact_ready"]
            self.assertEqual({item["metadata"]["evidence_class"] for item in artifacts}, {"candidate-only"})
            self.assertEqual(set(events[-1]["outputs"]), {"mask", "probability", "manifest", "preview"})


if __name__ == "__main__":
    unittest.main()

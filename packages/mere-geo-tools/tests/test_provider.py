from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from mere_geo_tools import cli, prepare, prepare_embeddings, provider
from mere_geo_tools.bundle import (
    BUNDLE_KIND,
    BUNDLE_VERSION,
    FIRE_BUNDLE_KIND,
    OLMOEARTH_BUNDLE_KIND,
    TESSERA_BUNDLE_KIND,
    canonical_digest,
    load_bundle,
    sha256_file,
)
from mere_geo_tools.constants import (
    FIRE_MODEL_ID,
    FIRE_MODEL_REVISION,
    MODEL_ID,
    MODEL_REVISION,
    OLMOEARTH_S2_BANDS,
    S1_BANDS,
    S2_BANDS,
    TEMPORAL_ROLES,
    TESSERA_S2_BANDS,
)
from mere_workflow_tools.graph_sdk import (
    GraphProviderError,
    validate_catalog,
    validate_event_stream,
    validate_preflight,
)


class GeoProviderTests(unittest.TestCase):
    def invoke_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with mock.patch.object(sys, "argv", ["mere-geo-tools", *arguments]), redirect_stdout(
            stdout
        ), redirect_stderr(stderr):
            exit_code = cli.main()
        return exit_code, stdout.getvalue(), stderr.getvalue()

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

    def make_embedding_bundle(self, root: pathlib.Path, family: str) -> pathlib.Path:
        bundle = root / f"{family}-bundle"
        bundle.mkdir(parents=True)
        grid = {
            "crs": "EPSG:32617",
            "transform": [10, 0, 385000, 0, -10, 3924000],
            "width": 16,
            "height": 16,
            "resolution_m": 10,
        }
        if family == "tessera":
            kind = TESSERA_BUNDLE_KIND
            modalities = {
                "S2": {"bands": TESSERA_S2_BANDS, "shape": [2, 10, 16, 16], "doy": [10, 20]},
                "S1_ASC": {"bands": S1_BANDS, "shape": [2, 2, 16, 16], "doy": [11, 21]},
            }
            names = ["S2", "S2_VALID", "S1_ASC"]
            extra = {"S2_DOY": [10, 20], "S1_ASC_DOY": [11, 21]}
        else:
            kind = OLMOEARTH_BUNDLE_KIND
            modalities = {
                "S2L2A": {"bands": OLMOEARTH_S2_BANDS, "shape": [2, 12, 16, 16]},
            }
            names = ["S2L2A"]
            extra = {"timestamps": [[1, 0, 2026], [1, 1, 2026]]}
        artifacts = {}
        entries = []
        for name in names:
            path = bundle / name / f"fixture_{name}.zarr.zip"
            path.parent.mkdir()
            path.write_bytes(f"fixture-{name}".encode())
            digest = sha256_file(path)
            relative = path.relative_to(bundle).as_posix()
            artifacts[name] = {"path": relative, "bytes": path.stat().st_size, "sha256": digest}
            entries.append({"name": name, "path": relative, "sha256": digest})
        manifest = {
            "kind": kind,
            "version": BUNDLE_VERSION,
            "sample_id": "fixture",
            "model_family": {"name": family},
            "grid": grid,
            "modalities": modalities,
            "sources": {},
            "artifacts": artifacts,
            "input_digest": canonical_digest(entries),
            **extra,
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest))
        return bundle

    def embedding_invocation(self, bundle: pathlib.Path, kind: str) -> dict[str, object]:
        return {
            "contract_version": "mere.run/plugin-graph-invocation.v1",
            "kind": kind,
            "arguments": {"input_bundle": str(bundle), "device": "auto"},
            "outputs": {
                "embeddings": {"type": "asset", "path": "artifacts/embeddings.safetensors"},
                "manifest": {"type": "asset", "path": "artifacts/embeddings.json"},
            },
        }

    def test_catalog_and_plugin_manifest_expose_candidate_provider(self) -> None:
        value = provider.catalog()
        validate_catalog(value)
        self.assertEqual(value["provider_id"], "mere-geo-tools")
        self.assertEqual(value["nodes"][0]["kind"], "geo.flood.segment")
        self.assertEqual(
            {node["kind"] for node in value["nodes"]},
            {"geo.flood.segment", "geo.fire.segment", "geo.tessera.embed", "geo.olmoearth.embed"},
        )
        self.assertIn("metal", value["nodes"][0]["requirements"]["accelerator_backends"])
        self.assertEqual(
            value["nodes"][0]["requirements"]["model_ids"],
            ["vision-flood-terramind-base"],
        )
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["graphProvider"]["contractVersion"], "mere.run/plugin-graph-provider.v1")
        self.assertIn("flood-segmentation", manifest["capabilities"])
        self.assertIn("fire-segmentation", manifest["capabilities"])
        self.assertIn("earth-observation-embeddings", manifest["capabilities"])

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

    def test_cli_routes_every_machine_readable_command(self) -> None:
        exit_code, stdout, _ = self.invoke_cli(["manifest", "--json"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout)["name"], provider.PROVIDER_ID)

        with mock.patch.object(cli, "doctor_report", return_value={"status": "blocked"}):
            exit_code, _, _ = self.invoke_cli(["doctor", "--json"])
        self.assertEqual(exit_code, 2)

        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            recipe = root / "recipe.json"
            output = root / "output"
            recipe.write_text('{"kind":"mere.geo/terramind-flood-source-recipe"}')
            with mock.patch("mere_geo_tools.prepare.prepare_bundle", return_value={"kind": "flood"}):
                exit_code, stdout, _ = self.invoke_cli(
                    ["prepare", "--recipe", str(recipe), "--output", str(output), "--json"]
                )
            self.assertEqual(json.loads(stdout)["kind"], "flood")

            recipe.write_text('{"kind":"mere.geo/tessera-v2-source-recipe"}')
            with mock.patch(
                "mere_geo_tools.prepare_embeddings.prepare_embedding_bundle",
                return_value={"kind": "tessera"},
            ):
                exit_code, stdout, _ = self.invoke_cli(
                    ["prepare", "--recipe", str(recipe), "--output", str(output), "--json"]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout)["kind"], "tessera")

            with mock.patch.object(cli, "load_bundle", return_value={"kind": "bundle"}):
                exit_code, stdout, _ = self.invoke_cli(["inspect", str(root), "--json"])
            self.assertEqual(json.loads(stdout)["kind"], "bundle")

            comparison = root / "comparison.json"
            comparison.write_text('{"comparison":{"jaccard":0.5}}')
            exit_code, stdout, _ = self.invoke_cli(["compare", str(comparison), "--json"])
            self.assertEqual(json.loads(stdout)["jaccard"], 0.5)

            request = root / "request.json"
            request.write_text("{}")
            exit_code, stdout, _ = self.invoke_cli(["graph", "catalog", "--json"])
            self.assertEqual(json.loads(stdout)["provider_id"], provider.PROVIDER_ID)

            with mock.patch.object(cli, "read_invocation", return_value={}), mock.patch.object(
                cli, "preflight", return_value={"status": "ok"}
            ), mock.patch.object(cli, "validate_preflight"):
                exit_code, stdout, _ = self.invoke_cli(
                    ["graph", "preflight", "--request", str(request), "--run-dir", str(root), "--json"]
                )
            self.assertEqual(json.loads(stdout)["status"], "ok")

            with mock.patch.object(cli, "read_invocation", return_value={}), mock.patch.object(
                cli, "graph_execute", side_effect=lambda _invocation, _run_dir, emit: emit({"type": "done"})
            ):
                exit_code, stdout, _ = self.invoke_cli(
                    [
                        "graph",
                        "execute",
                        "--request",
                        str(request),
                        "--run-dir",
                        str(root),
                        "--json-stream",
                    ]
                )
            self.assertEqual(json.loads(stdout)["type"], "done")

            with mock.patch.object(cli, "load_bundle", side_effect=GraphProviderError("bad bundle")):
                exit_code, _, stderr = self.invoke_cli(["inspect", str(root), "--json"])
            self.assertEqual(exit_code, 1)
            self.assertIn("bad bundle", stderr)

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

    def test_fire_recipe_uses_independent_bundle_and_model_pin(self) -> None:
        recipe = self.source_recipe()
        recipe["kind"] = "mere.geo/terramind-fire-source-recipe"
        prepare.validate_recipe(recipe)
        self.assertEqual(
            prepare.hazard_contract(recipe["kind"]),
            (FIRE_BUNDLE_KIND, FIRE_MODEL_ID, FIRE_MODEL_REVISION),
        )

    def test_embedding_recipes_require_real_temporal_inputs(self) -> None:
        target = {"aoi": [32.67, 46.59, 32.78, 46.64], "crs": "EPSG:32636"}
        tessera = {
            "kind": "mere.geo/tessera-v2-source-recipe",
            "version": 1,
            "sample_id": "annual-history",
            "target": target,
            "observations": {
                "S2": [{"collection": "sentinel-2-l2a", "item": "s2-a"}],
                "S1_ASC": [{"collection": "sentinel-1-rtc", "item": "s1-a"}],
            },
        }
        prepare_embeddings.validate_embedding_recipe(tessera)
        olmo = {
            "kind": "mere.geo/olmoearth-v1.2-source-recipe",
            "version": 1,
            "sample_id": "multisensor",
            "target": target,
            "timesteps": [
                {
                    "observed_at": "2026-06-15T10:00:00Z",
                    "S2L2A": {"collection": "sentinel-2-l2a", "item": "s2-a"},
                }
            ],
        }
        prepare_embeddings.validate_embedding_recipe(olmo)
        olmo["timesteps"][0]["observed_at"] = "2026-06-15"
        with self.assertRaisesRegex(GraphProviderError, "include a timezone"):
            prepare_embeddings.validate_embedding_recipe(olmo)

    def test_olmoearth_landsat_requires_compatible_level1_contract(self) -> None:
        target = {"aoi": [32.67, 46.59, 32.78, 46.64], "crs": "EPSG:32636"}
        landsat = {
            "stac_endpoint": prepare_embeddings.USGS_LANDSAT_STAC_ENDPOINT,
            "collection": prepare_embeddings.USGS_LANDSAT_COLLECTION,
            "item": "LC08_L1TP_046027_20250821_20250828_02_T1",
            "source_contract": "landsat-oli-tirs-level1-dn-v1",
        }
        recipe = {
            "kind": "mere.geo/olmoearth-v1.2-source-recipe",
            "version": 1,
            "sample_id": "landsat-context",
            "target": target,
            "timesteps": [{"observed_at": "2026-06-15T10:00:00Z", "LANDSAT": landsat}],
        }
        prepare_embeddings.validate_embedding_recipe(recipe)

        landsat["assets"] = dict(prepare_embeddings.USGS_LANDSAT_ASSETS)
        prepare_embeddings.validate_embedding_recipe(recipe)
        del landsat["assets"]["B11"]
        with self.assertRaisesRegex(GraphProviderError, "missing canonical bands: B11"):
            prepare_embeddings.validate_embedding_recipe(recipe)

        landsat["assets"]["B11"] = "lwir12"
        landsat["source_contract"] = "surface-reflectance"
        with self.assertRaisesRegex(GraphProviderError, "source_contract must be"):
            prepare_embeddings.validate_embedding_recipe(recipe)

        landsat["source_contract"] = "landsat-oli-tirs-level1-dn-v1"
        landsat["collection"] = "landsat-c2-l2"
        with self.assertRaisesRegex(GraphProviderError, "landsat-c2-l2 is incompatible"):
            prepare_embeddings.validate_embedding_recipe(recipe)

        landsat["collection"] = prepare_embeddings.USGS_LANDSAT_COLLECTION
        landsat["stac_endpoint"] = "https://planetarycomputer.microsoft.com/api/stac/v1"
        with self.assertRaisesRegex(GraphProviderError, "requires the official USGS Level-1 source"):
            prepare_embeddings.validate_embedding_recipe(recipe)

        landsat["stac_endpoint"] = "http://landsatlook.usgs.gov/stac-server"
        with self.assertRaisesRegex(GraphProviderError, "must be a non-empty HTTPS URL"):
            prepare_embeddings.validate_embedding_recipe(recipe)

    def test_olmoearth_landsat_uses_official_requester_pays_asset(self) -> None:
        asset = mock.Mock()
        asset.href = "https://landsatlook.usgs.gov/data/scene_B8.TIF"
        asset.extra_fields = {
            "alternate": {
                "s3": {
                    "href": "s3://usgs-landsat/collection02/level-1/scene_B8.TIF",
                    "storage:requester_pays": True,
                }
            }
        }
        self.assertEqual(
            prepare_embeddings.asset_read_access(asset, prepare_embeddings.USGS_LANDSAT_STAC_ENDPOINT),
            ("s3://usgs-landsat/collection02/level-1/scene_B8.TIF", True),
        )
        asset.extra_fields["alternate"]["s3"]["storage:requester_pays"] = False
        with self.assertRaisesRegex(GraphProviderError, "must declare requester-pays access"):
            prepare_embeddings.asset_read_access(asset, prepare_embeddings.USGS_LANDSAT_STAC_ENDPOINT)

    def test_embedding_bundles_are_typed_and_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            tessera = load_bundle(self.make_embedding_bundle(root, "tessera"))
            olmo = load_bundle(self.make_embedding_bundle(root, "olmoearth"))
            self.assertEqual(tessera["kind"], TESSERA_BUNDLE_KIND)
            self.assertEqual(olmo["kind"], OLMOEARTH_BUNDLE_KIND)

    def test_embedding_preflight_probes_the_matching_native_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            invocation = self.embedding_invocation(
                self.make_embedding_bundle(root, "tessera"), "geo.tessera.embed"
            )
            with mock.patch(
                "mere_geo_tools.runtime.resolve_mere_run_executable", return_value="/tmp/mere.run"
            ), mock.patch.object(provider, "probe_native_geo", return_value=None) as probe, mock.patch.object(
                provider.platform, "system", return_value="Darwin"
            ):
                report = provider.preflight(invocation, root / "run")
            validate_preflight(report)
            self.assertEqual(report["status"], "ok")
            probe.assert_called_once_with("/tmp/mere.run", "tessera")

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

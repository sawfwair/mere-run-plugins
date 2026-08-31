from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import platform
import sys
import tempfile
from typing import cast

from mere_workflow_tools.graph_sdk import GraphProviderError, JsonMap, validate_preflight

from . import __version__
from .bundle import load_bundle
from .provider import PROVIDER_ID, catalog, graph_execute, preflight, read_invocation


def plugin_manifest() -> JsonMap:
    commands = [
        {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
        {"name": "doctor", "description": "Check geospatial and model runtime readiness.", "stdout": "json"},
        {"name": "prepare", "description": "Prepare a typed geospatial input bundle from pinned STAC items.", "stdout": "json"},
        {"name": "inspect", "description": "Validate and inspect a prepared input bundle.", "stdout": "json"},
        {
            "name": "compare",
            "description": "Inspect candidate and NDVI/challenger comparison metrics.",
            "stdout": "json",
        },
        {"name": "graph", "description": "Expose portable geospatial graph nodes.", "stdout": "json"},
    ]
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PROVIDER_ID,
        "version": __version__,
        "executable": PROVIDER_ID,
        "description": "Humanitarian geospatial candidates and embeddings with content-addressed raster provenance.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-geo-tools",
        "graphProvider": {"contractVersion": "mere.run/plugin-graph-provider.v1"},
        "commands": commands,
        "capabilities": [
            "geospatial",
            "flood-segmentation",
            "fire-segmentation",
            "earth-observation-embeddings",
            "graph-node-provider-v1",
            "provenance",
        ],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": False,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def _deep_runtime_checks() -> tuple[dict[str, bool], dict[str, str]]:
    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}

    try:
        import numpy as np

        checks["numpy"] = bool(np.array([1, 2, 3], dtype=np.uint8).sum() == 6)
    except Exception as exc:
        checks["numpy"] = False
        errors["numpy"] = str(exc)

    try:
        import numpy as np
        from rasterio.io import MemoryFile
        from rasterio.transform import from_origin

        pixels = np.arange(4, dtype=np.uint8).reshape((1, 2, 2))
        with MemoryFile() as memory_file:
            with memory_file.open(
                driver="GTiff",
                width=2,
                height=2,
                count=1,
                dtype="uint8",
                crs="EPSG:32617",
                transform=from_origin(500_000, 4_000_000, 10, 10),
            ) as dataset:
                dataset.write(pixels)
            with memory_file.open() as dataset:
                checks["rasterio"] = bool(np.array_equal(dataset.read(), pixels))
    except Exception as exc:
        checks["rasterio"] = False
        errors["rasterio"] = str(exc)

    try:
        import numpy as np
        import zarr
        from numcodecs import Blosc

        with tempfile.TemporaryDirectory(prefix="mere-geo-doctor-zarr.") as raw_root:
            root = zarr.open_array(
                str(pathlib.Path(raw_root) / "check.zarr"),
                mode="w",
                shape=(2, 2),
                chunks=(1, 2),
                dtype="u1",
                compressor=Blosc(cname="zstd", clevel=1),
            )
            root[:] = np.array([[1, 2], [3, 4]], dtype=np.uint8)
            checks["zarr"] = bool(int(root[:].sum()) == 10)
    except Exception as exc:
        checks["zarr"] = False
        errors["zarr"] = str(exc)

    try:
        import numpy as np
        from safetensors.numpy import load_file, save_file

        with tempfile.TemporaryDirectory(prefix="mere-geo-doctor-safetensors.") as raw_root:
            path = pathlib.Path(raw_root) / "check.safetensors"
            save_file({"check": np.array([[1.0, 2.0]], dtype=np.float32)}, path)
            checks["safetensors"] = bool(float(load_file(path)["check"].sum()) == 3.0)
    except Exception as exc:
        checks["safetensors"] = False
        errors["safetensors"] = str(exc)

    try:
        import planetary_computer
        import pystac_client

        checks["stac_clients"] = bool(planetary_computer and pystac_client)
    except Exception as exc:
        checks["stac_clients"] = False
        errors["stac_clients"] = str(exc)

    return checks, errors


def doctor_report(*, deep: bool = False) -> JsonMap:
    from .runtime import resolve_mere_run_executable

    required = ["numpy", "planetary_computer", "pystac_client", "rasterio", "safetensors", "zarr"]
    modules = {name: importlib.util.find_spec(name) is not None for name in required}
    compatible_python = sys.version_info >= (3, 10)
    executable = resolve_mere_run_executable()
    native_platform = platform.system() == "Darwin"
    deep_checks, deep_errors = _deep_runtime_checks() if deep else ({}, {})
    ready = compatible_python and native_platform and bool(executable) and all(modules.values())
    if deep:
        ready = ready and all(deep_checks.values())
    report: JsonMap = {
        "status": "ready" if ready else "blocked",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "modules": modules,
        "native_runtime": {
            "executable": executable,
            "command": "mere.run geo flood",
            "commands": [
                "mere.run geo flood",
                "mere.run geo fire",
                "mere.run geo tessera",
                "mere.run geo olmoearth",
            ],
            "accelerator": "metal",
        },
    }
    if deep:
        report["deep_checks"] = deep_checks
        report["deep_errors"] = deep_errors
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    for name in ["manifest", "doctor"]:
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true")
        if name == "doctor":
            command.add_argument("--deep", action="store_true")
    prepare_command = commands.add_parser("prepare")
    prepare_command.add_argument("--recipe", required=True, type=pathlib.Path)
    prepare_command.add_argument("--output", required=True, type=pathlib.Path)
    prepare_command.add_argument("--json", action="store_true")
    inspect_command = commands.add_parser("inspect")
    inspect_command.add_argument("bundle", type=pathlib.Path)
    inspect_command.add_argument("--json", action="store_true")
    compare_command = commands.add_parser("compare")
    compare_command.add_argument("manifest", type=pathlib.Path)
    compare_command.add_argument("--json", action="store_true")
    graph = commands.add_parser("graph")
    graph_commands = graph.add_subparsers(dest="graph_command", required=True)
    graph_commands.add_parser("catalog").add_argument("--json", action="store_true")
    for name in ["preflight", "execute"]:
        command = graph_commands.add_parser(name)
        command.add_argument("--request", required=True, type=pathlib.Path)
        command.add_argument("--run-dir", required=True, type=pathlib.Path)
        command.add_argument("--json" if name == "preflight" else "--json-stream", action="store_true")
    return value


def print_json(value: object) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "manifest":
            print_json(plugin_manifest())
        elif args.command == "doctor":
            report = doctor_report(deep=args.deep)
            print_json(report)
            return 0 if report["status"] == "ready" else 2
        elif args.command == "prepare":
            recipe = cast(JsonMap, json.loads(args.recipe.read_text()))
            if recipe.get("kind") in {
                "mere.geo/tessera-v2-source-recipe",
                "mere.geo/olmoearth-v1.2-source-recipe",
            }:
                from .prepare_embeddings import prepare_embedding_bundle

                print_json(prepare_embedding_bundle(args.recipe, args.output))
            else:
                from .prepare import prepare_bundle

                print_json(prepare_bundle(args.recipe, args.output))
        elif args.command == "inspect":
            print_json(load_bundle(args.bundle))
        elif args.command == "compare":
            payload = cast(JsonMap, json.loads(args.manifest.read_text()))
            print_json(payload.get("comparison", {}))
        elif args.graph_command == "catalog":
            print_json(catalog())
        else:
            invocation = read_invocation(args.request)
            if args.graph_command == "preflight":
                report = preflight(invocation, args.run_dir)
                validate_preflight(report)
                print_json(report)
            else:
                graph_execute(invocation, args.run_dir, print_json)
        return 0
    except (GraphProviderError, OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

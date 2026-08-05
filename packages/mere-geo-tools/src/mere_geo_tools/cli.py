from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import platform
import sys
from typing import cast

from mere_workflow_tools.graph_sdk import GraphProviderError, JsonMap, validate_preflight

from . import __version__
from .bundle import load_bundle
from .provider import PROVIDER_ID, catalog, graph_execute, preflight, read_invocation


def plugin_manifest() -> JsonMap:
    commands = [
        {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
        {"name": "doctor", "description": "Check geospatial and model runtime readiness.", "stdout": "json"},
        {"name": "prepare", "description": "Prepare an ImpactMesh-compatible input bundle.", "stdout": "json"},
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
        "description": "Pinned geospatial candidate models with content-addressed raster provenance.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-geo-tools",
        "graphProvider": {"contractVersion": "mere.run/plugin-graph-provider.v1"},
        "commands": commands,
        "capabilities": ["geospatial", "flood-segmentation", "graph-node-provider-v1", "provenance"],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": False,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def doctor_report() -> JsonMap:
    from .runtime import resolve_mere_run_executable

    required = ["numpy", "rasterio", "safetensors", "zarr"]
    modules = {name: importlib.util.find_spec(name) is not None for name in required}
    compatible_python = sys.version_info >= (3, 10)
    executable = resolve_mere_run_executable()
    native_platform = platform.system() == "Darwin"
    return {
        "status": "ready" if compatible_python and native_platform and executable and all(modules.values()) else "blocked",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "modules": modules,
        "native_runtime": {
            "executable": executable,
            "command": "mere.run geo flood",
            "accelerator": "metal",
        },
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    for name in ["manifest", "doctor"]:
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true")
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
            report = doctor_report()
            print_json(report)
            return 0 if report["status"] == "ready" else 2
        elif args.command == "prepare":
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

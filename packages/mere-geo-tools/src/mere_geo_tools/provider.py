from __future__ import annotations

import pathlib
import platform
import subprocess
from dataclasses import dataclass
from typing import cast

from mere_workflow_tools.graph_sdk import (
    PREFLIGHT_CONTRACT_VERSION,
    PROVIDER_CONTRACT_VERSION,
    EventWriter,
    GraphEventStream,
    GraphProviderError,
    JsonMap,
    as_map,
    confined_path,
    diagnostic,
    load_invocation,
    relative_path,
    validate_catalog,
)

from . import __version__
from .bundle import load_bundle, sha256_file

PROVIDER_ID = "mere-geo-tools"
NODE_KIND = "geo.flood.segment"
OUTPUT_TYPES = {
    "mask": "image/tiff",
    "probability": "image/tiff",
    "manifest": "application/json",
    "preview": "image/png",
}
REQUIREMENTS: JsonMap = {
    "model_ids": ["vision-flood-terramind-base"],
    "accelerator_backends": ["metal"],
    "minimum_accelerator_memory_bytes": 8_000_000_000,
    "minimum_system_memory_bytes": 16_000_000_000,
    "minimum_disk_bytes": 4_000_000_000,
    "minimum_cpu_cores": 4,
    "network_access": False,
}


@dataclass(frozen=True)
class CandidateResult:
    outputs: dict[str, pathlib.Path]
    metrics: JsonMap


def catalog() -> JsonMap:
    value: JsonMap = {
        "contract_version": PROVIDER_CONTRACT_VERSION,
        "provider_id": PROVIDER_ID,
        "provider_version": __version__,
        "nodes": [
            {
                "kind": NODE_KIND,
                "title": "TerraMind flood candidates",
                "description": (
                    "Run the pinned TerraMind-base-Flood checkpoint on an ImpactMesh-compatible "
                    "four-timestep bundle and emit georeferenced candidate-only flood masks."
                ),
                "category": "geospatial",
                "inputs": [
                    {
                        "name": "input_bundle",
                        "type": "asset_directory",
                        "required": True,
                        "description": "Prepared four-timestep S2 L2A, S1 RTC, and Copernicus DEM bundle.",
                        "content_types": ["application/vnd.mere.geo.terramind-flood-input"],
                    },
                    {
                        "name": "device",
                        "type": "enum",
                        "required": False,
                        "description": "Native execution device. Auto selects Apple Metal.",
                        "default": "auto",
                        "values": ["auto", "metal"],
                    },
                ],
                "outputs": [
                    {
                        "name": name,
                        "type": "asset",
                        "optional": False,
                        "description": description,
                        "content_types": [content_type],
                    }
                    for name, content_type, description in [
                        ("mask", OUTPUT_TYPES["mask"], "Binary candidate flood mask COG."),
                        ("probability", OUTPUT_TYPES["probability"], "Flood-class probability COG."),
                        ("manifest", OUTPUT_TYPES["manifest"], "Model, input, output, and comparison provenance."),
                        ("preview", OUTPUT_TYPES["preview"], "Review-only PNG overlay."),
                    ]
                ],
                "requirements": REQUIREMENTS,
                "traits": {
                    "deterministic": True,
                    "cacheable": True,
                    "side_effects": "local",
                    "supports_progress": True,
                    "supports_previews": True,
                },
            }
        ],
    }
    validate_catalog(value)
    return value


def read_invocation(path: pathlib.Path) -> JsonMap:
    return load_invocation(path, {NODE_KIND})


def output_locations(invocation: JsonMap, run_directory: pathlib.Path) -> dict[str, pathlib.Path]:
    outputs = as_map(invocation.get("outputs"), "outputs")
    locations: dict[str, pathlib.Path] = {}
    for name in OUTPUT_TYPES:
        declaration = as_map(outputs.get(name), f"outputs.{name}")
        relative = declaration.get("path")
        if not isinstance(relative, str):
            raise GraphProviderError(f"outputs.{name}.path is required")
        locations[name] = confined_path(run_directory, relative)
    return locations


def preflight(invocation: JsonMap, run_directory: pathlib.Path) -> JsonMap:
    diagnostics: list[JsonMap] = []
    arguments = as_map(invocation.get("arguments"), "arguments")
    bundle_value = arguments.get("input_bundle")
    if not isinstance(bundle_value, str):
        diagnostics.append(diagnostic("bundle_missing", "blocker", "Input bundle is required", "Provide input_bundle."))
    else:
        try:
            load_bundle(pathlib.Path(bundle_value))
        except GraphProviderError as exc:
            diagnostics.append(diagnostic("bundle_invalid", "blocker", "Input bundle is invalid", str(exc)))
    device = arguments.get("device", "auto")
    if device not in {"auto", "metal"}:
        diagnostics.append(
            diagnostic("device_invalid", "blocker", "Device is invalid", f"Unsupported device: {device}")
        )
    if platform.system() != "Darwin":
        diagnostics.append(
            diagnostic(
                "native_mlx_platform_unsupported",
                "blocker",
                "Native TerraMind Flood requires Apple silicon",
                "Run this provider on a macOS Metal executor.",
            )
        )
    from .runtime import resolve_mere_run_executable

    executable = resolve_mere_run_executable()
    if executable is None:
        diagnostics.append(
            diagnostic(
                "mere_run_missing",
                "blocker",
                "mere.run is not available",
                "Install mere.run or set MERE_RUN_EXECUTABLE to a native build containing `geo flood`.",
            )
        )
    else:
        probe_error = probe_native_geo_flood(executable)
        if probe_error:
            diagnostics.append(
                diagnostic(
                    "geo_flood_unavailable",
                    "blocker",
                    "mere.run geo flood is unavailable",
                    probe_error,
                )
            )
    try:
        output_locations(invocation, run_directory)
    except GraphProviderError as exc:
        diagnostics.append(diagnostic("output_invalid", "blocker", "Output declaration is invalid", str(exc)))
    return {
        "contract_version": PREFLIGHT_CONTRACT_VERSION,
        "status": "blocked" if any(item["severity"] == "blocker" for item in diagnostics) else "ok",
        "diagnostics": diagnostics,
        "actions": [],
        "requirements": REQUIREMENTS,
    }


def graph_execute(invocation: JsonMap, run_directory: pathlib.Path, write_event: EventWriter) -> None:
    report = preflight(invocation, run_directory)
    if report["status"] != "ok":
        raise GraphProviderError("provider preflight is blocked")
    arguments = as_map(invocation["arguments"], "arguments")
    bundle_root = pathlib.Path(cast(str, arguments["input_bundle"])).resolve()
    device = cast(str, arguments.get("device", "auto"))
    locations = output_locations(invocation, run_directory)
    for path in locations.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    events = GraphEventStream(write_event)
    events.emit("progress", message="Running native TerraMind Flood through mere.run", progress={"current": 0, "total": 3})
    result = run_candidate(bundle_root, locations, device)
    events.emit("progress", message="Writing georeferenced candidate artifacts", progress={"current": 2, "total": 3})
    for name, path in result.outputs.items():
        events.emit(
            "artifact_ready",
            artifact={
                "name": name,
                "kind": "geo.flood.candidate",
                "path": relative_path(path, run_directory),
                "content_type": OUTPUT_TYPES[name],
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "metadata": {"evidence_class": "candidate-only"},
            },
        )
    events.emit("metric", metric=result.metrics)
    events.emit(
        "node_result",
        outputs={name: relative_path(path, run_directory) for name, path in result.outputs.items()},
    )


def run_candidate(bundle_root: pathlib.Path, locations: dict[str, pathlib.Path], device: str) -> CandidateResult:
    from .runtime import execute_candidate

    return execute_candidate(bundle_root, locations, device)


def probe_native_geo_flood(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "geo", "flood", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    return result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"

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
from .bundle import (
    FIRE_BUNDLE_KIND,
    FLOOD_BUNDLE_KIND,
    OLMOEARTH_BUNDLE_KIND,
    TESSERA_BUNDLE_KIND,
    load_bundle,
    sha256_file,
)
from .constants import FIRE_NATIVE_MODEL_ID, NATIVE_MODEL_ID, OLMOEARTH_MODELS, TESSERA_MODELS

PROVIDER_ID = "mere-geo-tools"
NODE_KIND = "geo.flood.segment"  # Backwards-compatible public name.

HAZARD_OUTPUT_TYPES = {
    "mask": "image/tiff",
    "probability": "image/tiff",
    "manifest": "application/json",
    "preview": "image/png",
}
EMBEDDING_OUTPUT_TYPES = {
    "embeddings": "application/vnd.safetensors",
    "manifest": "application/json",
}
OUTPUT_TYPES = HAZARD_OUTPUT_TYPES  # Backwards-compatible public name.


def requirements(model_ids: list[str], memory: int, disk: int) -> JsonMap:
    return {
        "model_ids": model_ids,
        "accelerator_backends": ["metal"],
        "minimum_accelerator_memory_bytes": memory,
        "minimum_system_memory_bytes": max(memory, 8_000_000_000),
        "minimum_disk_bytes": disk,
        "minimum_cpu_cores": 4,
        "network_access": False,
    }


REQUIREMENTS = requirements([NATIVE_MODEL_ID], 8_000_000_000, 4_000_000_000)


@dataclass(frozen=True)
class NodeSpec:
    kind: str
    title: str
    description: str
    bundle_kind: str
    command: str
    output_types: dict[str, str]
    requirements: JsonMap
    evidence_class: str


NODE_SPECS = {
    NODE_KIND: NodeSpec(
        kind=NODE_KIND,
        title="TerraMind flood candidates",
        description=(
            "Run pinned TerraMind Flood on a four-timestep S2/S1/DEM bundle and emit "
            "georeferenced candidate-only masks."
        ),
        bundle_kind=FLOOD_BUNDLE_KIND,
        command="flood",
        output_types=HAZARD_OUTPUT_TYPES,
        requirements=REQUIREMENTS,
        evidence_class="candidate-only",
    ),
    "geo.fire.segment": NodeSpec(
        kind="geo.fire.segment",
        title="TerraMind fire candidates",
        description=(
            "Run pinned TerraMind Fire on a four-timestep S2/S1/DEM bundle and emit "
            "georeferenced candidate-only masks."
        ),
        bundle_kind=FIRE_BUNDLE_KIND,
        command="fire",
        output_types=HAZARD_OUTPUT_TYPES,
        requirements=requirements([FIRE_NATIVE_MODEL_ID], 8_000_000_000, 4_000_000_000),
        evidence_class="candidate-only",
    ),
    "geo.tessera.embed": NodeSpec(
        kind="geo.tessera.embed",
        title="TESSERA v2 temporal embeddings",
        description=(
            "Encode provenance-pinned Sentinel-1/2 pixel histories with a hardware-selected "
            "TESSERA v2 student or Teacher."
        ),
        bundle_kind=TESSERA_BUNDLE_KIND,
        command="tessera",
        output_types=EMBEDDING_OUTPUT_TYPES,
        requirements=requirements(
            [cast(str, value["id"]) for value in TESSERA_MODELS.values()],
            4_000_000_000,
            10_000_000_000,
        ),
        evidence_class="derived-feature",
    ),
    "geo.olmoearth.embed": NodeSpec(
        kind="geo.olmoearth.embed",
        title="OlmoEarth v1.2 spatial embeddings",
        description=(
            "Encode provenance-pinned Sentinel-2, Sentinel-1, or Landsat observations with "
            "a hardware-selected OlmoEarth v1.2 tier."
        ),
        bundle_kind=OLMOEARTH_BUNDLE_KIND,
        command="olmoearth",
        output_types=EMBEDDING_OUTPUT_TYPES,
        requirements=requirements(
            [cast(str, value["id"]) for value in OLMOEARTH_MODELS.values()],
            4_000_000_000,
            8_000_000_000,
        ),
        evidence_class="derived-feature",
    ),
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
        "nodes": [catalog_node(spec) for spec in NODE_SPECS.values()],
    }
    validate_catalog(value)
    return value


def catalog_node(spec: NodeSpec) -> JsonMap:
    inputs: list[JsonMap] = [
        {
            "name": "input_bundle",
            "type": "asset_directory",
            "required": True,
            "description": "Prepared, content-addressed Earth-observation bundle.",
            "content_types": [f"application/vnd.{spec.bundle_kind.replace('/', '.')}"],
        },
        {
            "name": "device",
            "type": "enum",
            "required": False,
            "description": "Native execution device. Auto selects Apple Metal.",
            "default": "auto",
            "values": ["auto", "metal"],
        },
    ]
    if spec.command == "tessera":
        inputs.extend(
            [
                model_input(TESSERA_MODELS),
                {
                    "name": "dimensions",
                    "type": "integer",
                    "required": False,
                    "description": "Student width 16/32/64/128, or 1024 for Teacher.",
                    "minimum": 16,
                    "maximum": 1024,
                },
                {
                    "name": "batch_pixels",
                    "type": "integer",
                    "required": False,
                    "description": "Pixels per native inference batch; increase on larger-memory machines.",
                    "default": 2048,
                    "minimum": 1,
                },
            ]
        )
    elif spec.command == "olmoearth":
        inputs.extend(
            [
                model_input(OLMOEARTH_MODELS),
                {
                    "name": "patch_size",
                    "type": "integer",
                    "required": False,
                    "description": "Spatial patch size: 1, 2, 4, or 8 pixels.",
                    "default": 4,
                    "minimum": 1,
                    "maximum": 8,
                },
                {
                    "name": "input_resolution",
                    "type": "number",
                    "required": False,
                    "description": "Ground sample distance in metres; defaults to the prepared grid.",
                    "minimum": 0.01,
                },
                {
                    "name": "include_tokens",
                    "type": "boolean",
                    "required": False,
                    "description": "Preserve full space-time tokens in addition to pooled spatial grids.",
                    "default": False,
                },
            ]
        )
    output_descriptions = {
        "mask": "Binary candidate mask COG.",
        "probability": "Positive-class probability COG.",
        "manifest": "Model, source, execution, and output provenance.",
        "preview": "Review-only PNG overlay.",
        "embeddings": "Georeferenced spatial embeddings in safetensors.",
    }
    return {
        "kind": spec.kind,
        "title": spec.title,
        "description": spec.description,
        "category": "geospatial",
        "inputs": inputs,
        "outputs": [
            {
                "name": name,
                "type": "asset",
                "optional": False,
                "description": output_descriptions[name],
                "content_types": [content_type],
            }
            for name, content_type in spec.output_types.items()
        ],
        "requirements": spec.requirements,
        "traits": {
            "deterministic": True,
            "cacheable": True,
            "side_effects": "local",
            "supports_progress": True,
            "supports_previews": "preview" in spec.output_types,
        },
    }


def model_input(models: dict[str, JsonMap]) -> JsonMap:
    return {
        "name": "model",
        "type": "enum",
        "required": False,
        "description": "Auto selects the strongest appropriate installed tier for this machine.",
        "default": "auto",
        "values": ["auto", *[cast(str, value["id"]) for value in models.values()]],
    }


def read_invocation(path: pathlib.Path) -> JsonMap:
    return load_invocation(path, set(NODE_SPECS))


def invocation_spec(invocation: JsonMap) -> NodeSpec:
    kind = invocation.get("kind")
    if not isinstance(kind, str) or kind not in NODE_SPECS:
        raise GraphProviderError(f"unsupported geospatial node kind: {kind}")
    return NODE_SPECS[kind]


def output_locations(invocation: JsonMap, run_directory: pathlib.Path) -> dict[str, pathlib.Path]:
    spec = invocation_spec(invocation)
    outputs = as_map(invocation.get("outputs"), "outputs")
    locations: dict[str, pathlib.Path] = {}
    for name in spec.output_types:
        declaration = as_map(outputs.get(name), f"outputs.{name}")
        relative = declaration.get("path")
        if not isinstance(relative, str):
            raise GraphProviderError(f"outputs.{name}.path is required")
        locations[name] = confined_path(run_directory, relative)
    return locations


def preflight(invocation: JsonMap, run_directory: pathlib.Path) -> JsonMap:
    diagnostics: list[JsonMap] = []
    spec = invocation_spec(invocation)
    arguments = as_map(invocation.get("arguments"), "arguments")
    bundle_value = arguments.get("input_bundle")
    if not isinstance(bundle_value, str):
        diagnostics.append(diagnostic("bundle_missing", "blocker", "Input bundle is required", "Provide input_bundle."))
    else:
        try:
            load_bundle(pathlib.Path(bundle_value), expected_kinds={spec.bundle_kind})
        except GraphProviderError as exc:
            diagnostics.append(diagnostic("bundle_invalid", "blocker", "Input bundle is invalid", str(exc)))
    device = arguments.get("device", "auto")
    if device not in {"auto", "metal"}:
        diagnostics.append(diagnostic("device_invalid", "blocker", "Device is invalid", f"Unsupported device: {device}"))
    diagnostics.extend(argument_diagnostics(spec, arguments))
    if platform.system() != "Darwin":
        diagnostics.append(
            diagnostic(
                "native_mlx_platform_unsupported",
                "blocker",
                f"Native {spec.title} requires Apple silicon",
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
                f"Install mere.run or set MERE_RUN_EXECUTABLE to a native build containing `geo {spec.command}`.",
            )
        )
    else:
        probe_error = (
            probe_native_geo_flood(executable)
            if spec.command == "flood"
            else probe_native_geo(executable, spec.command)
        )
        if probe_error:
            diagnostics.append(
                diagnostic(
                    f"geo_{spec.command}_unavailable",
                    "blocker",
                    f"mere.run geo {spec.command} is unavailable",
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
        "requirements": spec.requirements,
    }


def argument_diagnostics(spec: NodeSpec, arguments: JsonMap) -> list[JsonMap]:
    values: list[JsonMap] = []

    def invalid(identifier: str, detail: str) -> None:
        values.append(diagnostic(identifier, "blocker", "Node argument is invalid", detail))

    if spec.command == "tessera":
        model = arguments.get("model", "auto")
        allowed = {"auto", *[value["id"] for value in TESSERA_MODELS.values()]}
        if model not in allowed:
            invalid("model_invalid", f"Unsupported TESSERA model: {model}")
        dimensions = arguments.get("dimensions")
        if dimensions is not None and dimensions not in {16, 32, 64, 128, 1024}:
            invalid("dimensions_invalid", "TESSERA dimensions must be 16, 32, 64, 128, or 1024")
        elif dimensions is not None and model == "auto":
            invalid("dimensions_model_ambiguous", "Pin a TESSERA model when requesting explicit dimensions")
        elif model == TESSERA_MODELS["teacher"]["id"] and dimensions not in {None, 1024}:
            invalid("dimensions_model_mismatch", "TESSERA Teacher requires 1024 dimensions")
        elif model not in {"auto", TESSERA_MODELS["teacher"]["id"]} and dimensions == 1024:
            invalid("dimensions_model_mismatch", "TESSERA student models support at most 128 dimensions")
        batch_pixels = arguments.get("batch_pixels", 2048)
        if not isinstance(batch_pixels, int) or isinstance(batch_pixels, bool) or batch_pixels < 1:
            invalid("batch_pixels_invalid", "TESSERA batch_pixels must be a positive integer")
    elif spec.command == "olmoearth":
        model = arguments.get("model", "auto")
        allowed = {"auto", *[value["id"] for value in OLMOEARTH_MODELS.values()]}
        if model not in allowed:
            invalid("model_invalid", f"Unsupported OlmoEarth model: {model}")
        if arguments.get("patch_size", 4) not in {1, 2, 4, 8}:
            invalid("patch_size_invalid", "OlmoEarth patch_size must be 1, 2, 4, or 8")
        resolution = arguments.get("input_resolution")
        if resolution is not None and (
            not isinstance(resolution, (int, float)) or isinstance(resolution, bool) or resolution <= 0
        ):
            invalid("input_resolution_invalid", "OlmoEarth input_resolution must be positive")
        if not isinstance(arguments.get("include_tokens", False), bool):
            invalid("include_tokens_invalid", "OlmoEarth include_tokens must be boolean")
    return values


def graph_execute(invocation: JsonMap, run_directory: pathlib.Path, write_event: EventWriter) -> None:
    report = preflight(invocation, run_directory)
    if report["status"] != "ok":
        raise GraphProviderError("provider preflight is blocked")
    spec = invocation_spec(invocation)
    arguments = as_map(invocation["arguments"], "arguments")
    bundle_root = pathlib.Path(cast(str, arguments["input_bundle"])).resolve()
    device = cast(str, arguments.get("device", "auto"))
    locations = output_locations(invocation, run_directory)
    for path in locations.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    events = GraphEventStream(write_event)
    events.emit(
        "progress",
        message=f"Running native {spec.title} through mere.run",
        progress={"current": 0, "total": 3},
    )
    result = run_node(spec, bundle_root, locations, device, arguments)
    events.emit("progress", message="Writing provenance-preserving geo artifacts", progress={"current": 2, "total": 3})
    for name, path in result.outputs.items():
        events.emit(
            "artifact_ready",
            artifact={
                "name": name,
                "kind": spec.kind,
                "path": relative_path(path, run_directory),
                "content_type": spec.output_types[name],
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "metadata": {"evidence_class": spec.evidence_class},
            },
        )
    events.emit("metric", metric=result.metrics)
    events.emit("node_result", outputs={name: relative_path(path, run_directory) for name, path in result.outputs.items()})


def run_node(
    spec: NodeSpec,
    bundle_root: pathlib.Path,
    locations: dict[str, pathlib.Path],
    device: str,
    arguments: JsonMap,
) -> CandidateResult:
    if spec.command == "flood":
        return run_candidate(bundle_root, locations, device)
    if spec.command == "fire":
        from .runtime import execute_fire_candidate

        return execute_fire_candidate(bundle_root, locations, device)
    from .embedding_runtime import execute_olmoearth_embedding, execute_tessera_embedding

    model_value = arguments.get("model", "auto")
    model = None if model_value == "auto" else cast(str, model_value)
    if spec.command == "tessera":
        return execute_tessera_embedding(
            bundle_root,
            locations,
            device,
            model,
            cast(int, arguments["dimensions"]) if "dimensions" in arguments else None,
            cast(int, arguments.get("batch_pixels", 2048)),
        )
    resolution_value = arguments.get("input_resolution")
    resolution = float(resolution_value) if isinstance(resolution_value, (int, float)) else None
    return execute_olmoearth_embedding(
        bundle_root,
        locations,
        device,
        model,
        cast(int, arguments.get("patch_size", 4)),
        resolution,
        cast(bool, arguments.get("include_tokens", False)),
    )


def run_candidate(bundle_root: pathlib.Path, locations: dict[str, pathlib.Path], device: str) -> CandidateResult:
    from .runtime import execute_candidate

    return execute_candidate(bundle_root, locations, device)


def probe_native_geo(executable: str, command: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "geo", command, "--help"],
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


def probe_native_geo_flood(executable: str) -> str | None:
    return probe_native_geo(executable, "flood")

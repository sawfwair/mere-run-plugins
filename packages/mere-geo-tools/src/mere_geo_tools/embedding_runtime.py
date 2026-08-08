from __future__ import annotations

import json
import pathlib
import platform
import subprocess
import tempfile
import time
from typing import cast

import numpy as np
from numpy.typing import NDArray

from mere_workflow_tools.graph_sdk import GraphProviderError, JsonMap, as_map

from .bundle import (
    OLMOEARTH_BUNDLE_KIND,
    TESSERA_BUNDLE_KIND,
    confined_bundle_path,
    load_bundle,
    sha256_file,
)
from .constants import OLMOEARTH_MODELS, TESSERA_MODELS
from .provider import CandidateResult
from .runtime import artifact_path, load_zarr, resolve_mere_run_executable

FloatArray = NDArray[np.float32]


def execute_tessera_embedding(
    bundle_root: pathlib.Path,
    locations: dict[str, pathlib.Path],
    requested_device: str,
    model: str | None,
    dimensions: int | None,
    batch_pixels: int,
) -> CandidateResult:
    import zarr

    require_metal(requested_device, "TESSERA")
    if dimensions is not None and dimensions not in {16, 32, 64, 128, 1024}:
        raise GraphProviderError("TESSERA dimensions must be 16, 32, 64, 128, or 1024")
    if batch_pixels < 1:
        raise GraphProviderError("TESSERA batch_pixels must be positive")
    bundle = load_bundle(bundle_root, expected_kinds={TESSERA_BUNDLE_KIND})
    artifacts = as_map(bundle["artifacts"], "input artifacts")
    s2 = np.asarray(
        load_zarr(zarr, confined_bundle_path(bundle_root, artifact_path(artifacts, "S2"))),
        dtype=np.float32,
    )
    valid = np.asarray(
        load_zarr(zarr, confined_bundle_path(bundle_root, artifact_path(artifacts, "S2_VALID"))),
        dtype=np.uint8,
    )
    radar = {
        name: np.asarray(
            load_zarr(zarr, confined_bundle_path(bundle_root, artifact_path(artifacts, name))),
            dtype=np.float32,
        )
        for name in ["S1_ASC", "S1_DESC"]
        if name in artifacts
    }
    executable = require_runtime("TESSERA")
    grid = as_map(bundle["grid"], "grid")
    height = cast(int, grid["height"])
    width = cast(int, grid["width"])
    pixel_count = height * width
    valid_counts = valid.reshape(valid.shape[0], pixel_count).sum(axis=0)
    output: FloatArray | None = None
    native_runs: list[JsonMap] = []
    started = time.monotonic()
    for bucket in [8, 16, 32, 64, 128, 256]:
        pixel_indices = np.flatnonzero(
            np.array([sequence_bucket(int(value)) == bucket for value in valid_counts], dtype=bool)
        )
        for start in range(0, len(pixel_indices), batch_pixels):
            batch = pixel_indices[start : start + batch_pixels]
            inputs = tessera_pixel_batch(bundle, s2, valid, radar, batch, bucket)
            embeddings, metadata = native_tessera_forward(
                inputs,
                executable,
                model,
                dimensions,
            )
            if embeddings.ndim != 2 or embeddings.shape[0] != len(batch):
                raise GraphProviderError(
                    f"native TESSERA embeddings have invalid shape {tuple(embeddings.shape)}"
                )
            if output is None:
                output = np.full((pixel_count, embeddings.shape[1]), np.nan, dtype=np.float32)
            elif output.shape[1] != embeddings.shape[1]:
                raise GraphProviderError("native TESSERA output dimensions changed between batches")
            output[batch] = embeddings
            native_runs.append({**metadata, "sequence_length": bucket})
    if output is None:
        raise GraphProviderError("TESSERA bundle contains no cloud-valid Sentinel-2 pixels")
    spatial = output.reshape(height, width, output.shape[1])
    selected_model = native_runs[0].get("model_id") if native_runs else model
    metadata = {
        "format": "mere.geo/tessera-v2-spatial-embeddings-v1",
        "model_id": str(selected_model),
        "dimensions": str(output.shape[1]),
        "crs": cast(str, grid["crs"]),
    }
    save_safetensors({"embeddings": spatial}, locations["embeddings"], metadata)
    elapsed = time.monotonic() - started
    invalid_pixels = int((valid_counts == 0).sum())
    write_embedding_manifest(
        locations["manifest"],
        {
            "kind": "mere.geo/tessera-v2-embeddings",
            "version": 1,
            "evidence_class": "derived-feature",
            "model": model_manifest(TESSERA_MODELS, selected_model, dimensions=output.shape[1]),
            "input": input_manifest(bundle),
            "execution": {
                "device": "metal",
                "platform": platform.platform(),
                "elapsed_seconds": round(elapsed, 3),
                "batch_pixels": batch_pixels,
                "native_runs": native_runs,
                "sequence_policy": "cloud-valid S2 observations resampled to 8/16/32/64/128/256 buckets",
            },
            "summary": {
                "height": height,
                "width": width,
                "dimensions": output.shape[1],
                "embedded_pixels": pixel_count - invalid_pixels,
                "invalid_pixels": invalid_pixels,
            },
            "outputs": {},
        },
        locations,
    )
    return CandidateResult(
        outputs=locations,
        metrics={
            "name": "embedded_pixel_fraction",
            "value": round((pixel_count - invalid_pixels) / pixel_count, 8),
            "unit": "ratio",
            "evidence_class": "derived-feature",
        },
    )


def execute_olmoearth_embedding(
    bundle_root: pathlib.Path,
    locations: dict[str, pathlib.Path],
    requested_device: str,
    model: str | None,
    patch_size: int,
    input_resolution: float | None,
    include_tokens: bool,
) -> CandidateResult:
    import zarr

    require_metal(requested_device, "OlmoEarth")
    if patch_size not in {1, 2, 4, 8}:
        raise GraphProviderError("OlmoEarth patch_size must be 1, 2, 4, or 8")
    bundle = load_bundle(bundle_root, expected_kinds={OLMOEARTH_BUNDLE_KIND})
    grid = as_map(bundle["grid"], "grid")
    resolution = float(input_resolution if input_resolution is not None else grid["resolution_m"])
    if resolution <= 0:
        raise GraphProviderError("OlmoEarth input_resolution must be positive")
    height = cast(int, grid["height"])
    width = cast(int, grid["width"])
    if height % patch_size or width % patch_size:
        raise GraphProviderError("OlmoEarth bundle dimensions must be divisible by patch_size")
    artifacts = as_map(bundle["artifacts"], "input artifacts")
    inputs: dict[str, np.ndarray] = {
        "TIMESTAMPS": np.asarray(bundle["timestamps"], dtype=np.int32)[None, :, :]
    }
    for name in ["S2L2A", "S1RTC", "LANDSAT"]:
        if name not in artifacts:
            continue
        array = np.asarray(
            load_zarr(zarr, confined_bundle_path(bundle_root, artifact_path(artifacts, name))),
            dtype=np.float32,
        )
        inputs[name] = np.ascontiguousarray(array.transpose(2, 3, 0, 1)[None, ...])
    executable = require_runtime("OlmoEarth")
    started = time.monotonic()
    payload = native_olmoearth_forward(
        inputs,
        locations["embeddings"],
        executable,
        model,
        patch_size,
        resolution,
        include_tokens,
    )
    elapsed = time.monotonic() - started
    arrays = load_safetensors(locations["embeddings"])
    pooled_names = sorted(name for name in arrays if name.endswith("_EMBEDDINGS"))
    if not pooled_names:
        raise GraphProviderError("native OlmoEarth did not emit spatial embeddings")
    selected_model = payload.get("model_id", model)
    summary = {
        "input_height": height,
        "input_width": width,
        "patch_size": patch_size,
        "grid_height": height // patch_size,
        "grid_width": width // patch_size,
        "modalities": pooled_names,
        "include_tokens": include_tokens,
    }
    write_embedding_manifest(
        locations["manifest"],
        {
            "kind": "mere.geo/olmoearth-v1.2-embeddings",
            "version": 1,
            "evidence_class": "derived-feature",
            "license_notice": (
                "OlmoEarth's upstream artifact license prohibits military, defense, intelligence, "
                "human-surveillance, policing, and listed extractive uses."
            ),
            "model": model_manifest(OLMOEARTH_MODELS, selected_model),
            "input": input_manifest(bundle),
            "execution": {
                "device": "metal",
                "platform": platform.platform(),
                "elapsed_seconds": round(elapsed, 3),
                "patch_size": patch_size,
                "input_resolution_meters": resolution,
                "native_run": payload,
            },
            "summary": summary,
            "outputs": {},
        },
        locations,
    )
    return CandidateResult(
        outputs=locations,
        metrics={
            "name": "spatial_embedding_cells",
            "value": (height // patch_size) * (width // patch_size),
            "unit": "cells_per_modality",
            "evidence_class": "derived-feature",
        },
    )


def require_metal(device: str, family: str) -> None:
    if device not in {"auto", "metal"}:
        raise GraphProviderError(f"{family} executes through native mere.run Metal; use device=auto or device=metal")


def require_runtime(family: str) -> str:
    executable = resolve_mere_run_executable()
    if executable is None:
        raise GraphProviderError(f"mere.run is required for native {family} inference")
    return executable


def sequence_bucket(count: int) -> int | None:
    if count <= 0:
        return None
    for bucket in [8, 16, 32, 64, 128, 256]:
        if count <= bucket:
            return bucket
    return 256


def tessera_pixel_batch(
    bundle: JsonMap,
    s2: FloatArray,
    valid: NDArray[np.uint8],
    radar: dict[str, FloatArray],
    pixel_indices: NDArray[np.int64],
    sequence_length: int,
) -> dict[str, np.ndarray]:
    pixel_count = s2.shape[-2] * s2.shape[-1]
    s2_flat = s2.reshape(s2.shape[0], s2.shape[1], pixel_count)
    valid_flat = valid.reshape(valid.shape[0], pixel_count)
    s2_doy = np.asarray(bundle["S2_DOY"], dtype=np.int32)
    sampled_values = np.empty((len(pixel_indices), sequence_length, s2.shape[1]), dtype=np.float32)
    sampled_days = np.empty((len(pixel_indices), sequence_length), dtype=np.int32)
    for row, pixel in enumerate(pixel_indices):
        available = np.flatnonzero(valid_flat[:, pixel])
        positions = np.rint(np.linspace(0, len(available) - 1, sequence_length)).astype(np.int64)
        selected = available[positions]
        sampled_values[row] = s2_flat[selected, :, pixel]
        sampled_days[row] = s2_doy[selected]
    inputs: dict[str, np.ndarray] = {"S2": sampled_values, "S2_DOY": sampled_days}
    for name, values in radar.items():
        flat = values.reshape(values.shape[0], values.shape[1], pixel_count)
        inputs[name] = np.ascontiguousarray(flat[:, :, pixel_indices].transpose(2, 0, 1))
        inputs[f"{name}_DOY"] = np.broadcast_to(
            np.asarray(bundle[f"{name}_DOY"], dtype=np.int32)[None, :],
            (len(pixel_indices), values.shape[0]),
        ).copy()
    return inputs


def native_tessera_forward(
    inputs: dict[str, np.ndarray],
    executable: str,
    model: str | None,
    dimensions: int | None,
) -> tuple[FloatArray, JsonMap]:
    with tempfile.TemporaryDirectory(prefix="mere-tessera-native-") as raw_directory:
        directory = pathlib.Path(raw_directory)
        input_path = directory / "input.safetensors"
        output_path = directory / "embeddings.safetensors"
        save_safetensors(inputs, input_path, {"format": "mere.geo/tessera-pixel-batch-v1"})
        command = [executable, "geo", "tessera", str(input_path), "--output", str(output_path), "--json"]
        if model and model != "auto":
            command.extend(["--model", model])
        if dimensions is not None:
            command.extend(["--dimensions", str(dimensions)])
        payload = run_native(command, "tessera", timeout=600)
        arrays = load_safetensors(output_path)
        embeddings = arrays.get("embeddings")
        if embeddings is None:
            raise GraphProviderError("native mere.run geo tessera did not emit embeddings")
        return embeddings.astype(np.float32, copy=False), native_metadata(payload)


def native_olmoearth_forward(
    inputs: dict[str, np.ndarray],
    output_path: pathlib.Path,
    executable: str,
    model: str | None,
    patch_size: int,
    input_resolution: float,
    include_tokens: bool,
) -> JsonMap:
    with tempfile.TemporaryDirectory(prefix="mere-olmoearth-native-") as raw_directory:
        input_path = pathlib.Path(raw_directory) / "input.safetensors"
        save_safetensors(inputs, input_path, {"format": "mere.geo/olmoearth-grid-v1"})
        command = [
            executable,
            "geo",
            "olmoearth",
            str(input_path),
            "--output",
            str(output_path),
            "--patch-size",
            str(patch_size),
            "--input-resolution",
            str(input_resolution),
            "--json",
        ]
        if model and model != "auto":
            command.extend(["--model", model])
        if include_tokens:
            command.append("--include-tokens")
        return native_metadata(run_native(command, "olmoearth", timeout=900))


def run_native(command: list[str], name: str, timeout: int) -> JsonMap:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GraphProviderError(f"native mere.run geo {name} failed: {exc}") from None
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise GraphProviderError(f"native mere.run geo {name} failed: {detail}")
    try:
        return as_map(json.loads(result.stdout), f"native geo {name} result")
    except (json.JSONDecodeError, GraphProviderError) as exc:
        raise GraphProviderError(f"native mere.run geo {name} returned invalid JSON") from exc


def save_safetensors(
    arrays: dict[str, np.ndarray],
    path: pathlib.Path,
    metadata: dict[str, str],
) -> None:
    from safetensors.numpy import save_file

    save_file(arrays, str(path), metadata=metadata)


def load_safetensors(path: pathlib.Path) -> dict[str, np.ndarray]:
    from safetensors.numpy import load_file

    return load_file(str(path))


def native_metadata(payload: JsonMap) -> JsonMap:
    return {
        key: payload[key]
        for key in [
            "status",
            "model_id",
            "variant",
            "batch_size",
            "device",
            "model_load_seconds",
            "inference_seconds",
        ]
        if key in payload
    }


def model_manifest(catalog: dict[str, JsonMap], selected_model: object, **extra: object) -> JsonMap:
    model_id = str(selected_model) if selected_model is not None else "unknown"
    spec = next((value for value in catalog.values() if value["id"] == model_id), None)
    value: JsonMap = {"native_model_id": model_id, "framework": "mere.run Swift/MLX", **extra}
    if spec:
        value.update(
            {
                "repository": spec["repository"],
                "revision": spec["revision"],
                "native_weights_sha256": spec["weights_sha256"],
                "variant": next(name for name, candidate in catalog.items() if candidate is spec),
            }
        )
    return value


def input_manifest(bundle: JsonMap) -> JsonMap:
    return {
        "digest": bundle["input_digest"],
        "artifacts": bundle["artifacts"],
        "sources": bundle["sources"],
        "grid": bundle["grid"],
    }


def write_embedding_manifest(
    path: pathlib.Path,
    manifest: JsonMap,
    locations: dict[str, pathlib.Path],
) -> None:
    outputs = as_map(manifest["outputs"], "outputs")
    for name, output_path in locations.items():
        if name == "manifest":
            continue
        outputs[name] = {
            "path": output_path.name,
            "sha256": sha256_file(output_path),
            "content_type": "application/vnd.safetensors",
        }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

from __future__ import annotations

import json
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray

from mere_workflow_tools.graph_sdk import GraphProviderError, JsonMap, as_map

from .bundle import confined_bundle_path, load_bundle, sha256_file
from .constants import (
    FLOOD_MEANS,
    FLOOD_STDS,
    MODEL_CHECKPOINT,
    MODEL_CHECKPOINT_SHA256,
    MODEL_CONFIG_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    NATIVE_MODEL_ID,
    NATIVE_WEIGHTS_SHA256,
    THOR_CHECKPOINT_BYTES,
    THOR_MODEL_ID,
    THOR_REVISION,
)
from .provider import CandidateResult

FloatArray = NDArray[np.float32]


@dataclass(frozen=True)
class FloodTile:
    batch: int
    y: slice
    x: slice
    data: dict[str, FloatArray]


def execute_candidate(
    bundle_root: pathlib.Path, locations: dict[str, pathlib.Path], requested_device: str
) -> CandidateResult:
    import rasterio
    import zarr
    from PIL import Image
    from rasterio.transform import Affine

    bundle = load_bundle(bundle_root)
    artifacts = as_map(bundle["artifacts"], "input artifacts")
    s2 = load_zarr(zarr, confined_bundle_path(bundle_root, artifact_path(artifacts, "S2L2A")))
    s1 = load_zarr(zarr, confined_bundle_path(bundle_root, artifact_path(artifacts, "S1RTC")))
    with rasterio.open(confined_bundle_path(bundle_root, artifact_path(artifacts, "DEM"))) as source:
        dem = source.read().astype(np.float32)

    tensors = {
        "S2L2A": normalized_array(s2.transpose(1, 0, 2, 3), FLOOD_MEANS["S2L2A"], FLOOD_STDS["S2L2A"]),
        "S1RTC": normalized_array(s1.transpose(1, 0, 2, 3), FLOOD_MEANS["S1RTC"], FLOOD_STDS["S1RTC"]),
        "DEM": normalized_array(
            np.repeat(dem[:, None, :, :], 4, axis=1),
            FLOOD_MEANS["DEM"],
            FLOOD_STDS["DEM"],
        ),
    }
    if requested_device not in {"auto", "metal"}:
        raise GraphProviderError("TerraMind Flood executes through native mere.run Metal; use device=auto or device=metal")
    executable = resolve_mere_run_executable()
    if executable is None:
        raise GraphProviderError("mere.run is required for native TerraMind Flood inference")
    model_root = os.environ.get("MERE_TERRAMIND_FLOOD_MODEL")

    started = time.monotonic()
    logits, native_runs = tiled_native_inference(tensors, executable, model_root)
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponent = np.exp(shifted)
    probability = (exponent / exponent.sum(axis=1, keepdims=True))[0, 1].astype(np.float32)
    elapsed = time.monotonic() - started
    mask = (probability >= 0.5).astype(np.uint8)

    grid = as_map(bundle["grid"], "grid")
    transform = Affine(*cast(list[float], grid["transform"]))
    crs = cast(str, grid["crs"])
    write_cog(rasterio, locations["mask"], mask[None, :, :], crs, transform, "uint8", 255, "nearest")
    write_cog(
        rasterio, locations["probability"], probability[None, :, :], crs, transform, "float32", -9999.0, "average"
    )
    write_preview(Image, np, locations["preview"], s2[2], mask)

    ndvi = ndvi_comparison(np, s2, mask)
    pixel_area = float(grid["resolution_m"]) ** 2
    flood_pixels = int(mask.sum())
    total_pixels = int(mask.size)
    output_hashes = {
        "mask": sha256_file(locations["mask"]),
        "probability": sha256_file(locations["probability"]),
        "preview": sha256_file(locations["preview"]),
    }
    manifest: JsonMap = {
        "kind": "mere.geo/flood-candidate",
        "version": 1,
        "evidence_class": "candidate-only",
        "promotion_policy": "Requires independent authoritative corroboration and local validation.",
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "checkpoint": MODEL_CHECKPOINT,
            "checkpoint_sha256": MODEL_CHECKPOINT_SHA256,
            "config_sha256": MODEL_CONFIG_SHA256,
            "native_model_id": NATIVE_MODEL_ID,
            "native_weights_sha256": NATIVE_WEIGHTS_SHA256,
            "framework": "mere.run Swift/MLX",
            "decoder": "UNetDecoder",
            "precision": "float32",
            "runtime_command": "mere.run geo flood",
        },
        "input": {
            "digest": bundle["input_digest"],
            "artifacts": bundle["artifacts"],
            "timesteps": bundle["timesteps"],
            "grid": grid,
        },
        "execution": {
            "device": "metal",
            "platform": platform.platform(),
            "elapsed_seconds": round(elapsed, 3),
            "native_runs": native_runs,
            "crop": 256,
            "stride": 208,
            "delta": 8,
            "threshold": 0.5,
        },
        "summary": {
            "flood_pixels": flood_pixels,
            "total_pixels": total_pixels,
            "candidate_fraction": round(flood_pixels / total_pixels, 8),
            "candidate_area_square_metres": round(flood_pixels * pixel_area, 3),
        },
        "outputs": {
            name: {
                "path": locations[name].name,
                "sha256": output_hashes[name],
                "cog": name in {"mask", "probability"},
                "crs": crs if name in {"mask", "probability"} else None,
            }
            for name in ["mask", "probability", "preview"]
        },
        "comparison": {
            "local_ndvi_cue": ndvi,
            "newer_backbone_challenger": {
                "model_id": THOR_MODEL_ID,
                "revision": THOR_REVISION,
                "checkpoint_bytes": THOR_CHECKPOINT_BYTES,
                "released": "2026-01-30",
                "common_modalities": ["Sentinel-1", "Sentinel-2"],
                "published_sen1floods11_miou_10_percent": 86.29,
                "published_terramind_b_sen1floods11_miou_10_percent": 84.43,
                "local_mask_metric": None,
                "status": "backbone-only",
                "reason": "No pinned ImpactMesh flood head exists, so a local mask comparison would not be honest or reproducible.",
            },
            "interpretation": "Agreement is not accuracy; this demo has no pixel-level authoritative flood label.",
        },
    }
    locations["manifest"].write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    metrics: JsonMap = {
        "name": "candidate_flood_fraction",
        "value": manifest["summary"]["candidate_fraction"],
        "unit": "ratio",
        "evidence_class": "candidate-only",
    }
    return CandidateResult(outputs=locations, metrics=metrics)


def artifact_path(artifacts: JsonMap, name: str) -> str:
    value = as_map(artifacts[name], f"artifact {name}").get("path")
    if not isinstance(value, str):
        raise GraphProviderError(f"artifact {name} path is invalid")
    return value


def load_zarr(zarr_module: object, path: pathlib.Path) -> object:
    store = zarr_module.ZipStore(str(path), mode="r")
    try:
        root = zarr_module.open_consolidated(store, mode="r")
        return root["bands"][...]
    finally:
        store.close()


def normalized_array(value: object, means: list[float], stds: list[float]) -> FloatArray:
    tensor = np.asarray(value, dtype=np.float32)
    mean = np.asarray(means, dtype=np.float32)[:, None, None, None]
    std = np.asarray(stds, dtype=np.float32)[:, None, None, None]
    return ((tensor - mean) / std)[None, ...]


def resolve_mere_run_executable() -> str | None:
    override = os.environ.get("MERE_RUN_EXECUTABLE")
    if override:
        candidate = pathlib.Path(override).expanduser().resolve()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return None
    return shutil.which("mere.run")


def tiled_native_inference(
    tensors: dict[str, FloatArray],
    executable: str,
    model_root: str | None,
) -> tuple[FloatArray, list[JsonMap]]:
    crop = 256
    stride = 208
    delta = 8
    values = list(tensors.values())
    if not values or any(value.ndim != 5 for value in values):
        raise GraphProviderError("TerraMind inputs must be B,C,T,H,W arrays")
    shapes = {(value.shape[0], value.shape[-2], value.shape[-1]) for value in values}
    if len(shapes) != 1:
        raise GraphProviderError("TerraMind modalities must share batch and image dimensions")
    batch_size, height, width = next(iter(shapes))
    padded = {
        name: np.pad(value, ((0, 0), (0, 0), (0, 0), (delta, delta), (delta, delta)), mode="reflect")
        for name, value in tensors.items()
    }
    padded_height = height + 2 * delta
    padded_width = width + 2 * delta
    blend = blend_mask(crop, stride, delta)
    tiles: list[FloodTile] = []

    def append_tiles(row: int, column: int) -> None:
        for batch in range(batch_size):
            tiles.append(
                FloodTile(
                    batch=batch,
                    y=slice(row + delta, row + crop - delta),
                    x=slice(column + delta, column + crop - delta),
                    data={
                        name: value[batch, ..., row : row + crop, column : column + crop]
                        for name, value in padded.items()
                    },
                )
            )

    for row in range(0, padded_height - crop - 1, stride):
        append_tiles(row, padded_width - crop)
    for column in range(0, padded_width - crop - 1, stride):
        append_tiles(padded_height - crop, column)
    append_tiles(padded_height - crop, padded_width - crop)
    for row in range(0, padded_height - crop - 1, stride):
        for column in range(0, padded_width - crop - 1, stride):
            append_tiles(row, column)

    predictions: list[tuple[FloodTile, FloatArray]] = []
    native_runs: list[JsonMap] = []
    for start in range(0, len(tiles), 4):
        tile_batch = tiles[start : start + 4]
        native_inputs = {
            name: np.ascontiguousarray(np.stack([tile.data[name] for tile in tile_batch], axis=0))
            for name in tensors
        }
        native_logits, metadata = native_flood_forward(native_inputs, executable, model_root)
        if tuple(native_logits.shape) != (len(tile_batch), 2, crop, crop):
            raise GraphProviderError(
                f"native TerraMind logits have invalid shape {tuple(native_logits.shape)}"
            )
        predictions.extend(zip(tile_batch, native_logits, strict=True))
        native_runs.append(metadata)

    output = np.zeros((batch_size, 2, padded_height, padded_width), dtype=np.float32)
    counts = np.zeros((batch_size, padded_height, padded_width), dtype=np.float32)
    output_crop = (slice(delta, crop - delta), slice(delta, crop - delta))
    for tile, prediction in predictions:
        cropped = prediction[:, output_crop[0], output_crop[1]]
        output[tile.batch, :, tile.y, tile.x] += cropped * blend
        counts[tile.batch, tile.y, tile.x] += blend
    output = output[..., delta:-delta, delta:-delta]
    counts = counts[..., delta:-delta, delta:-delta]
    if np.any(counts == 0):
        raise GraphProviderError("some raster pixels did not receive a TerraMind classification")
    return output / counts[:, None, :, :], native_runs


def blend_mask(crop: int, stride: int, delta: int) -> FloatArray:
    overlap = min(crop // 2, crop - stride) - delta
    axis = np.ones(crop - 2 * delta, dtype=np.float32)
    if overlap:
        positions = np.arange(overlap, dtype=np.float32)
        ramp = np.cos(np.pi * (positions + 1) / (overlap + 1)) / 2 + 0.5
        axis[:overlap] = ramp[::-1]
        axis[-overlap:] = ramp
    return axis[:, None] * axis[None, :] + np.float32(1e-6)


def native_flood_forward(
    inputs: dict[str, FloatArray], executable: str, model_root: str | None
) -> tuple[FloatArray, JsonMap]:
    from safetensors.numpy import load_file, save_file

    with tempfile.TemporaryDirectory(prefix="mere-terramind-native-") as raw_directory:
        directory = pathlib.Path(raw_directory)
        input_path = directory / "input.safetensors"
        output_path = directory / "logits.safetensors"
        save_file(inputs, str(input_path), metadata={"format": "mere.run/terramind-flood-input-v1"})
        command = [executable, "geo", "flood", str(input_path), "--output", str(output_path), "--json"]
        if model_root:
            command.extend(["--model", model_root])
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
            raise GraphProviderError(f"native mere.run geo flood failed: {detail}")
        try:
            payload = as_map(json.loads(result.stdout), "native geo flood result")
        except (json.JSONDecodeError, GraphProviderError) as exc:
            raise GraphProviderError("native mere.run geo flood returned invalid JSON") from exc
        arrays = load_file(str(output_path))
        logits = arrays.get("logits")
        if logits is None:
            raise GraphProviderError("native mere.run geo flood did not emit logits")
        metadata: JsonMap = {
            key: payload[key]
            for key in ["status", "model_id", "batch_size", "device", "model_load_seconds", "inference_seconds"]
            if key in payload
        }
        return logits.astype("float32", copy=False), metadata


def ndvi_comparison(np: object, s2: object, mask: object) -> JsonMap:
    pre = ndvi(np, s2[1, 7], s2[1, 3])
    event = ndvi(np, s2[2, 7], s2[2, 3])
    change = event - pre
    cue = change <= -0.2
    intersection = int((cue & (mask == 1)).sum())
    union = int((cue | (mask == 1)).sum())
    cue_pixels = int(cue.sum())
    flood_pixels = int(mask.sum())
    return {
        "definition": "event minus pre-event NDVI <= -0.2",
        "cue_pixels": cue_pixels,
        "terramind_pixels": flood_pixels,
        "intersection_pixels": intersection,
        "union_pixels": union,
        "jaccard": round(intersection / union, 8) if union else None,
        "terramind_overlap_fraction": round(intersection / flood_pixels, 8) if flood_pixels else None,
        "ndvi_overlap_fraction": round(intersection / cue_pixels, 8) if cue_pixels else None,
    }


def ndvi(np: object, nir: object, red: object) -> object:
    denominator = nir + red
    return np.divide(nir - red, denominator, out=np.zeros_like(denominator, dtype=np.float32), where=denominator != 0)


def write_cog(
    rasterio_module: object,
    path: pathlib.Path,
    value: object,
    crs: str,
    transform: object,
    dtype: str,
    nodata: float | int,
    overview_resampling: str,
) -> None:
    with rasterio_module.open(
        path,
        "w",
        driver="COG",
        width=value.shape[-1],
        height=value.shape[-2],
        count=value.shape[0],
        dtype=dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="DEFLATE",
        blocksize=256,
        overview_resampling=overview_resampling,
    ) as destination:
        destination.write(value)


def write_preview(image_module: object, np: object, path: pathlib.Path, event_s2: object, mask: object) -> None:
    rgb = event_s2[[3, 2, 1]].transpose(1, 2, 0).astype(np.float32)
    low = np.percentile(rgb, 2, axis=(0, 1), keepdims=True)
    high = np.percentile(rgb, 98, axis=(0, 1), keepdims=True)
    rgb = np.clip((rgb - low) / np.maximum(high - low, 1), 0, 1)
    overlay = (rgb * 255).astype(np.uint8)
    overlay[mask == 1] = (0.45 * overlay[mask == 1] + 0.55 * np.array([255, 48, 48])).astype(np.uint8)
    image_module.fromarray(overlay, mode="RGB").save(path)

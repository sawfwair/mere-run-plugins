from __future__ import annotations

import json
import pathlib
import platform
import tempfile
import time
from typing import cast

from mere_workflow_tools.graph_sdk import GraphProviderError, JsonMap, as_map

from .bundle import confined_bundle_path, load_bundle, sha256_file
from .constants import (
    FLOOD_MEANS,
    FLOOD_STDS,
    MODEL_CHECKPOINT,
    MODEL_CONFIG,
    MODEL_ID,
    MODEL_REVISION,
    THOR_CHECKPOINT_BYTES,
    THOR_MODEL_ID,
    THOR_REVISION,
)
from .provider import CandidateResult


def execute_candidate(
    bundle_root: pathlib.Path, locations: dict[str, pathlib.Path], requested_device: str
) -> CandidateResult:
    import numpy as np
    import rasterio
    import torch
    import zarr
    from huggingface_hub import hf_hub_download
    from PIL import Image
    from rasterio.transform import Affine
    from terratorch.cli_tools import LightningInferenceModel
    from terratorch.tasks.tiled_inference import tiled_inference

    bundle = load_bundle(bundle_root)
    artifacts = as_map(bundle["artifacts"], "input artifacts")
    s2 = load_zarr(zarr, confined_bundle_path(bundle_root, artifact_path(artifacts, "S2L2A")))
    s1 = load_zarr(zarr, confined_bundle_path(bundle_root, artifact_path(artifacts, "S1RTC")))
    with rasterio.open(confined_bundle_path(bundle_root, artifact_path(artifacts, "DEM"))) as source:
        dem = source.read().astype(np.float32)

    tensors = {
        "S2L2A": normalized_tensor(torch, s2.transpose(1, 0, 2, 3), FLOOD_MEANS["S2L2A"], FLOOD_STDS["S2L2A"]),
        "S1RTC": normalized_tensor(torch, s1.transpose(1, 0, 2, 3), FLOOD_MEANS["S1RTC"], FLOOD_STDS["S1RTC"]),
        "DEM": normalized_tensor(
            torch,
            np.repeat(dem[:, None, :, :], 4, axis=1),
            FLOOD_MEANS["DEM"],
            FLOOD_STDS["DEM"],
        ),
    }
    device = select_device(torch, requested_device)
    config_path = pathlib.Path(
        hf_hub_download(repo_id=MODEL_ID, filename=MODEL_CONFIG, revision=MODEL_REVISION)
    )
    checkpoint_path = hf_hub_download(repo_id=MODEL_ID, filename=MODEL_CHECKPOINT, revision=MODEL_REVISION)
    checkpoint_hash = sha256_file(pathlib.Path(checkpoint_path))
    config_hash = sha256_file(config_path)
    runtime_config = inference_config(config_path, device)
    try:
        task = LightningInferenceModel.from_config(str(runtime_config), checkpoint_path)
    finally:
        runtime_config.unlink(missing_ok=True)
    task.model.eval()
    task.model.to(device)

    def model_forward(value: object, **kwargs: object) -> object:
        return task.model(value, **kwargs).output

    started = time.monotonic()
    with torch.no_grad():
        logits = tiled_inference(
            model_forward,
            tensors,
            crop=256,
            stride=208,
            batch_size=1 if device == "cpu" else 4,
            delta=8,
            verbose=False,
            device=device,
        )
        probability = torch.softmax(logits, dim=1)[0, 1].cpu().numpy().astype(np.float32)
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
            "checkpoint_sha256": checkpoint_hash,
            "config_sha256": config_hash,
            "framework": "terratorch==1.2.10",
            "decoder": "UNetDecoder",
            "runtime_config_overrides": {
                "trainer.logger": False,
                "trainer.callbacks": [],
                "trainer.enable_checkpointing": False,
                "trainer.accelerator": device,
                "trainer.devices": 1,
                "trainer.precision": "32-true" if device == "cpu" else "16-mixed",
            },
        },
        "input": {
            "digest": bundle["input_digest"],
            "artifacts": bundle["artifacts"],
            "timesteps": bundle["timesteps"],
            "grid": grid,
        },
        "execution": {
            "device": device,
            "platform": platform.platform(),
            "elapsed_seconds": round(elapsed, 3),
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


def inference_config(source: pathlib.Path, device: str) -> pathlib.Path:
    import yaml

    payload = yaml.safe_load(source.read_text())
    if not isinstance(payload, dict):
        raise GraphProviderError("TerraMind model config must be an object")
    payload["trainer"] = {
        "accelerator": device,
        "devices": 1,
        "logger": False,
        "callbacks": [],
        "enable_checkpointing": False,
        "precision": "32-true" if device == "cpu" else "16-mixed",
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="mere-terramind-", delete=False
    ) as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)
        return pathlib.Path(handle.name)


def load_zarr(zarr_module: object, path: pathlib.Path) -> object:
    store = zarr_module.ZipStore(str(path), mode="r")
    try:
        root = zarr_module.open_consolidated(store, mode="r")
        return root["bands"][...]
    finally:
        store.close()


def normalized_tensor(torch_module: object, value: object, means: list[float], stds: list[float]) -> object:
    tensor = torch_module.from_numpy(value).float()
    mean = torch_module.tensor(means, dtype=tensor.dtype)[:, None, None, None]
    std = torch_module.tensor(stds, dtype=tensor.dtype)[:, None, None, None]
    return ((tensor - mean) / std).unsqueeze(0)


def select_device(torch_module: object, requested: str) -> str:
    if requested == "mps":
        raise GraphProviderError("MPS is blocked for the pinned TerraMind temporal UNet decoder")
    if requested == "auto":
        if torch_module.cuda.is_available():
            return "cuda"
        return "cpu"
    if requested == "rocm":
        if not torch_module.cuda.is_available() or torch_module.version.hip is None:
            raise GraphProviderError("ROCm was requested but is unavailable")
        return "cuda"
    if requested == "cuda" and not torch_module.cuda.is_available():
        raise GraphProviderError("CUDA was requested but is unavailable")
    return requested


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

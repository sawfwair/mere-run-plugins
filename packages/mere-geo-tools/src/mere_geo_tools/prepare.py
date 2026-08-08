from __future__ import annotations

import json
import math
import pathlib
import re
from datetime import timezone
from typing import cast

from mere_workflow_tools.graph_sdk import GraphProviderError, JsonMap, as_list, as_map

from .bundle import (
    BUNDLE_VERSION,
    FIRE_BUNDLE_KIND,
    FLOOD_BUNDLE_KIND,
    canonical_digest,
    load_bundle,
    sha256_file,
)
from .constants import (
    FIRE_MODEL_ID,
    FIRE_MODEL_REVISION,
    MODEL_ID,
    MODEL_REVISION,
    S1_BANDS,
    S2_BANDS,
    TEMPORAL_ROLES,
)

FLOOD_RECIPE_KIND = "mere.geo/terramind-flood-source-recipe"
FIRE_RECIPE_KIND = "mere.geo/terramind-fire-source-recipe"


def prepare_bundle(recipe_path: pathlib.Path, output_root: pathlib.Path) -> JsonMap:
    recipe_bytes = recipe_path.read_bytes()
    try:
        recipe = as_map(json.loads(recipe_bytes), "TerraMind preparation recipe")
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"invalid preparation recipe JSON: {exc}") from None
    validate_recipe(recipe)
    recipe_kind = cast(str, recipe["kind"])
    bundle_kind, model_id, model_revision = hazard_contract(recipe_kind)
    if output_root.exists() and any(output_root.iterdir()):
        existing = load_bundle(output_root)
        if existing.get("source_recipe_sha256") == sha256_bytes(recipe_bytes):
            return existing
        raise GraphProviderError(f"output directory already contains a different bundle: {output_root}")

    import numpy as np
    import planetary_computer as pc
    import pystac_client
    import rasterio
    import zarr
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import transform_bounds

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "S2L2A").mkdir()
    (output_root / "S1RTC").mkdir()
    (output_root / "DEM").mkdir()

    target = as_map(recipe["target"], "target")
    aoi = cast(list[float], target["aoi"])
    crs = cast(str, target["crs"])
    resolution = float(cast(int | float, target.get("resolution_m", 10)))
    block_multiple = cast(int, target.get("block_multiple", 64))
    min_size = cast(int, target.get("minimum_size", 256))
    projected_bounds = transform_bounds("EPSG:4326", crs, *aoi, densify_pts=21)
    left, bottom, right, top, width, height = aligned_grid(projected_bounds, resolution, block_multiple, min_size)
    transform = Affine(resolution, 0, left, 0, -resolution, top)

    endpoint = cast(str, recipe.get("stac_endpoint", "https://planetarycomputer.microsoft.com/api/stac/v1"))
    unsigned_catalog = pystac_client.Client.open(endpoint)
    signed_catalog = pystac_client.Client.open(endpoint, modifier=pc.sign_inplace)
    s2_stack = np.zeros((4, len(S2_BANDS), height, width), dtype=np.float32)
    s1_stack = np.zeros((4, len(S1_BANDS), height, width), dtype=np.float32)
    timestep_provenance: list[JsonMap] = []

    def read_asset(href: str, resampling: object, nodata: float) -> object:
        with (
            rasterio.open(href) as source,
            WarpedVRT(
                source,
                crs=crs,
                transform=transform,
                width=width,
                height=height,
                resampling=resampling,
                nodata=nodata,
                dtype="float32",
            ) as warped,
        ):
            return warped.read(1, masked=True).filled(nodata).astype(np.float32)

    for index, raw_step in enumerate(as_list(recipe["timesteps"], "timesteps")):
        step = as_map(raw_step, "timestep")
        s2_spec = as_map(step["S2L2A"], "S2L2A source")
        s1_spec = as_map(step["S1RTC"], "S1RTC source")
        s2_unsigned, s2_signed = paired_item(unsigned_catalog, signed_catalog, s2_spec)
        s1_unsigned, s1_signed = paired_item(unsigned_catalog, signed_catalog, s1_spec)
        s2_assets: list[JsonMap] = []
        s1_assets: list[JsonMap] = []
        for band_index, band in enumerate(S2_BANDS):
            unsigned_asset = s2_unsigned.assets[band]
            signed_asset = s2_signed.assets[band]
            s2_stack[index, band_index] = cast(object, read_asset(signed_asset.href, Resampling.bilinear, 0.0))
            s2_assets.append(asset_provenance(band, unsigned_asset))
        for band_index, band in enumerate(S1_BANDS):
            unsigned_asset = s1_unsigned.assets[band]
            signed_asset = s1_signed.assets[band]
            linear = cast(object, read_asset(signed_asset.href, Resampling.bilinear, float("nan")))
            valid = np.isfinite(linear) & (linear > 0)
            db = np.zeros((height, width), dtype=np.float32)
            db[valid] = 10.0 * np.log10(linear[valid])
            s1_stack[index, band_index] = db
            s1_assets.append(asset_provenance(band, unsigned_asset))
        scl = cast(object, read_asset(s2_signed.assets["SCL"].href, Resampling.nearest, 0.0))
        invalid_classes = np.isin(scl.astype(np.uint8), [0, 1, 3, 8, 9, 10, 11])
        timestep_provenance.append(
            {
                "role": step["role"],
                "S2L2A": item_provenance(s2_unsigned, s2_assets),
                "S1RTC": item_provenance(s1_unsigned, s1_assets),
                "quality": {"s2_invalid_pixel_fraction": round(float(invalid_classes.mean()), 6)},
            }
        )

    dem_spec = as_map(recipe["DEM"], "DEM source")
    dem_unsigned, dem_signed = paired_item(unsigned_catalog, signed_catalog, dem_spec)
    dem = cast(object, read_asset(dem_signed.assets["data"].href, Resampling.bilinear, -9999.0))
    dem = np.where(np.isfinite(dem), dem, -9999.0).astype(np.float32)[None, :, :]

    sample_id = cast(str, recipe["sample_id"])
    s2_path = output_root / "S2L2A" / f"{sample_id}_S2L2A.zarr.zip"
    s1_path = output_root / "S1RTC" / f"{sample_id}_S1RTC.zarr.zip"
    dem_path = output_root / "DEM" / f"{sample_id}_DEM.tif"
    write_zarr(zarr, s2_path, s2_stack)
    write_zarr(zarr, s1_path, s1_stack)
    write_cog(rasterio, dem_path, dem, crs, transform, "float32", -9999.0)

    artifact_paths = {"S2L2A": s2_path, "S1RTC": s1_path, "DEM": dem_path}
    artifacts: JsonMap = {}
    digest_entries: list[JsonMap] = []
    for name, path in artifact_paths.items():
        relative = path.relative_to(output_root).as_posix()
        digest = sha256_file(path)
        artifacts[name] = {"path": relative, "bytes": path.stat().st_size, "sha256": digest}
        digest_entries.append({"name": name, "path": relative, "sha256": digest})

    manifest: JsonMap = {
        "kind": bundle_kind,
        "version": BUNDLE_VERSION,
        "sample_id": sample_id,
        "source_recipe_sha256": sha256_bytes(recipe_bytes),
        "model": {"id": model_id, "revision": model_revision},
        "aoi": {"bounds_wgs84": aoi},
        "grid": {
            "crs": crs,
            "transform": list(transform)[:6],
            "width": width,
            "height": height,
            "resolution_m": resolution,
            "bounds": [left, bottom, right, top],
        },
        "timesteps": timestep_provenance,
        "DEM": item_provenance(dem_unsigned, [asset_provenance("data", dem_unsigned.assets["data"])]),
        "modalities": {
            "S2L2A": {"bands": S2_BANDS, "shape": [4, 12, height, width], "units": "surface_reflectance_dn"},
            "S1RTC": {"bands": S1_BANDS, "shape": [4, 2, height, width], "units": "gamma0_db"},
            "DEM": {"bands": ["elevation"], "shape": [1, height, width], "units": "metres"},
        },
        "artifacts": artifacts,
        "input_digest": canonical_digest(digest_entries),
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return load_bundle(output_root)


def validate_recipe(recipe: JsonMap) -> None:
    if recipe.get("kind") not in {FLOOD_RECIPE_KIND, FIRE_RECIPE_KIND} or recipe.get("version") != 1:
        raise GraphProviderError("unsupported TerraMind hazard source recipe")
    if not isinstance(recipe.get("sample_id"), str):
        raise GraphProviderError("source recipe sample_id is required")
    target = as_map(recipe.get("target"), "target")
    aoi = as_list(target.get("aoi"), "target.aoi")
    if len(aoi) != 4 or any(not isinstance(value, (int, float)) for value in aoi):
        raise GraphProviderError("target.aoi must be [west,south,east,north]")
    west, south, east, north = cast(list[float], aoi)
    if not all(math.isfinite(value) for value in aoi) or not (
        -180 <= west < east <= 180 and -90 <= south < north <= 90
    ):
        raise GraphProviderError("target.aoi must be finite ordered WGS84 bounds")
    crs_value = target.get("crs")
    if not isinstance(crs_value, str) or not crs_value.strip():
        raise GraphProviderError("target.crs is required")
    epsg_match = re.fullmatch(r"EPSG:(\d+)", crs_value.strip().upper())
    if epsg_match is None:
        raise GraphProviderError(f"target.crs is invalid: {crs_value}") from None
    epsg = int(epsg_match.group(1))
    if epsg not in range(32601, 32661) and epsg not in range(32701, 32761):
        raise GraphProviderError("target.crs must be a WGS84 UTM projected CRS with metre units")
    timesteps = as_list(recipe.get("timesteps"), "timesteps")
    roles = [as_map(item, "timestep").get("role") for item in timesteps]
    if roles != TEMPORAL_ROLES:
        raise GraphProviderError(f"source recipe roles must be ordered as {TEMPORAL_ROLES}")
    for raw_step in timesteps:
        step = as_map(raw_step, "timestep")
        for modality in ["S2L2A", "S1RTC"]:
            validate_item_spec(as_map(step.get(modality), modality))
    validate_item_spec(as_map(recipe.get("DEM"), "DEM"))


def hazard_contract(recipe_kind: str) -> tuple[str, str, str]:
    if recipe_kind == FLOOD_RECIPE_KIND:
        return FLOOD_BUNDLE_KIND, MODEL_ID, MODEL_REVISION
    if recipe_kind == FIRE_RECIPE_KIND:
        return FIRE_BUNDLE_KIND, FIRE_MODEL_ID, FIRE_MODEL_REVISION
    raise GraphProviderError(f"unsupported TerraMind hazard source recipe: {recipe_kind}")


def validate_item_spec(spec: JsonMap) -> None:
    for field in ["collection", "item"]:
        if not isinstance(spec.get(field), str) or not spec[field]:
            raise GraphProviderError(f"source item {field} is required")


def paired_item(unsigned_catalog: object, signed_catalog: object, spec: JsonMap) -> tuple[object, object]:
    collection_id = cast(str, spec["collection"])
    item_id = cast(str, spec["item"])
    unsigned = unsigned_catalog.get_collection(collection_id).get_item(item_id)
    signed = signed_catalog.get_collection(collection_id).get_item(item_id)
    if unsigned is None or signed is None:
        raise GraphProviderError(f"STAC item is unavailable: {collection_id}/{item_id}")
    return unsigned, signed


def aligned_grid(
    bounds: tuple[float, float, float, float], resolution: float, block_multiple: int, min_size: int
) -> tuple[float, float, float, float, int, int]:
    min_x, min_y, max_x, max_y = bounds
    width = max(min_size, math.ceil((max_x - min_x) / resolution / block_multiple) * block_multiple)
    height = max(min_size, math.ceil((max_y - min_y) / resolution / block_multiple) * block_multiple)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    left = math.floor((center_x - width * resolution / 2) / resolution) * resolution
    top = math.ceil((center_y + height * resolution / 2) / resolution) * resolution
    right = left + width * resolution
    bottom = top - height * resolution
    return left, bottom, right, top, width, height


def asset_provenance(name: str, asset: object) -> JsonMap:
    extra = cast(JsonMap, asset.extra_fields)
    value: JsonMap = {"name": name, "href": str(asset.href).split("?", 1)[0]}
    for key in ["file:size", "file:checksum"]:
        if key in extra:
            value[key] = extra[key]
    return value


def item_provenance(item: object, assets: list[JsonMap]) -> JsonMap:
    observed = item.datetime
    return {
        "collection": item.collection_id,
        "item": item.id,
        "observed_at": observed.astimezone(timezone.utc).isoformat() if observed else None,
        "assets": assets,
    }


def write_zarr(zarr_module: object, path: pathlib.Path, array: object) -> None:
    store = zarr_module.ZipStore(str(path), mode="w")
    try:
        group = zarr_module.group(store=store)
        height, width = array.shape[-2:]
        group.create_dataset(
            "bands",
            data=array,
            chunks=(1, 1, min(256, height), min(256, width)),
            overwrite=True,
        )
        zarr_module.consolidate_metadata(store)
    finally:
        store.close()


def write_cog(
    rasterio_module: object,
    path: pathlib.Path,
    array: object,
    crs: str,
    transform: object,
    dtype: str,
    nodata: float | int,
) -> None:
    with rasterio_module.open(
        path,
        "w",
        driver="COG",
        width=array.shape[-1],
        height=array.shape[-2],
        count=array.shape[0],
        dtype=dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="DEFLATE",
        blocksize=256,
        overview_resampling="nearest",
    ) as destination:
        destination.write(array)


def sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()

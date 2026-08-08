from __future__ import annotations

import json
import math
import pathlib
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import cast

from mere_workflow_tools.graph_sdk import GraphProviderError, JsonMap, as_list, as_map

from .bundle import (
    BUNDLE_VERSION,
    OLMOEARTH_BUNDLE_KIND,
    TESSERA_BUNDLE_KIND,
    canonical_digest,
    load_bundle,
    sha256_file,
)
from .constants import (
    OLMOEARTH_LANDSAT_BANDS,
    OLMOEARTH_LANDSAT_SOURCE_CONTRACT,
    OLMOEARTH_S2_BANDS,
    PLANETARY_COMPUTER_STAC_ENDPOINT,
    S1_BANDS,
    TESSERA_S2_BANDS,
    USGS_LANDSAT_ASSETS,
    USGS_LANDSAT_AWS_REGION,
    USGS_LANDSAT_COLLECTION,
    USGS_LANDSAT_STAC_ENDPOINT,
)
from .prepare import aligned_grid, asset_provenance, item_provenance, paired_item, sha256_bytes

TESSERA_RECIPE_KIND = "mere.geo/tessera-v2-source-recipe"
OLMOEARTH_RECIPE_KIND = "mere.geo/olmoearth-v1.2-source-recipe"


def prepare_embedding_bundle(recipe_path: pathlib.Path, output_root: pathlib.Path) -> JsonMap:
    recipe_bytes = recipe_path.read_bytes()
    try:
        recipe = as_map(json.loads(recipe_bytes), "embedding preparation recipe")
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"invalid preparation recipe JSON: {exc}") from None
    validate_embedding_recipe(recipe)
    expected_kind = (
        TESSERA_BUNDLE_KIND if recipe["kind"] == TESSERA_RECIPE_KIND else OLMOEARTH_BUNDLE_KIND
    )
    if output_root.exists() and any(output_root.iterdir()):
        existing = load_bundle(output_root, expected_kinds={expected_kind})
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

    target = as_map(recipe["target"], "target")
    aoi = cast(list[float], target["aoi"])
    crs = cast(str, target["crs"])
    resolution = float(cast(int | float, target.get("resolution_m", 10)))
    block_multiple = cast(int, target.get("block_multiple", 16))
    min_size = cast(int, target.get("minimum_size", 16))
    projected_bounds = transform_bounds("EPSG:4326", crs, *aoi, densify_pts=21)
    left, bottom, right, top, width, height = aligned_grid(
        projected_bounds, resolution, block_multiple, min_size
    )
    transform = Affine(resolution, 0, left, 0, -resolution, top)
    default_endpoint = stac_endpoint(
        recipe.get("stac_endpoint", PLANETARY_COMPUTER_STAC_ENDPOINT),
        "source recipe stac_endpoint",
    )
    catalog_cache: dict[str, tuple[object, object]] = {}

    def catalogs_for_spec(spec: JsonMap) -> tuple[object, object, str]:
        endpoint = stac_endpoint(spec.get("stac_endpoint", default_endpoint), "source item stac_endpoint")
        if endpoint not in catalog_cache:
            unsigned_catalog = pystac_client.Client.open(endpoint)
            if endpoint == PLANETARY_COMPUTER_STAC_ENDPOINT:
                signed_catalog = pystac_client.Client.open(endpoint, modifier=pc.sign_inplace)
            else:
                signed_catalog = pystac_client.Client.open(endpoint)
            catalog_cache[endpoint] = (unsigned_catalog, signed_catalog)
        unsigned_catalog, signed_catalog = catalog_cache[endpoint]
        return unsigned_catalog, signed_catalog, endpoint

    def read_asset(href: str, resampling: object, nodata: float, requester_pays: bool) -> object:
        environment = (
            {"AWS_REQUEST_PAYER": "requester", "AWS_REGION": USGS_LANDSAT_AWS_REGION}
            if requester_pays
            else {}
        )
        try:
            with (
                rasterio.Env(**environment),
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
        except rasterio.errors.RasterioIOError as exc:
            if requester_pays:
                raise GraphProviderError(
                    "USGS Landsat Level-1 access failed. The official usgs-landsat S3 bucket is "
                    "requester-pays and requires authenticated AWS credentials with billing enabled."
                ) from exc
            raise

    output_root.mkdir(parents=True, exist_ok=True)
    sample_id = cast(str, recipe["sample_id"])
    arrays: dict[str, object] = {}
    modalities: JsonMap = {}
    provenance: JsonMap = {}
    manifest_extra: JsonMap = {}
    if recipe["kind"] == TESSERA_RECIPE_KIND:
        observations = as_map(recipe["observations"], "observations")
        s2, s2_valid, s2_doy, s2_provenance = read_sequence(
            observations["S2"],
            TESSERA_S2_BANDS,
            catalogs_for_spec,
            read_asset,
            Resampling,
            np,
            mode="reflectance",
            include_scl=True,
        )
        arrays["S2"] = s2
        arrays["S2_VALID"] = s2_valid
        modalities["S2"] = {
            "bands": TESSERA_S2_BANDS,
            "shape": list(s2.shape),
            "units": "surface_reflectance_dn",
            "doy": s2_doy,
        }
        provenance["S2"] = s2_provenance
        manifest_extra["S2_DOY"] = s2_doy
        for name in ["S1_ASC", "S1_DESC"]:
            raw_sequence = observations.get(name)
            if raw_sequence is None:
                continue
            values, _, doy, source_provenance = read_sequence(
                raw_sequence,
                S1_BANDS,
                catalogs_for_spec,
                read_asset,
                Resampling,
                np,
                mode="tessera_radar",
                include_scl=False,
            )
            arrays[name] = values
            modalities[name] = {
                "bands": S1_BANDS,
                "shape": list(values.shape),
                "units": "tessera_scaled_gamma0_db",
                "doy": doy,
            }
            provenance[name] = source_provenance
            manifest_extra[f"{name}_DOY"] = doy
        model_family: JsonMap = {
            "name": "TESSERA-v2",
            "selection": "hardware-aware at execution unless model is explicit",
        }
        bundle_kind = TESSERA_BUNDLE_KIND
    else:
        timesteps = as_list(recipe["timesteps"], "timesteps")
        timestamps = [timestamp_components(as_map(step, "timestep")["observed_at"]) for step in timesteps]
        modality_contracts = {
            "S2L2A": (OLMOEARTH_S2_BANDS, "reflectance", "surface_reflectance_dn"),
            "S1RTC": (S1_BANDS, "radar_db", "gamma0_db"),
            "LANDSAT": (OLMOEARTH_LANDSAT_BANDS, "landsat_level1_dn", "level1_dn"),
        }
        for name, (bands, mode, units) in modality_contracts.items():
            if name not in as_map(timesteps[0], "timestep"):
                continue
            specs = [as_map(step, "timestep")[name] for step in timesteps]
            values, _, _, source_provenance = read_sequence(
                specs,
                bands,
                catalogs_for_spec,
                read_asset,
                Resampling,
                np,
                mode=mode,
                include_scl=False,
                default_assets=USGS_LANDSAT_ASSETS if name == "LANDSAT" else None,
            )
            arrays[name] = values
            modalities[name] = {
                "bands": bands,
                "shape": list(values.shape),
                "units": units,
            }
            if name == "LANDSAT":
                modalities[name]["source_contract"] = OLMOEARTH_LANDSAT_SOURCE_CONTRACT
            provenance[name] = source_provenance
        manifest_extra["timestamps"] = timestamps
        model_family = {
            "name": "OlmoEarth-v1.2",
            "selection": "hardware-aware at execution unless model is explicit",
            "license_policy": "upstream artifact license applies",
        }
        bundle_kind = OLMOEARTH_BUNDLE_KIND

    artifacts: JsonMap = {}
    digest_entries: list[JsonMap] = []
    for name, array in arrays.items():
        directory = output_root / name
        directory.mkdir()
        path = directory / f"{sample_id}_{name}.zarr.zip"
        write_zarr(zarr, path, array)
        relative = path.relative_to(output_root).as_posix()
        digest = sha256_file(path)
        artifacts[name] = {"path": relative, "bytes": path.stat().st_size, "sha256": digest}
        digest_entries.append({"name": name, "path": relative, "sha256": digest})

    manifest: JsonMap = {
        "kind": bundle_kind,
        "version": BUNDLE_VERSION,
        "sample_id": sample_id,
        "source_recipe_sha256": sha256_bytes(recipe_bytes),
        "model_family": model_family,
        "aoi": {"bounds_wgs84": aoi},
        "grid": {
            "crs": crs,
            "transform": list(transform)[:6],
            "width": width,
            "height": height,
            "resolution_m": resolution,
            "bounds": [left, bottom, right, top],
        },
        "modalities": modalities,
        "sources": provenance,
        "artifacts": artifacts,
        "input_digest": canonical_digest(digest_entries),
        **manifest_extra,
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return load_bundle(output_root, expected_kinds={bundle_kind})


def validate_embedding_recipe(recipe: JsonMap) -> None:
    kind = recipe.get("kind")
    if kind not in {TESSERA_RECIPE_KIND, OLMOEARTH_RECIPE_KIND} or recipe.get("version") != 1:
        raise GraphProviderError("unsupported embedding source recipe")
    if not isinstance(recipe.get("sample_id"), str) or not recipe["sample_id"]:
        raise GraphProviderError("source recipe sample_id is required")
    default_endpoint = stac_endpoint(
        recipe.get("stac_endpoint", PLANETARY_COMPUTER_STAC_ENDPOINT),
        "source recipe stac_endpoint",
    )
    validate_target(as_map(recipe.get("target"), "target"))
    if kind == TESSERA_RECIPE_KIND:
        observations = as_map(recipe.get("observations"), "observations")
        validate_sequence(observations.get("S2"), "observations.S2", 256)
        radar_count = 0
        for name in ["S1_ASC", "S1_DESC"]:
            if name in observations:
                validate_sequence(observations[name], f"observations.{name}", 256)
                radar_count += 1
        if radar_count == 0:
            raise GraphProviderError("TESSERA recipe requires S1_ASC or S1_DESC observations")
    else:
        timesteps = as_list(recipe.get("timesteps"), "timesteps")
        if not 1 <= len(timesteps) <= 12:
            raise GraphProviderError("OlmoEarth recipe requires between 1 and 12 timesteps")
        first = as_map(timesteps[0], "timestep")
        modalities = {name for name in ["S2L2A", "S1RTC", "LANDSAT"] if name in first}
        if not modalities:
            raise GraphProviderError("OlmoEarth recipe requires S2L2A, S1RTC, or LANDSAT")
        for raw_step in timesteps:
            step = as_map(raw_step, "timestep")
            timestamp_components(step.get("observed_at"))
            if {name for name in ["S2L2A", "S1RTC", "LANDSAT"] if name in step} != modalities:
                raise GraphProviderError("OlmoEarth modalities must be present at every timestep")
            for name in modalities:
                spec = as_map(step[name], name)
                validate_item_spec(spec)
                if name == "LANDSAT":
                    validate_landsat_spec(spec, default_endpoint)


def validate_target(target: JsonMap) -> None:
    aoi = as_list(target.get("aoi"), "target.aoi")
    if len(aoi) != 4 or any(not isinstance(value, (int, float)) for value in aoi):
        raise GraphProviderError("target.aoi must be [west,south,east,north]")
    west, south, east, north = cast(list[float], aoi)
    if not all(math.isfinite(value) for value in aoi) or not (
        -180 <= west < east <= 180 and -90 <= south < north <= 90
    ):
        raise GraphProviderError("target.aoi must be finite ordered WGS84 bounds")
    crs = target.get("crs")
    match = re.fullmatch(r"EPSG:(\d+)", crs.strip().upper()) if isinstance(crs, str) else None
    if match is None:
        raise GraphProviderError(f"target.crs is invalid: {crs}")
    epsg = int(match.group(1))
    if epsg not in range(32601, 32661) and epsg not in range(32701, 32761):
        raise GraphProviderError("target.crs must be a WGS84 UTM projected CRS with metre units")


def validate_sequence(value: object, name: str, maximum: int) -> None:
    sequence = as_list(value, name)
    if not 1 <= len(sequence) <= maximum:
        raise GraphProviderError(f"{name} requires between 1 and {maximum} observations")
    for raw_spec in sequence:
        validate_item_spec(as_map(raw_spec, name))


def validate_item_spec(spec: JsonMap) -> None:
    for field in ["collection", "item"]:
        if not isinstance(spec.get(field), str) or not spec[field]:
            raise GraphProviderError(f"source item {field} is required")
    assets = spec.get("assets")
    if assets is not None:
        mapping = as_map(assets, "source item assets")
        if any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in mapping.items()
        ):
            raise GraphProviderError("source item assets must map canonical band names to STAC asset names")
    if "stac_endpoint" in spec:
        stac_endpoint(spec["stac_endpoint"], "source item stac_endpoint")


def validate_landsat_spec(spec: JsonMap, default_endpoint: str) -> None:
    endpoint = stac_endpoint(spec.get("stac_endpoint", default_endpoint), "OlmoEarth LANDSAT stac_endpoint")
    collection = spec.get("collection")
    if collection == "landsat-c2-l2":
        raise GraphProviderError(
            "Planetary Computer landsat-c2-l2 is incompatible with OlmoEarth LANDSAT: "
            "the model requires the raw 11-band OLI/TIRS Level-1 DN tensor"
        )
    if endpoint != USGS_LANDSAT_STAC_ENDPOINT or collection != USGS_LANDSAT_COLLECTION:
        raise GraphProviderError(
            "OlmoEarth LANDSAT requires the official USGS Level-1 source: "
            f"{USGS_LANDSAT_STAC_ENDPOINT} collection {USGS_LANDSAT_COLLECTION}"
        )
    if spec.get("source_contract") != OLMOEARTH_LANDSAT_SOURCE_CONTRACT:
        raise GraphProviderError(
            f"OlmoEarth LANDSAT source_contract must be {OLMOEARTH_LANDSAT_SOURCE_CONTRACT}"
        )
    if "assets" in spec:
        assets = as_map(spec["assets"], "OlmoEarth LANDSAT assets")
        missing = [band for band in OLMOEARTH_LANDSAT_BANDS if band not in assets]
        if missing:
            raise GraphProviderError(
                f"OlmoEarth LANDSAT assets are missing canonical bands: {', '.join(missing)}"
            )


def stac_endpoint(value: object, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"https://[^/\s]+(?:/[^\s]*)?", value) is None:
        raise GraphProviderError(f"{name} must be a non-empty HTTPS URL")
    return value.rstrip("/")


def timestamp_components(value: object) -> list[int]:
    if not isinstance(value, str):
        raise GraphProviderError("OlmoEarth timestep observed_at is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GraphProviderError(f"invalid OlmoEarth observed_at timestamp: {value}") from None
    if parsed.tzinfo is None:
        raise GraphProviderError("OlmoEarth observed_at must include a timezone")
    utc = parsed.astimezone(timezone.utc)
    return [utc.day, utc.month - 1, utc.year]


def read_sequence(
    raw_specs: object,
    bands: list[str],
    catalogs_for_spec: Callable[[JsonMap], tuple[object, object, str]],
    read_asset: object,
    resampling: object,
    np: object,
    mode: str,
    include_scl: bool,
    default_assets: dict[str, str] | None = None,
) -> tuple[object, object | None, list[int], list[JsonMap]]:
    specs = [as_map(value, "source item") for value in as_list(raw_specs, "source sequence")]
    values: list[object] = []
    validity: list[object] = []
    days: list[int] = []
    provenance: list[JsonMap] = []
    for spec in specs:
        unsigned_catalog, signed_catalog, endpoint = catalogs_for_spec(spec)
        unsigned, signed = paired_item(unsigned_catalog, signed_catalog, spec)
        if unsigned.datetime is None:
            raise GraphProviderError(f"STAC item has no observation datetime: {unsigned.collection_id}/{unsigned.id}")
        days.append(unsigned.datetime.astimezone(timezone.utc).timetuple().tm_yday)
        asset_overrides = {**(default_assets or {}), **cast(dict[str, str], spec.get("assets", {}))}
        source_bands: list[object] = []
        assets: list[JsonMap] = []
        for band in bands:
            asset_name = asset_overrides.get(band, band)
            try:
                unsigned_asset = unsigned.assets[asset_name]
                signed_asset = signed.assets[asset_name]
            except KeyError:
                raise GraphProviderError(
                    f"STAC item {unsigned.collection_id}/{unsigned.id} is missing asset {asset_name} for {band}"
                ) from None
            access_href, requester_pays = asset_read_access(signed_asset, endpoint)
            array = cast(object, read_asset(access_href, resampling.bilinear, 0.0, requester_pays))
            if mode in {"tessera_radar", "radar_db"}:
                valid = np.isfinite(array) & (array > 0)
                converted = np.zeros_like(array, dtype=np.float32)
                converted[valid] = 10.0 * np.log10(array[valid])
                if mode == "tessera_radar":
                    converted[valid] = (converted[valid] + 50.0) * 200.0
                array = converted
            source_bands.append(array)
            source_asset = asset_provenance(band, unsigned_asset)
            source_asset["access_href"] = access_href
            if requester_pays:
                source_asset["requester_pays"] = True
            assets.append(source_asset)
        values.append(np.stack(source_bands, axis=0).astype(np.float32))
        if include_scl:
            scl_name = asset_overrides.get("SCL", "SCL")
            try:
                scl_asset = signed.assets[scl_name]
            except KeyError:
                raise GraphProviderError(
                    f"STAC item {unsigned.collection_id}/{unsigned.id} is missing cloud mask asset {scl_name}"
                ) from None
            scl = cast(object, read_asset(scl_asset.href, resampling.nearest, 0.0, False))
            invalid = np.isin(scl.astype(np.uint8), [0, 1, 3, 8, 9, 10, 11])
            validity.append((~invalid).astype(np.uint8))
            assets.append(asset_provenance("SCL", unsigned.assets[scl_name]))
        source_provenance = item_provenance(unsigned, assets)
        source_provenance["stac_endpoint"] = endpoint
        if "source_contract" in spec:
            source_provenance["source_contract"] = spec["source_contract"]
        provenance.append(source_provenance)
    stacked = np.stack(values, axis=0).astype(np.float32)
    valid_stack = np.stack(validity, axis=0).astype(np.uint8) if validity else None
    return stacked, valid_stack, days, provenance


def asset_read_access(asset: object, endpoint: str) -> tuple[str, bool]:
    if endpoint != USGS_LANDSAT_STAC_ENDPOINT:
        return cast(str, asset.href), False
    extra = cast(JsonMap, asset.extra_fields)
    alternates = as_map(extra.get("alternate"), "USGS Landsat STAC asset alternate access")
    s3 = as_map(alternates.get("s3"), "USGS Landsat STAC asset S3 access")
    href = s3.get("href")
    if not isinstance(href, str) or not href.startswith("s3://usgs-landsat/"):
        raise GraphProviderError("USGS Landsat STAC asset is missing its official usgs-landsat S3 URI")
    if s3.get("storage:requester_pays") is not True:
        raise GraphProviderError("USGS Landsat STAC asset must declare requester-pays access")
    return href, True


def write_zarr(zarr_module: object, path: pathlib.Path, array: object) -> None:
    store = zarr_module.ZipStore(str(path), mode="w")
    try:
        group = zarr_module.group(store=store)
        height, width = array.shape[-2:]
        chunks = tuple([1] * (array.ndim - 2) + [min(256, height), min(256, width)])
        group.create_dataset("bands", data=array, chunks=chunks, overwrite=True)
        zarr_module.consolidate_metadata(store)
    finally:
        store.close()

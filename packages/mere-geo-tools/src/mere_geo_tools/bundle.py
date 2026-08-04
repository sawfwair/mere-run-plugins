from __future__ import annotations

import hashlib
import json
import pathlib

from mere_workflow_tools.graph_sdk import GraphProviderError, JsonMap, as_list, as_map

from .constants import MODEL_ID, MODEL_REVISION, S1_BANDS, S2_BANDS, TEMPORAL_ROLES

BUNDLE_KIND = "mere.geo/terramind-flood-input"
BUNDLE_VERSION = 1


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_bundle(root: pathlib.Path, verify_hashes: bool = True) -> JsonMap:
    manifest_path = root / "manifest.json"
    if not root.is_dir():
        raise GraphProviderError(f"input bundle is not a directory: {root}")
    if not manifest_path.is_file():
        raise GraphProviderError(f"input bundle manifest is missing: {manifest_path}")
    try:
        manifest = as_map(json.loads(manifest_path.read_text()), "input bundle manifest")
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"invalid input bundle manifest JSON: {exc}") from None
    validate_bundle(manifest, root, verify_hashes)
    return manifest


def validate_bundle(manifest: JsonMap, root: pathlib.Path, verify_hashes: bool = True) -> None:
    if manifest.get("kind") != BUNDLE_KIND or manifest.get("version") != BUNDLE_VERSION:
        raise GraphProviderError("unsupported TerraMind flood input bundle contract")
    model = as_map(manifest.get("model"), "input bundle model")
    if model.get("id") != MODEL_ID or model.get("revision") != MODEL_REVISION:
        raise GraphProviderError("input bundle is not pinned to the supported TerraMind flood checkpoint")
    grid = as_map(manifest.get("grid"), "input bundle grid")
    for field in ["crs", "transform", "width", "height", "resolution_m"]:
        if field not in grid:
            raise GraphProviderError(f"input bundle grid is missing {field}")
    if not isinstance(grid["width"], int) or not isinstance(grid["height"], int):
        raise GraphProviderError("input bundle grid dimensions must be integers")
    if grid["width"] < 256 or grid["height"] < 256:
        raise GraphProviderError("input bundle grid must be at least 256 by 256 pixels")

    timesteps = as_list(manifest.get("timesteps"), "input bundle timesteps")
    roles = [as_map(item, "input bundle timestep").get("role") for item in timesteps]
    if roles != TEMPORAL_ROLES:
        raise GraphProviderError(f"input bundle roles must be ordered as {TEMPORAL_ROLES}")

    modalities = as_map(manifest.get("modalities"), "input bundle modalities")
    s2 = as_map(modalities.get("S2L2A"), "S2L2A modality")
    s1 = as_map(modalities.get("S1RTC"), "S1RTC modality")
    dem = as_map(modalities.get("DEM"), "DEM modality")
    if s2.get("shape") != [4, 12, grid["height"], grid["width"]] or s2.get("bands") != S2_BANDS:
        raise GraphProviderError("S2L2A must be [4,12,H,W] in the canonical TerraMind band order")
    if s1.get("shape") != [4, 2, grid["height"], grid["width"]] or s1.get("bands") != S1_BANDS:
        raise GraphProviderError("S1RTC must be [4,2,H,W] ordered as VV,VH")
    if dem.get("shape") != [1, grid["height"], grid["width"]]:
        raise GraphProviderError("DEM must be [1,H,W] and is repeated by the runtime")

    artifacts = as_map(manifest.get("artifacts"), "input bundle artifacts")
    digest_entries: list[JsonMap] = []
    for name in ["S2L2A", "S1RTC", "DEM"]:
        artifact = as_map(artifacts.get(name), f"input artifact {name}")
        relative = artifact.get("path")
        expected_hash = artifact.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise GraphProviderError(f"input artifact {name} requires path and sha256")
        path = confined_bundle_path(root, relative)
        if not path.is_file():
            raise GraphProviderError(f"input artifact is missing: {path}")
        if verify_hashes and sha256_file(path) != expected_hash:
            raise GraphProviderError(f"input artifact hash mismatch: {name}")
        digest_entries.append({"name": name, "path": relative, "sha256": expected_hash})
    if manifest.get("input_digest") != canonical_digest(digest_entries):
        raise GraphProviderError("input bundle digest does not match its artifact inventory")


def confined_bundle_path(root: pathlib.Path, relative: str) -> pathlib.Path:
    raw = pathlib.PurePosixPath(relative)
    if raw.is_absolute() or not raw.parts or any(part in {"", ".", ".."} for part in raw.parts):
        raise GraphProviderError(f"input artifact path is not confined: {relative}")
    resolved_root = root.resolve()
    candidate = (resolved_root / pathlib.Path(*raw.parts)).resolve()
    if resolved_root not in candidate.parents:
        raise GraphProviderError(f"input artifact escapes its bundle: {relative}")
    return candidate

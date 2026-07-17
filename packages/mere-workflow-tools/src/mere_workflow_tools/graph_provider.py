from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import time
from typing import cast

from PIL import Image, ImageDraw, ImageOps

from .graph_sdk import (
    EVENT_CONTRACT_VERSION,
    INVOCATION_CONTRACT_VERSION,
    PREFLIGHT_CONTRACT_VERSION,
    PROVIDER_CONTRACT_VERSION,
    EventWriter,
    GraphEventStream,
    GraphProviderError,
    JsonMap,
    as_map,
    confined_path,
    diagnostic,
    relative_path,
    validate_catalog,
)
from .graph_sdk import (
    load_invocation as load_graph_invocation,
)

CONTRACT_VERSION = PROVIDER_CONTRACT_VERSION
INVOCATION_VERSION = INVOCATION_CONTRACT_VERSION
PREFLIGHT_VERSION = PREFLIGHT_CONTRACT_VERSION
EVENT_VERSION = EVENT_CONTRACT_VERSION
NODE_KIND = "dataset.prepare"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def graph_catalog(provider_id: str, provider_version: str) -> JsonMap:
    catalog: JsonMap = {
        "contract_version": CONTRACT_VERSION,
        "provider_id": provider_id,
        "provider_version": provider_version,
        "nodes": [
            {
                "kind": NODE_KIND,
                "title": "Prepare paired image dataset",
                "description": (
                    "Verify and materialize a deterministic image-caption dataset with a manifest, "
                    "optional contact sheet, and structured statistics."
                ),
                "category": "dataset",
                "inputs": [
                    {
                        "name": "data",
                        "type": "asset_directory",
                        "required": True,
                        "description": "Directory containing image files and same-stem UTF-8 caption files.",
                        "content_types": ["image/png", "image/jpeg", "image/webp", "text/plain"],
                    },
                    {
                        "name": "trigger_token",
                        "type": "string",
                        "required": False,
                        "description": "Exact token to prefix to every caption.",
                    },
                    {
                        "name": "contact_sheet",
                        "type": "boolean",
                        "required": False,
                        "description": "Create a JPEG contact sheet for dataset inspection.",
                        "default": True,
                    },
                    {
                        "name": "maximum_images",
                        "type": "integer",
                        "required": False,
                        "description": "Optional deterministic limit after filename sorting.",
                        "minimum": 1,
                        "maximum": 100000,
                        "step": 1,
                        "advanced": True,
                    },
                ],
                "outputs": [
                    {
                        "name": "dataset",
                        "type": "asset_directory",
                        "optional": False,
                        "description": "Verified image-caption pairs ready for training.",
                        "content_types": ["application/vnd.mere.dataset"],
                    },
                    {
                        "name": "manifest",
                        "type": "asset",
                        "optional": False,
                        "description": "Content-addressed dataset manifest.",
                        "content_types": ["application/json"],
                    },
                    {
                        "name": "contact_sheet",
                        "type": "asset",
                        "optional": True,
                        "description": "Optional visual index of prepared images.",
                        "content_types": ["image/jpeg"],
                    },
                    {
                        "name": "stats",
                        "type": "json",
                        "optional": False,
                        "description": "Pair count, byte count, and canonical dataset digest.",
                    },
                ],
                "requirements": {
                    "model_ids": [],
                    "accelerator_backends": ["cpu", "metal", "cuda", "rocm"],
                    "minimum_accelerator_memory_bytes": None,
                },
                "traits": {
                    "deterministic": True,
                    "cacheable": True,
                    "side_effects": "none",
                    "supports_progress": True,
                    "supports_previews": True,
                },
            }
        ],
    }
    validate_catalog(catalog)
    return catalog


def load_invocation(path: pathlib.Path) -> JsonMap:
    return load_graph_invocation(path, {NODE_KIND})


def graph_preflight(invocation: JsonMap, run_directory: pathlib.Path) -> JsonMap:
    diagnostics: list[JsonMap] = []
    arguments = as_map(invocation["arguments"], "arguments")
    source_value = arguments.get("data")
    if not isinstance(source_value, str) or not pathlib.Path(source_value).is_dir():
        diagnostics.append(
            diagnostic("dataset_missing", "blocker", "Dataset directory is missing", f"Not a directory: {source_value}")
        )
    else:
        source = pathlib.Path(source_value)
        try:
            images = dataset_images(source, arguments)
            missing = [image.name for image in images if not image.with_suffix(".txt").is_file()]
            if missing:
                diagnostics.append(
                    diagnostic(
                        "dataset_caption_missing",
                        "blocker",
                        "Dataset captions are missing",
                        f"Missing same-stem captions for: {', '.join(missing[:8])}",
                    )
                )
            if not images:
                diagnostics.append(
                    diagnostic("dataset_empty", "blocker", "Dataset has no images", f"No supported images in {source}")
                )
        except GraphProviderError as exc:
            diagnostics.append(diagnostic("dataset_invalid", "blocker", "Dataset is invalid", str(exc)))

    try:
        output_locations(invocation, run_directory)
    except GraphProviderError as exc:
        diagnostics.append(diagnostic("output_invalid", "blocker", "Output declaration is invalid", str(exc)))

    status = "blocked" if any(item["severity"] == "blocker" for item in diagnostics) else "ok"
    return {
        "contract_version": PREFLIGHT_VERSION,
        "status": status,
        "diagnostics": diagnostics,
        "requirements": {
            "model_ids": [],
            "accelerator_backends": ["cpu", "metal", "cuda", "rocm"],
            "minimum_accelerator_memory_bytes": None,
        },
    }


def graph_execute(invocation: JsonMap, run_directory: pathlib.Path, write_event: EventWriter) -> None:
    preflight = graph_preflight(invocation, run_directory)
    if preflight["status"] == "blocked":
        messages = [str(item["message"]) for item in cast(list[JsonMap], preflight["diagnostics"])]
        raise GraphProviderError(" ".join(messages))

    started = time.monotonic()
    events = GraphEventStream(write_event)
    arguments = as_map(invocation["arguments"], "arguments")
    source = pathlib.Path(cast(str, arguments["data"])).resolve()
    images = dataset_images(source, arguments)
    locations = output_locations(invocation, run_directory)
    dataset = locations["dataset"]
    manifest_path = locations["manifest"]
    contact_sheet_path = locations.get("contact_sheet")
    make_empty_directory(dataset)

    trigger_token = arguments.get("trigger_token")
    if trigger_token is not None and not isinstance(trigger_token, str):
        raise GraphProviderError("trigger_token must be a string")

    entries: list[JsonMap] = []
    total_bytes = 0
    for index, image in enumerate(images, start=1):
        caption = image.with_suffix(".txt")
        copied_image = dataset / image.name
        copied_caption = dataset / caption.name
        link_or_copy(image, copied_image)
        caption_text = caption.read_text().strip()
        if isinstance(trigger_token, str) and trigger_token.strip():
            token = trigger_token.strip()
            if not caption_text.lower().startswith(token.lower()):
                caption_text = f"{token}, {caption_text}"
        copied_caption.write_text(caption_text + "\n")
        image_size = copied_image.stat().st_size
        caption_size = copied_caption.stat().st_size
        total_bytes += image_size + caption_size
        entries.append(
            {
                "image": copied_image.name,
                "image_sha256": file_sha256(copied_image),
                "caption": copied_caption.name,
                "caption_sha256": file_sha256(copied_caption),
            }
        )
        events.emit(
            "progress",
            message=f"Prepared {image.name}",
            progress={
                "phase": "prepare",
                "current": index,
                "total": len(images),
                "fraction": index / len(images),
                "unit": "images",
            },
        )

    stats: JsonMap = {
        "pair_count": len(entries),
        "byte_count": total_bytes,
        "sha256": dataset_digest(entries),
    }
    manifest: JsonMap = {
        "contract_version": "mere.run/dataset-manifest.v1",
        "source": source.name,
        "entries": entries,
        "stats": stats,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    events.emit(
        "artifact_ready",
        artifact=artifact_value("dataset", dataset, run_directory, "application/vnd.mere.dataset"),
    )
    events.emit(
        "artifact_ready",
        artifact=artifact_value("manifest", manifest_path, run_directory, "application/json"),
    )

    contact_sheet_output: object = None
    if bool(arguments.get("contact_sheet", True)) and contact_sheet_path is not None:
        make_contact_sheet([dataset / image.name for image in images], contact_sheet_path)
        contact_sheet_output = relative_path(contact_sheet_path, run_directory)
        events.emit(
            "preview_ready",
            artifact=artifact_value("contact_sheet", contact_sheet_path, run_directory, "image/jpeg"),
        )

    events.emit(
        "metric",
        metric={"name": "duration", "value": time.monotonic() - started, "unit": "seconds"},
    )
    events.emit(
        "node_result",
        outputs={
            "dataset": relative_path(dataset, run_directory),
            "manifest": relative_path(manifest_path, run_directory),
            "contact_sheet": contact_sheet_output,
            "stats": stats,
        },
    )


def dataset_images(source: pathlib.Path, arguments: JsonMap) -> list[pathlib.Path]:
    images: list[pathlib.Path] = []
    for item in sorted(source.iterdir(), key=lambda path: path.name):
        if item.is_symlink():
            raise GraphProviderError(f"dataset contains a symlink: {item.name}")
        if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(item)
    maximum = arguments.get("maximum_images")
    if maximum is not None:
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
            raise GraphProviderError("maximum_images must be a positive integer")
        images = images[:maximum]
    return images


def output_locations(invocation: JsonMap, run_directory: pathlib.Path) -> dict[str, pathlib.Path]:
    outputs = as_map(invocation["outputs"], "outputs")
    expected = {
        "dataset": ("asset_directory", False),
        "manifest": ("asset", False),
        "contact_sheet": ("asset", True),
        "stats": ("json", False),
    }
    locations: dict[str, pathlib.Path] = {}
    for name, (expected_type, optional) in expected.items():
        descriptor = as_map(outputs.get(name), f"outputs.{name}")
        if descriptor.get("type") != expected_type:
            raise GraphProviderError(f"outputs.{name}.type must be {expected_type}")
        raw_path = descriptor.get("path")
        if raw_path is None:
            if expected_type == "json" or optional:
                continue
            raise GraphProviderError(f"outputs.{name}.path is required")
        if not isinstance(raw_path, str):
            raise GraphProviderError(f"outputs.{name}.path must be a string")
        locations[name] = confined_path(run_directory, raw_path)
    return locations


def make_empty_directory(path: pathlib.Path) -> None:
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise GraphProviderError(f"output directory is not empty: {path}")
    else:
        path.mkdir(parents=True)


def link_or_copy(source: pathlib.Path, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def dataset_digest(entries: list[JsonMap]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def make_contact_sheet(images: list[pathlib.Path], output: pathlib.Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tiles: list[Image.Image] = []
    for image_path in images[:64]:
        with Image.open(image_path) as opened:
            image = ImageOps.contain(opened.convert("RGB"), (160, 160), method=Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (180, 205), (245, 245, 245))
        tile.paste(image, ((180 - image.width) // 2, 8))
        ImageDraw.Draw(tile).text((8, 182), image_path.stem[:22], fill=(40, 40, 40))
        tiles.append(tile)
    columns = min(4, max(1, len(tiles)))
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 180, rows * 205), (255, 255, 255))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % columns) * 180, (index // columns) * 205))
    sheet.save(output, format="JPEG", quality=90)


def artifact_value(name: str, path: pathlib.Path, root: pathlib.Path, content_type: str) -> JsonMap:
    return {"name": name, "path": relative_path(path, root), "content_type": content_type}

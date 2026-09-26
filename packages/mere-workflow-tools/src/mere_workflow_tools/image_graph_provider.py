"""Deterministic image finishing nodes exposed through the public graph provider API."""

from __future__ import annotations

import pathlib
import time
from collections import deque
from typing import cast

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

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
KINDS = {"image.crop", "image.mask", "image.composite", "image.inpaint"}
MAX_PIXELS = 16_000_000


def _field(name: str, kind: str, description: str, *, required: bool = True, **extra: object) -> JsonMap:
    return {"name": name, "type": kind, "required": required, "description": description, **extra}


def _node(kind: str, title: str, description: str, inputs: list[JsonMap]) -> JsonMap:
    return {
        "kind": kind, "title": title, "description": description, "category": "image",
        "inputs": inputs,
        "outputs": [{"name": "image", "type": "asset", "description": "Finished PNG image",
                     "optional": False, "content_types": ["image/png"]}],
        "requirements": {"model_ids": [], "accelerator_backends": ["cpu", "metal", "cuda", "rocm"],
                         "minimum_accelerator_memory_bytes": None},
        "traits": {"deterministic": True, "cacheable": True, "side_effects": "none",
                   "supports_progress": False, "supports_previews": False},
    }


def graph_catalog(provider_id: str, provider_version: str) -> JsonMap:
    catalog: JsonMap = {
        "contract_version": CONTRACT_VERSION,
        "provider_id": provider_id,
        "provider_version": provider_version,
        "nodes": [
            _node("image.crop", "Crop image", "Crop an image to an exact pixel rectangle.", [
                _field("source", "asset", "Source image", content_types=["image/png", "image/jpeg", "image/webp"]),
                _field("left", "integer", "Left pixel coordinate", minimum=0),
                _field("top", "integer", "Top pixel coordinate", minimum=0),
                _field("width", "integer", "Crop width in pixels", minimum=1),
                _field("height", "integer", "Crop height in pixels", minimum=1),
            ]),
            _node("image.mask", "Apply mask", "Use a grayscale mask as image transparency.", [
                _field("source", "asset", "Source image", content_types=["image/png", "image/jpeg", "image/webp"]),
                _field("mask", "asset", "White areas remain visible; black areas become transparent", content_types=["image/png"]),
                _field("invert", "boolean", "Invert the mask", required=False, default=False),
            ]),
            _node("image.composite", "Composite images", "Place a transparent layer over a base image.", [
                _field("base", "asset", "Base image", content_types=["image/png", "image/jpeg", "image/webp"]),
                _field("overlay", "asset", "Overlay image", content_types=["image/png", "image/webp"]),
                _field("left", "integer", "Left pixel coordinate", required=False, default=0),
                _field("top", "integer", "Top pixel coordinate", required=False, default=0),
                _field("opacity", "number", "Overlay opacity from 0 to 1", required=False,
                       minimum=0, maximum=1, default=1),
            ]),
            _node("image.inpaint", "Inpaint masked area", "Fill a small masked area from neighboring pixels without a model.", [
                _field("source", "asset", "Source image", content_types=["image/png", "image/jpeg", "image/webp"]),
                _field("mask", "asset", "White areas are replaced; black areas are preserved", content_types=["image/png"]),
            ]),
        ],
    }
    validate_catalog(catalog)
    return catalog


def load_invocation(path: pathlib.Path) -> JsonMap:
    return load_graph_invocation(path, KINDS)


def _integer(arguments: JsonMap, name: str, default: int | None = None) -> int:
    value = arguments.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise GraphProviderError(f"{name} must be an integer")
    return value


def _source(arguments: JsonMap, name: str) -> pathlib.Path:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise GraphProviderError(f"{name} must be an image path")
    path = pathlib.Path(value)
    if not path.is_file():
        raise GraphProviderError(f"{name} image is unavailable")
    return path


def _output(invocation: JsonMap, root: pathlib.Path) -> pathlib.Path:
    descriptor = as_map(as_map(invocation["outputs"], "outputs").get("image"), "outputs.image")
    if descriptor.get("type") != "asset" or not isinstance(descriptor.get("path"), str):
        raise GraphProviderError("outputs.image must declare an asset path")
    return confined_path(root, cast(str, descriptor["path"]))


def _validate_arguments(kind: str, arguments: JsonMap) -> None:
    if kind == "image.crop":
        _source(arguments, "source")
        for name in ("left", "top", "width", "height"):
            value = _integer(arguments, name)
            if value < (1 if name in {"width", "height"} else 0):
                raise GraphProviderError(f"{name} is outside the crop range")
    elif kind in {"image.mask", "image.inpaint"}:
        _source(arguments, "source")
        _source(arguments, "mask")
        if kind == "image.mask" and not isinstance(arguments.get("invert", False), bool):
            raise GraphProviderError("invert must be a boolean")
    elif kind == "image.composite":
        _source(arguments, "base")
        _source(arguments, "overlay")
        _integer(arguments, "left", 0)
        _integer(arguments, "top", 0)
        opacity = arguments.get("opacity", 1)
        if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not 0 <= opacity <= 1:
            raise GraphProviderError("opacity must be between 0 and 1")
    else:
        raise GraphProviderError(f"unsupported image operation: {kind}")


def graph_preflight(invocation: JsonMap, run_directory: pathlib.Path) -> JsonMap:
    diagnostics: list[JsonMap] = []
    try:
        _validate_arguments(cast(str, invocation["kind"]), as_map(invocation["arguments"], "arguments"))
        _output(invocation, run_directory)
    except GraphProviderError as exc:
        diagnostics.append(diagnostic("image_edit_invalid", "blocker", "Image edit is invalid", str(exc)))
    return {"contract_version": PREFLIGHT_VERSION,
            "status": "blocked" if diagnostics else "ok", "diagnostics": diagnostics,
            "requirements": {"model_ids": [], "accelerator_backends": ["cpu", "metal", "cuda", "rocm"],
                             "minimum_accelerator_memory_bytes": None}}


def _open_image(path: pathlib.Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            if source.width * source.height > MAX_PIXELS:
                raise GraphProviderError("image exceeds the 16 megapixel finishing limit")
            converted = source.convert("RGBA")
            if not isinstance(converted, Image.Image):
                raise GraphProviderError("image conversion did not return an image")
            return converted
    except (OSError, UnidentifiedImageError) as exc:
        raise GraphProviderError(f"could not read image: {path.name}") from exc


def _mask_image(path: pathlib.Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as source:
        if source.size != size:
            raise GraphProviderError("mask dimensions must match the source image")
        converted = source.convert("L")
        if not isinstance(converted, Image.Image):
            raise GraphProviderError("mask conversion did not return an image")
        return converted


def _inpaint(source: Image.Image, mask: Image.Image) -> Image.Image:
    """Fill a bounded defect using nearest known neighbors; preserves untouched pixels."""
    width, height = source.size
    if width * height > 4_000_000:
        raise GraphProviderError("inpainting is limited to 4 megapixels")
    image = source.convert("RGB")
    pixels = image.load()
    masks = mask.load()
    assert pixels is not None and masks is not None
    missing = {(x, y) for y in range(height) for x in range(width) if cast(int, masks[x, y]) >= 128}
    if len(missing) > width * height // 4:
        raise GraphProviderError("inpainting mask covers more than 25% of the image")
    if not missing:
        return source.copy()
    frontier: deque[tuple[int, int]] = deque()
    queued: set[tuple[int, int]] = set()
    neighbors = ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1))
    for x, y in missing:
        if any((x + dx, y + dy) not in missing and 0 <= x + dx < width and 0 <= y + dy < height
               for dx, dy in neighbors):
            frontier.append((x, y))
            queued.add((x, y))
    if not frontier:
        raise GraphProviderError("inpainting mask has no known boundary pixels")
    while frontier:
        x, y = frontier.popleft()
        samples = [pixels[x + dx, y + dy] for dx, dy in neighbors
                   if 0 <= x + dx < width and 0 <= y + dy < height and (x + dx, y + dy) not in missing]
        if not samples:
            continue
        pixels[x, y] = tuple(sum(channel) // len(samples) for channel in zip(*samples))
        missing.remove((x, y))
        for dx, dy in neighbors:
            candidate = (x + dx, y + dy)
            if candidate in missing and candidate not in queued:
                frontier.append(candidate)
                queued.add(candidate)
    if missing:
        raise GraphProviderError("inpainting could not fill the complete mask")
    binary_mask = mask.point(lambda value: 255 if value >= 128 else 0)
    return Image.composite(image.convert("RGBA"), source, binary_mask)


def _render(kind: str, arguments: JsonMap) -> Image.Image:
    if kind == "image.composite":
        base = _open_image(_source(arguments, "base"))
        overlay = _open_image(_source(arguments, "overlay"))
        opacity = float(cast(float, arguments.get("opacity", 1)))
        overlay.putalpha(overlay.getchannel("A").point(lambda value: round(value * opacity)))
        layer = Image.new("RGBA", base.size)
        layer.paste(overlay, (_integer(arguments, "left", 0), _integer(arguments, "top", 0)))
        return Image.alpha_composite(base, layer)
    source = _open_image(_source(arguments, "source"))
    if kind == "image.crop":
        left, top = _integer(arguments, "left"), _integer(arguments, "top")
        width, height = _integer(arguments, "width"), _integer(arguments, "height")
        if left + width > source.width or top + height > source.height:
            raise GraphProviderError("crop rectangle exceeds source image bounds")
        return source.crop((left, top, left + width, top + height))
    mask = _mask_image(_source(arguments, "mask"), source.size)
    if kind == "image.inpaint":
        return _inpaint(source, mask)
    if arguments.get("invert", False):
        mask = ImageOps.invert(mask)
    source.putalpha(ImageChops.multiply(source.getchannel("A"), mask))
    return source


def graph_execute(invocation: JsonMap, run_directory: pathlib.Path, write_event: EventWriter) -> None:
    preflight = graph_preflight(invocation, run_directory)
    if preflight["status"] == "blocked":
        raise GraphProviderError(" ".join(str(item["message"]) for item in cast(list[JsonMap], preflight["diagnostics"])))
    started = time.monotonic()
    kind = cast(str, invocation["kind"])
    arguments = as_map(invocation["arguments"], "arguments")
    target = _output(invocation, run_directory)
    image = _render(kind, arguments)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")
    events = GraphEventStream(write_event)
    events.emit("artifact_ready", artifact={"name": "image", "path": relative_path(target, run_directory),
                                            "content_type": "image/png"})
    events.emit("metric", metric={"name": "duration", "value": time.monotonic() - started, "unit": "seconds"})
    events.emit("node_result", outputs={"image": relative_path(target, run_directory)})

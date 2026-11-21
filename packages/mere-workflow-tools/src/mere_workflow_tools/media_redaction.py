"""Review and burn opaque redactions into still images or ordered frames."""

from __future__ import annotations

import hashlib
import io
import json
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict

from PIL import Image, ImageDraw, ImageOps

REVIEW_SCHEMA = "mere.run/media-redaction-review.v1"
EXPORT_SCHEMA = "mere.run/media-redaction-export.v1"
MAX_IMAGE_BYTES = 128 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_EDGE = 12_000



class FrameIdentity(TypedDict):
    name: str
    width: int
    height: int
    sha256: str


def read_frame(path: Path) -> tuple[Image.Image, FrameIdentity]:
    with path.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds 128 MiB: {path.name}")
    with Image.open(io.BytesIO(data)) as original:
        if getattr(original, "n_frames", 1) != 1:
            raise ValueError(f"Use a folder of single-frame images: {path.name}")
        if original.width * original.height > MAX_PIXELS or max(original.size) > MAX_EDGE:
            raise ValueError(f"Image exceeds 40 megapixels or 12,000 pixels per side: {path.name}")
        oriented = ImageOps.exif_transpose(original).convert("RGBA")
    flattened = Image.new("RGB", oriented.size, "white")
    flattened.paste(oriented, mask=oriented.getchannel("A"))
    return flattened, {
        "name": path.name,
        "width": flattened.width,
        "height": flattened.height,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def prepare_output(inputs: list[Path], source_root: Path, output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError(f"Output directory already exists: {output}")
    if source_root.is_dir() and output.is_relative_to(source_root):
        raise ValueError("Choose an output directory outside the source folder.")
    for path in inputs:
        if not path.resolve().is_relative_to(source_root if source_root.is_dir() else source_root.parent):
            raise ValueError(f"Image points outside the source folder: {path.name}")
    output.parent.mkdir(parents=True, exist_ok=True)


def publish(staging: Path, output: Path) -> None:
    # Start with an exclusively reserved destination. Renaming over the empty
    # directory exposes only a complete result, even when two exports race.
    output.mkdir(mode=0o700)
    try:
        staging.replace(output)
    except OSError:
        output.rmdir()
        raise


def create_review(inputs: list[Path], source_root: Path, output: Path) -> dict[str, object]:
    prepare_output(inputs, source_root, output)
    with TemporaryDirectory(dir=output.parent, prefix=".redaction-review-") as temporary:
        staging = Path(temporary)
        previews = staging / "previews"
        previews.mkdir()
        frames = []
        for index, path in enumerate(inputs, 1):
            image, identity = read_frame(path)
            preview = f"previews/{index:06}.png"
            image.save(staging / preview)
            frames.append({**identity, "preview": preview})
        data = json.dumps({"schema": REVIEW_SCHEMA, "frames": frames}, ensure_ascii=True)
        template = files("mere_workflow_tools").joinpath("templates").joinpath("redaction-review.html").read_text(encoding="utf-8")
        (staging / "review.html").write_text(
            template.replace("__REVIEW_DATA__", data.replace("<", r"\u003c")), encoding="utf-8"
        )
        publish(staging, output)
    return {"reviewPage": str(output / "review.html"), "frameCount": len(frames)}


def approved_rectangles(frame: object, identity: FrameIdentity) -> list[list[int]]:
    if not isinstance(frame, dict) or any(frame.get(key) != value for key, value in identity.items()):
        raise ValueError(f"Source image changed or review order differs: {identity['name']}")
    if frame.get("approved") is not True:
        raise ValueError(f"Image has not been approved: {identity['name']}")
    rectangles = frame.get("rectangles")
    if not isinstance(rectangles, list):
        raise ValueError(f"Invalid rectangle list: {identity['name']}")
    for rectangle in rectangles:
        if not isinstance(rectangle, list) or len(rectangle) != 4 or any(type(value) is not int for value in rectangle):
            raise ValueError(f"Rectangle requires four integer coordinates: {identity['name']}")
        x0, y0, x1, y1 = rectangle
        if not (0 <= x0 < x1 <= identity["width"] and 0 <= y0 < y1 <= identity["height"]):
            raise ValueError(f"Rectangle is outside the image or empty: {identity['name']}")
    return [list(rectangle) for rectangle in rectangles]


def export_review(inputs: list[Path], source_root: Path, review_path: Path, output: Path) -> dict[str, object]:
    prepare_output(inputs, source_root, output)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(review, dict) or review.get("schema") != REVIEW_SCHEMA:
        raise ValueError("Unsupported redaction review schema.")
    frames = review.get("frames")
    if not isinstance(frames, list) or len(frames) != len(inputs):
        raise ValueError("Review must cover every image in the source, in order.")
    with TemporaryDirectory(dir=output.parent, prefix=".redaction-export-") as temporary:
        staging = Path(temporary)
        exported = []
        for index, (path, frame) in enumerate(zip(inputs, frames), 1):
            image, identity = read_frame(path)
            rectangles = approved_rectangles(frame, identity)
            draw = ImageDraw.Draw(image)
            for x0, y0, x1, y1 in rectangles:
                draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill="black")
            filename = f"{index:06}.png"
            destination = staging / filename
            image.save(destination)
            exported.append({
                "source": identity,
                "rectangles": rectangles,
                "output": filename,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            })
        (staging / "export.json").write_text(
            json.dumps({"schema": EXPORT_SCHEMA, "frames": exported}, indent=2) + "\n",
            encoding="utf-8",
        )
        publish(staging, output)
    return {"exportManifest": str(output / "export.json"), "frameCount": len(exported)}

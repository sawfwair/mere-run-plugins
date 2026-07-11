from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, cast

import PIL
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat

from . import __version__

JsonMap = dict[str, object]
JsonList = list[object]
PLUGIN_NAME = "mere-vfx-tools"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    capabilities: tuple[str, ...]


TOOLS: dict[str, ToolSpec] = {
    "roto": ToolSpec("roto", "Smart Roto", "Track subjects and deliver refined shot mattes.", ("roto", "tracking", "alpha-matte")),
    "matte-refine": ToolSpec("matte-refine", "Matte Refine", "Normalize, grow, choke, and feather mattes.", ("matte-refine", "alpha-matte")),
    "track-export": ToolSpec("track-export", "Track Export", "Export tracking metadata for compositing and 3D tools.", ("track-export", "nuke", "after-effects", "blender")),
    "key": ToolSpec("key", "Chroma Key", "Key and despill a still or image sequence.", ("keying", "despill", "alpha-matte")),
    "shot-qc": ToolSpec("shot-qc", "Shot QC", "Detect corrupt frames, luma jumps, and matte chatter.", ("shot-qc", "quality-control")),
    "inbetween": ToolSpec("inbetween", "Generative In-between", "Generate motion between explicit keyframes.", ("inbetween", "video-generation")),
    "turntable": ToolSpec("turntable", "Turntable", "Generate an image-anchored orbit and contact sheet.", ("turntable", "video-generation", "contact-sheet")),
    "character-sheet": ToolSpec("character-sheet", "Character Sheet", "Generate canonical character reference views.", ("character-sheet", "image-generation", "continuity")),
    "pose-sequence": ToolSpec(
        "pose-sequence",
        "Pose Sequence",
        "Extract body, hand, and face landmarks across a shot for motion handoff.",
        ("pose-sequence", "markerless-motion", "body-pose", "hand-pose", "face-landmarks", "after-effects", "blender"),
    ),
    "motion-pass": ToolSpec(
        "motion-pass",
        "Motion Pass",
        "Generate native dense optical-flow passes for adjacent shot frames.",
        ("motion-pass", "optical-flow", "middlebury-flo", "nuke", "blender"),
    ),
    "clean-plate": ToolSpec(
        "clean-plate",
        "Clean Plate",
        "Remove masked subjects while preserving pixels outside the supplied matte.",
        ("clean-plate", "object-removal", "masked-edit", "image-generation"),
    ),
    "set-extension": ToolSpec(
        "set-extension",
        "Set Extension",
        "Extend a plate while preserving the supplied source region.",
        ("set-extension", "outpainting", "image-generation", "plate-preservation"),
    ),
    "restore": ToolSpec(
        "restore",
        "Restore and Upscale",
        "Restore detail and upscale stills or image sequences.",
        ("restoration", "super-resolution", "image-generation"),
    ),
    "depth-normal": ToolSpec(
        "depth-normal",
        "Depth and Normal Passes",
        "Generate non-metric depth proxies and deterministic image-space normal maps.",
        ("depth-pass", "normal-pass", "image-generation", "blender", "nuke"),
    ),
    "relight": ToolSpec(
        "relight",
        "Relight and Shadow Catcher",
        "Relight frames from image-space normals and project matte-based shadow layers.",
        ("relighting", "shadow-catcher", "normal-pass", "alpha-matte"),
    ),
    "image-to-3d": ToolSpec(
        "image-to-3d",
        "Image/Video to 3D",
        "Project depth passes into camera-space PLY point clouds and OBJ surface meshes.",
        ("image-to-3d", "video-to-3d", "point-cloud", "mesh", "blender"),
    ),
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def eprint(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def print_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_json(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def as_map(value: object, context: str) -> JsonMap:
    if not isinstance(value, dict):
        raise PluginError(f"{context} must be a JSON object", 2)
    return cast(JsonMap, value)


def as_list(value: object, context: str) -> JsonList:
    if not isinstance(value, list):
        raise PluginError(f"{context} must be a JSON array", 2)
    return cast(JsonList, value)


def split_command(value: str, label: str) -> list[str]:
    try:
        command = shlex.split(value)
    except ValueError as exc:
        raise PluginError(f"invalid {label}: {exc}", 2) from None
    if not command:
        raise PluginError(f"{label} is empty", 2)
    return command


def command_available(command: list[str]) -> bool:
    return pathlib.Path(command[0]).expanduser().is_file() or shutil.which(command[0]) is not None


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def option_string(options: JsonMap, key: str, default: str = "") -> str:
    value = options.get(key, default)
    return value if isinstance(value, str) else default


def option_float(options: JsonMap, key: str, default: float) -> float:
    value = options.get(key, default)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def option_int(options: JsonMap, key: str, default: int) -> int:
    value = options.get(key, default)
    return int(value) if isinstance(value, (int, float)) else default


def option_bool(options: JsonMap, key: str, default: bool) -> bool:
    value = options.get(key, default)
    return value if isinstance(value, bool) else default


def option_vector(options: JsonMap, key: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
    value = options.get(key)
    if isinstance(value, list) and len(value) >= 3 and all(isinstance(item, (int, float)) for item in value[:3]):
        return float(value[0]), float(value[1]), float(value[2])
    return default


def load_request(path: pathlib.Path) -> JsonMap:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginError(f"could not read request JSON {path}: {exc}", 2) from None
    request = as_map(payload, "request")
    if "inputs" not in request:
        request["inputs"] = {}
    if "options" not in request:
        request["options"] = {}
    as_map(request["inputs"], "request.inputs")
    as_map(request["options"], "request.options")
    return request


def input_path(request: JsonMap, key: str) -> pathlib.Path:
    inputs = as_map(request["inputs"], "request.inputs")
    value = inputs.get(key)
    if not isinstance(value, str) or not value:
        raise PluginError(f"request.inputs.{key} must be a local path", 2)
    path = pathlib.Path(value).expanduser().resolve()
    if not path.exists():
        raise PluginError(f"request input does not exist: {path}", 2)
    return path


def plugin_manifest() -> JsonMap:
    workflow_commands = [
        {"name": spec.name, "description": spec.description, "stdout": "json"}
        for spec in TOOLS.values()
    ]
    capabilities = sorted({"vfx", "local-runner", *(cap for spec in TOOLS.values() for cap in spec.capabilities)})
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": PLUGIN_NAME,
        "description": "Local shot-oriented VFX workflows powered by native mere.run inference.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-vfx-tools",
        "commands": [
            {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
            {"name": "doctor", "description": "Check native runtime and media-tool readiness.", "stdout": "json"},
            {"name": "plan", "description": "Write a durable VFX run manifest.", "stdout": "json"},
            {"name": "run", "description": "Execute a planned VFX run.", "stdout": "json"},
            {"name": "resume", "description": "Inspect or resume a VFX run.", "stdout": "json"},
            {"name": "cleanup", "description": "Record local cleanup state.", "stdout": "json"},
            *workflow_commands,
        ],
        "capabilities": capabilities,
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": False,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def default_run_id(tool: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"vfx-{tool}-{stamp}"


def make_manifest(args: argparse.Namespace) -> JsonMap:
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise PluginError("invalid --run-id", 2)
    request = load_request(args.request_json)
    created = now_iso()
    command = [
        PLUGIN_NAME,
        args.tool,
        "--request-json",
        str(args.request_json),
        "--output-dir",
        str(args.output_dir),
        "--run-id",
        args.run_id,
        "--mere-run-command",
        args.mere_run_command,
        "--ffmpeg-command",
        args.ffmpeg_command,
    ]
    return {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {"id": f"vfx-{args.tool}", "family": "vfx-workflow", "title": TOOLS[args.tool].title},
        "status": "planned",
        "createdAt": created,
        "updatedAt": created,
        "dataset": {"path": str(args.request_json), "pairCount": 1, "sha256": sha256(args.request_json)},
        "command": command,
        "local": {"outputDirectory": str(args.output_dir), "runManifest": str(args.output_dir / "run.json")},
        "tool": {"name": args.tool, "backend": "mere.run", "capabilities": list(TOOLS[args.tool].capabilities)},
        "runtime": {
            "mereRunCommand": split_command(args.mere_run_command, "mere.run command"),
            "ffmpegCommand": split_command(args.ffmpeg_command, "ffmpeg command"),
        },
        "request": request,
        "artifacts": {"localDirectory": str(args.output_dir), "items": []},
        "cleanup": {"default": "none", "status": "not-started"},
    }


def update_manifest(path: pathlib.Path, manifest: JsonMap, status: str | None = None) -> None:
    if status is not None:
        manifest["status"] = status
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def artifact(manifest: JsonMap, path: pathlib.Path, kind: str, label: str) -> None:
    if not path.exists():
        raise PluginError(f"expected artifact was not written: {path}")
    artifacts = as_map(manifest["artifacts"], "artifacts")
    items = as_list(artifacts["items"], "artifacts.items")
    item: JsonMap = {"name": path.name, "path": str(path), "kind": kind, "label": label}
    if path.is_file():
        item["sha256"] = sha256(path)
    items.append(item)


def runtime_command(manifest: JsonMap, key: str) -> list[str]:
    runtime = as_map(manifest["runtime"], "runtime")
    command = runtime.get(key)
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise PluginError(f"runtime.{key} must be a string array")
    return list(cast(list[str], command))


def run_process(argv: list[str], label: str) -> None:
    if not command_available(argv):
        raise PluginError(f"{label} command not found: {argv[0]}", 3)
    eprint("$ " + shlex.join(argv))
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        eprint(line.rstrip())
    return_code = process.wait()
    if return_code != 0:
        raise PluginError(f"{label} failed with exit {return_code}")


def refine_mask(image: Image.Image, grow: int, choke: int, feather: float) -> Image.Image:
    matte = ImageOps.grayscale(image.convert("RGB")) if image.mode not in {"L", "LA", "RGBA"} else image.getchannel("A") if image.mode in {"LA", "RGBA"} else image
    matte = matte.convert("L")
    if grow > 0:
        matte = matte.filter(ImageFilter.MaxFilter(grow * 2 + 1))
    if choke > 0:
        matte = matte.filter(ImageFilter.MinFilter(choke * 2 + 1))
    if feather > 0:
        matte = matte.filter(ImageFilter.GaussianBlur(feather))
    return matte


def image_files(path: pathlib.Path) -> list[pathlib.Path]:
    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
        return [path]
    if path.is_dir():
        return sorted(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS)
    raise PluginError(f"no supported image input at {path}", 2)


def options_for(manifest: JsonMap) -> JsonMap:
    request = as_map(manifest["request"], "request")
    return as_map(request["options"], "request.options")


def combine_raw_mattes(raw_dir: pathlib.Path, output_dir: pathlib.Path, options: JsonMap) -> list[pathlib.Path]:
    paths = image_files(raw_dir)
    grouped: dict[str, list[pathlib.Path]] = {}
    for path in paths:
        relative_parent = path.parent.relative_to(raw_dir)
        key = str(relative_parent) if str(relative_parent) != "." else path.stem
        grouped.setdefault(key, []).append(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[pathlib.Path] = []
    for index, group in enumerate(sorted(grouped.values(), key=lambda values: str(values[0]))):
        combined = Image.new("L", Image.open(group[0]).size, 0)
        for source in group:
            mask = refine_mask(Image.open(source), 0, 0, 0)
            if mask.size != combined.size:
                mask = mask.resize(combined.size)
            combined = ImageChops.lighter(combined, mask)
        combined = refine_mask(
            combined,
            option_int(options, "growPixels", 0),
            option_int(options, "chokePixels", 0),
            option_float(options, "featherRadius", 1.0),
        )
        destination = output_dir / f"frame_{index + 1:06d}.png"
        combined.save(destination)
        outputs.append(destination)
    return outputs


def extract_video_frames(manifest: JsonMap, video: pathlib.Path, directory: pathlib.Path) -> list[pathlib.Path]:
    directory.mkdir(parents=True, exist_ok=True)
    argv = runtime_command(manifest, "ffmpegCommand") + [
        "-y", "-i", str(video), "-fps_mode", "passthrough", str(directory / "frame_%06d.png"),
    ]
    run_process(argv, "ffmpeg frame extraction")
    return sorted(directory.glob("frame_*.png"))


def encode_alpha_movie(manifest: JsonMap, frames_dir: pathlib.Path, fps: float, output: pathlib.Path) -> None:
    argv = runtime_command(manifest, "ffmpegCommand") + [
        "-y", "-framerate", str(fps), "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", str(output),
    ]
    run_process(argv, "ffmpeg alpha encode")


def execute_roto(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    options = options_for(manifest)
    video = input_path(request, "video")
    raw_dir = output_dir / "raw-mattes"
    mattes = output_dir / "mattes"
    review = output_dir / "roto-review.mp4"
    tracking = output_dir / "tracking.json"
    argv = runtime_command(manifest, "mereRunCommand") + [
        "vision", "track", str(video), "--model", option_string(options, "model", "vision-segment-sam31"),
        "--output", str(review), "--json-output", str(tracking), "--mask-output-dir", str(raw_dir),
        "--init-frame", str(option_int(options, "initFrame", 0)),
    ]
    prompts = string_list(options.get("prompts")) or [option_string(options, "prompt", "subject")]
    for prompt in prompts:
        argv.extend(["--prompt", prompt])
    for box in string_list(options.get("boxes")):
        argv.extend(["--box", box])
    for point in string_list(options.get("points")):
        argv.extend(["--point", point])
    run_process(argv, "mere.run vision track")
    matte_files = combine_raw_mattes(raw_dir, mattes, options)
    if not matte_files:
        raise PluginError("tracking produced no matte frames")
    artifact(manifest, review, "video", "roto-review")
    artifact(manifest, tracking, "json", "tracking-data")
    artifact(manifest, mattes, "directory", "matte-sequence")
    if option_bool(options, "alphaVideo", True):
        source_frames = extract_video_frames(manifest, video, output_dir / "source-frames")
        tracking_payload = as_map(json.loads(tracking.read_text()), "tracking JSON")
        raw_frames = tracking_frames(tracking_payload)
        indices: list[int] = []
        for position, raw_frame in enumerate(raw_frames):
            if not isinstance(raw_frame, dict):
                continue
            frame_index = cast(JsonMap, raw_frame).get("frameIndex", position)
            indices.append(int(frame_index) if isinstance(frame_index, (int, float)) else position)
        selected_frames = [source_frames[index] for index in indices if 0 <= index < len(source_frames)]
        if len(selected_frames) != len(matte_files):
            raise PluginError(
                f"could not align {len(matte_files)} tracked mattes to {len(source_frames)} source frames "
                f"using tracker indices {indices}"
            )
        manifest["vfx"] = {
            "sourceFrameCount": len(source_frames),
            "trackedFrameCount": len(matte_files),
            "alphaFrameIndices": indices,
        }
        rgba_dir = output_dir / "rgba-frames"
        rgba_dir.mkdir(parents=True, exist_ok=True)
        for index, (source, matte) in enumerate(zip(selected_frames, matte_files)):
            frame = Image.open(source).convert("RGBA")
            alpha = Image.open(matte).convert("L")
            if alpha.size != frame.size:
                alpha = alpha.resize(frame.size)
            frame.putalpha(alpha)
            frame.save(rgba_dir / f"frame_{index + 1:06d}.png")
        alpha_movie = output_dir / "roto-alpha.mov"
        native_fps = tracking_payload.get("fps")
        fps = float(native_fps) if isinstance(native_fps, (int, float)) else option_float(options, "fps", 24.0)
        encode_alpha_movie(manifest, rgba_dir, fps, alpha_movie)
        artifact(manifest, alpha_movie, "video", "alpha-video")


def execute_matte_refine(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    source = input_path(request, "masks")
    destination = output_dir / "refined-mattes"
    destination.mkdir(parents=True, exist_ok=True)
    options = options_for(manifest)
    for index, path in enumerate(image_files(source)):
        result = refine_mask(
            Image.open(path),
            option_int(options, "growPixels", 0),
            option_int(options, "chokePixels", 0),
            option_float(options, "featherRadius", 1.0),
        )
        result.save(destination / f"frame_{index + 1:06d}.png")
    artifact(manifest, destination, "directory", "refined-mattes")


def tracking_frames(payload: JsonMap) -> JsonList:
    for key in ("frames", "frameDetections", "detectionsByFrame"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def execute_track_export(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    source = input_path(request, "trackingJson")
    payload = as_map(json.loads(source.read_text()), "tracking JSON")
    frames = tracking_frames(payload)
    normalized: list[JsonMap] = []
    csv_rows: list[list[object]] = []
    for frame_index, raw_frame in enumerate(frames):
        frame = as_map(raw_frame, f"tracking frame {frame_index}")
        detections_value = frame.get("detections", frame.get("objects", []))
        detections = detections_value if isinstance(detections_value, list) else []
        normalized_frame: JsonMap = {"frame": frame.get("frame", frame.get("frameIndex", frame_index)), "objects": []}
        objects = as_list(normalized_frame["objects"], "normalized objects")
        for raw_detection in detections:
            if not isinstance(raw_detection, dict):
                continue
            detection = cast(JsonMap, raw_detection)
            box_value = detection.get("box", [0, 0, 0, 0])
            box = box_value if isinstance(box_value, list) and len(box_value) >= 4 else [0, 0, 0, 0]
            item: JsonMap = {
                "objectID": detection.get("objectID", detection.get("id", "object")),
                "label": detection.get("label", "object"),
                "visible": detection.get("visible", True),
                "box": box[:4],
                "maskPath": detection.get("maskPath"),
            }
            objects.append(item)
            csv_rows.append([normalized_frame["frame"], item["objectID"], item["label"], *box[:4], item["visible"]])
        normalized.append(normalized_frame)
    generic = output_dir / "tracks.json"
    ae = output_dir / "tracks-after-effects.json"
    blender = output_dir / "tracks-blender.json"
    csv_path = output_dir / "tracks.csv"
    write_json(generic, {"schemaVersion": "mere.run/vfx-tracks.v1", "source": str(source), "frames": normalized})
    write_json(ae, {"format": "after-effects", "fps": payload.get("fps", 24), "frames": normalized})
    write_json(blender, {"format": "blender", "fps": payload.get("fps", 24), "tracks": normalized})
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "object_id", "label", "x", "y", "width", "height", "visible"])
        writer.writerows(csv_rows)
    for path, label in ((generic, "generic-tracks"), (ae, "after-effects-tracks"), (blender, "blender-tracks"), (csv_path, "track-table")):
        artifact(manifest, path, "json" if path.suffix == ".json" else "csv", label)


def key_image(source: pathlib.Path, destination: pathlib.Path, options: JsonMap) -> None:
    color_value = options.get("keyColor", [0, 255, 0])
    color = color_value if isinstance(color_value, list) and len(color_value) >= 3 else [0, 255, 0]
    key_rgb = tuple(int(max(0, min(255, float(component)))) for component in color[:3])
    threshold = max(0.0, option_float(options, "threshold", 55.0))
    softness = max(1.0, option_float(options, "softness", 45.0))
    despill = max(0.0, min(1.0, option_float(options, "despill", 0.65)))
    image = Image.open(source).convert("RGBA")
    pixels = image.load()
    if pixels is None:
        raise PluginError(f"could not read image pixels: {source}")
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, _alpha = cast(tuple[int, int, int, int], pixels[x, y])
            distance = math.sqrt((red - key_rgb[0]) ** 2 + (green - key_rgb[1]) ** 2 + (blue - key_rgb[2]) ** 2)
            alpha = int(max(0.0, min(1.0, (distance - threshold) / softness)) * 255)
            spill = max(0, green - max(red, blue))
            green = int(max(0, green - spill * despill))
            pixels[x, y] = (red, green, blue, alpha)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)


def execute_key(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    source = input_path(request, "images")
    destination = output_dir / "keyed"
    files = image_files(source)
    for index, path in enumerate(files):
        key_image(path, destination / f"frame_{index + 1:06d}.png", options_for(manifest))
    artifact(manifest, destination, "directory", "keyed-sequence")


def execute_shot_qc(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    source = input_path(request, "frames")
    files = image_files(source)
    report_frames: list[JsonMap] = []
    issues: list[JsonMap] = []
    previous_luma: float | None = None
    previous_alpha: float | None = None
    expected_size: tuple[int, int] | None = None
    luma_limit = option_float(options_for(manifest), "lumaJumpThreshold", 35.0)
    alpha_limit = option_float(options_for(manifest), "alphaJumpThreshold", 0.12)
    for index, path in enumerate(files):
        try:
            image = Image.open(path).convert("RGBA")
            luma = float(ImageStat.Stat(ImageOps.grayscale(image.convert("RGB"))).mean[0])
            alpha = float(ImageStat.Stat(image.getchannel("A")).mean[0]) / 255.0
        except OSError as exc:
            issues.append({"frame": index, "code": "corrupt-frame", "detail": str(exc)})
            continue
        if expected_size is None:
            expected_size = image.size
        elif image.size != expected_size:
            issues.append({"frame": index, "code": "size-change", "expected": expected_size, "actual": image.size})
        if previous_luma is not None and abs(luma - previous_luma) > luma_limit:
            issues.append({"frame": index, "code": "luma-jump", "delta": abs(luma - previous_luma)})
        if previous_alpha is not None and abs(alpha - previous_alpha) > alpha_limit:
            issues.append({"frame": index, "code": "alpha-chatter", "delta": abs(alpha - previous_alpha)})
        report_frames.append({"frame": index, "path": str(path), "width": image.width, "height": image.height, "meanLuma": luma, "meanAlpha": alpha})
        previous_luma, previous_alpha = luma, alpha
    report = output_dir / "shot-qc.json"
    notes = output_dir / "shot-qc.md"
    write_json(report, {"schemaVersion": "mere.run/vfx-qc.v1", "ok": not issues, "frameCount": len(files), "frames": report_frames, "issues": issues})
    lines = ["# Shot QC", "", f"Frames inspected: {len(files)}", f"Issues: {len(issues)}", ""]
    lines.extend(f"- Frame {item.get('frame')}: {item.get('code')}" for item in issues)
    notes.write_text("\n".join(lines) + "\n")
    artifact(manifest, report, "json", "shot-qc")
    artifact(manifest, notes, "markdown", "shot-qc-notes")


def video_generate_argv(manifest: JsonMap, prompt: str, output: pathlib.Path, start: pathlib.Path, end: pathlib.Path | None = None) -> list[str]:
    options = options_for(manifest)
    argv = runtime_command(manifest, "mereRunCommand") + [
        "video", "generate", prompt, "--variant", option_string(options, "variant", "distilled"),
        "--model", option_string(options, "model", "video-ltx23-av-mlx"), "--image", str(start),
        "--image-strength", str(option_float(options, "imageStrength", 0.9)),
        "--num-frames", str(option_int(options, "numFrames", 65)), "--fps", str(option_int(options, "fps", 24)),
        "--seed", str(option_int(options, "seed", 42)), "--output", str(output),
    ]
    if end is not None:
        argv.extend(["--end-image", str(end), "--end-image-strength", str(option_float(options, "endImageStrength", 0.85))])
    return argv


def execute_inbetween(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    start = input_path(request, "startImage")
    end = input_path(request, "endImage")
    prompt = option_string(options_for(manifest), "prompt", "smooth coherent motion between the supplied keyframes")
    output = output_dir / "inbetween.mp4"
    run_process(video_generate_argv(manifest, prompt, output, start, end), "mere.run video generate")
    artifact(manifest, output, "video", "generative-inbetween")


def contact_sheet(paths: list[pathlib.Path], destination: pathlib.Path, columns: int = 4) -> None:
    if not paths:
        raise PluginError("cannot create contact sheet without images")
    images = [Image.open(path).convert("RGB") for path in paths]
    thumb_width = 320
    thumbs: list[Image.Image] = []
    for image in images:
        height = max(1, int(image.height * thumb_width / image.width))
        thumbs.append(image.resize((thumb_width, height)))
    cell_height = max(image.height for image in thumbs)
    rows = math.ceil(len(thumbs) / columns)
    sheet = Image.new("RGB", (columns * thumb_width, rows * cell_height), "#151515")
    for index, image in enumerate(thumbs):
        sheet.paste(image, ((index % columns) * thumb_width, (index // columns) * cell_height))
    sheet.save(destination)


def execute_turntable(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    image = input_path(request, "image")
    prompt = option_string(options_for(manifest), "prompt", "a smooth full 360 degree studio turntable orbit, consistent subject and lighting")
    output = output_dir / "turntable.mp4"
    run_process(video_generate_argv(manifest, prompt, output, image), "mere.run video generate")
    frames = extract_video_frames(manifest, output, output_dir / "turntable-frames")
    selected = frames[:: max(1, len(frames) // 8)][:8]
    sheet = output_dir / "turntable-contact-sheet.jpg"
    contact_sheet(selected, sheet)
    artifact(manifest, output, "video", "turntable")
    artifact(manifest, sheet, "image", "turntable-contact-sheet")


def execute_character_sheet(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    reference = input_path(request, "referenceImage")
    options = options_for(manifest)
    views = string_list(options.get("views")) or ["front view", "left profile", "right profile", "back view", "three-quarter view", "neutral full body"]
    prompt_prefix = option_string(options, "prompt", "same character, neutral studio character reference")
    images_dir = output_dir / "character-views"
    images_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[pathlib.Path] = []
    for index, view in enumerate(views):
        destination = images_dir / f"view_{index + 1:02d}.png"
        argv = runtime_command(manifest, "mereRunCommand") + [
            "image", "generate", "--model", option_string(options, "model", "image-klein-9b"),
            "--ref-image", str(reference), "--strength", str(option_float(options, "strength", 0.55)),
            "--prompt", f"{prompt_prefix}, {view}", "--seed", str(option_int(options, "seed", 525252) + index),
            "--output", str(destination),
        ]
        lora = option_string(options, "lora")
        if lora:
            argv.extend(["--lora", lora, "--lora-scale", str(option_float(options, "loraScale", 1.5))])
        run_process(argv, "mere.run image generate")
        outputs.append(destination)
    sheet = output_dir / "character-sheet.jpg"
    contact_sheet(outputs, sheet, 3)
    artifact(manifest, images_dir, "directory", "character-views")
    artifact(manifest, sheet, "image", "character-sheet")


def sequence_source_frames(manifest: JsonMap, output_dir: pathlib.Path, directory_name: str) -> tuple[list[pathlib.Path], str]:
    request = as_map(manifest["request"], "request")
    inputs = as_map(request["inputs"], "request.inputs")
    if isinstance(inputs.get("video"), str):
        video = input_path(request, "video")
        return extract_video_frames(manifest, video, output_dir / directory_name), str(video)
    frames = input_path(request, "frames")
    return image_files(frames), str(frames)


def point_number(point: JsonMap, key: str) -> float:
    value = point.get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def execute_pose_sequence(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    options = options_for(manifest)
    frames, source = sequence_source_frames(manifest, output_dir, "pose-source-frames")
    if not frames:
        raise PluginError("pose sequence input produced no frames")
    fps = option_float(options, "fps", 24.0)
    if fps <= 0:
        raise PluginError("request.options.fps must be greater than zero", 2)
    pose_dir = output_dir / "pose-frames"
    pose_dir.mkdir(parents=True, exist_ok=True)
    sequence_frames: list[JsonMap] = []
    csv_rows: list[list[object]] = []
    ae_layers: dict[str, list[JsonMap]] = {}
    blender_frames: list[JsonMap] = []
    for frame_index, frame_path in enumerate(frames):
        pose_path = pose_dir / f"frame_{frame_index + 1:06d}.json"
        argv = runtime_command(manifest, "mereRunCommand") + [
            "vision", "pose", str(frame_path), "--json-output", str(pose_path),
            "--minimum-confidence", str(option_float(options, "minimumConfidence", 0.1)),
            "--max-hands", str(option_int(options, "maxHands", 2)),
        ]
        if not option_bool(options, "includeBody", True):
            argv.append("--no-body")
        if not option_bool(options, "includeHands", True):
            argv.append("--no-hands")
        if not option_bool(options, "includeFace", True):
            argv.append("--no-face")
        run_process(argv, "mere.run vision pose")
        pose = as_map(json.loads(pose_path.read_text()), f"pose frame {frame_index}")
        timestamp = frame_index / fps
        subjects_value = pose.get("subjects", [])
        subjects = subjects_value if isinstance(subjects_value, list) else []
        sequence_frames.append({
            "frameIndex": frame_index,
            "timestampSeconds": timestamp,
            "sourceFrame": str(frame_path),
            "poseArtifact": str(pose_path),
            "subjects": subjects,
        })
        blender_points: list[JsonMap] = []
        width_value = pose.get("imageWidth", 0)
        height_value = pose.get("imageHeight", 0)
        width = float(width_value) if isinstance(width_value, (int, float)) else 0.0
        height = float(height_value) if isinstance(height_value, (int, float)) else 0.0
        for raw_subject in subjects:
            if not isinstance(raw_subject, dict):
                continue
            subject = cast(JsonMap, raw_subject)
            kind = str(subject.get("kind", "subject"))
            subject_index_value = subject.get("index", 0)
            subject_index = int(subject_index_value) if isinstance(subject_index_value, (int, float)) else 0
            points_value = subject.get("points", [])
            points = points_value if isinstance(points_value, list) else []
            for raw_point in points:
                if not isinstance(raw_point, dict):
                    continue
                point = cast(JsonMap, raw_point)
                name = str(point.get("name", "point"))
                x = point_number(point, "x")
                y = point_number(point, "y")
                confidence = point_number(point, "confidence")
                layer = f"{kind}.{subject_index}.{name}"
                pixel_x = x * width
                pixel_y_top = (1.0 - y) * height
                csv_rows.append([frame_index, timestamp, kind, subject_index, name, x, y, pixel_x, pixel_y_top, confidence])
                keyframe: JsonMap = {
                    "frame": frame_index,
                    "timeSeconds": timestamp,
                    "position": [pixel_x, pixel_y_top],
                    "confidence": confidence,
                }
                ae_layers.setdefault(layer, []).append(keyframe)
                blender_points.append({
                    "track": layer,
                    "normalizedImagePosition": [x, y],
                    "pixelPositionTopLeft": [pixel_x, pixel_y_top],
                    "confidence": confidence,
                })
        blender_frames.append({"frame": frame_index, "timeSeconds": timestamp, "points": blender_points})

    sequence_path = output_dir / "pose-sequence.json"
    csv_path = output_dir / "pose-sequence.csv"
    ae_path = output_dir / "pose-after-effects.json"
    blender_path = output_dir / "pose-blender.json"
    first_pose = as_map(json.loads((pose_dir / "frame_000001.json").read_text()), "first pose")
    output_width: object = first_pose.get("imageWidth")
    output_height: object = first_pose.get("imageHeight")
    write_json(sequence_path, {
        "schemaVersion": "mere.run/vfx-pose-sequence.v1",
        "source": source,
        "fps": fps,
        "coordinateSpace": "normalized-bottom-left",
        "frames": sequence_frames,
    })
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "time_seconds", "kind", "subject_index", "point", "x_normalized", "y_normalized", "x_pixels", "y_pixels_top", "confidence"])
        writer.writerows(csv_rows)
    write_json(ae_path, {
        "schemaVersion": "mere.run/vfx-pose-after-effects.v1",
        "fps": fps,
        "width": output_width,
        "height": output_height,
        "origin": "top-left",
        "layers": [{"name": name, "keyframes": keyframes} for name, keyframes in sorted(ae_layers.items())],
    })
    write_json(blender_path, {
        "schemaVersion": "mere.run/vfx-pose-blender.v1",
        "fps": fps,
        "width": output_width,
        "height": output_height,
        "coordinateSpace": "image-2d",
        "frames": blender_frames,
    })
    artifact(manifest, pose_dir, "directory", "per-frame-pose")
    artifact(manifest, sequence_path, "json", "pose-sequence")
    artifact(manifest, csv_path, "csv", "pose-table")
    artifact(manifest, ae_path, "json", "after-effects-pose")
    artifact(manifest, blender_path, "json", "blender-pose")


def execute_motion_pass(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    options = options_for(manifest)
    frames, source = sequence_source_frames(manifest, output_dir, "motion-source-frames")
    if len(frames) < 2:
        raise PluginError("motion pass input must contain at least two frames", 2)
    fps = option_float(options, "fps", 24.0)
    if fps <= 0:
        raise PluginError("request.options.fps must be greater than zero", 2)
    accuracy = option_string(options, "accuracy", "high")
    if accuracy not in {"low", "medium", "high", "very-high"}:
        raise PluginError("request.options.accuracy must be low, medium, high, or very-high", 2)
    flow_dir = output_dir / "motion-flow"
    flow_dir.mkdir(parents=True, exist_ok=True)
    flows: list[JsonMap] = []
    for frame_index, (from_frame, to_frame) in enumerate(zip(frames, frames[1:])):
        stem = f"flow_{frame_index + 1:06d}_to_{frame_index + 2:06d}"
        flow_path = flow_dir / f"{stem}.flo"
        metadata_path = flow_dir / f"{stem}.json"
        argv = runtime_command(manifest, "mereRunCommand") + [
            "vision", "flow", str(from_frame), str(to_frame),
            "--output", str(flow_path), "--json-output", str(metadata_path),
            "--accuracy", accuracy,
        ]
        run_process(argv, "mere.run vision flow")
        metadata = as_map(json.loads(metadata_path.read_text()), f"flow metadata {frame_index}")
        flows.append({
            "fromFrame": frame_index,
            "toFrame": frame_index + 1,
            "fromTimeSeconds": frame_index / fps,
            "toTimeSeconds": (frame_index + 1) / fps,
            "fromSource": str(from_frame),
            "toSource": str(to_frame),
            "flowArtifact": str(flow_path),
            "flowSha256": sha256(flow_path),
            "metadataArtifact": str(metadata_path),
            "metadataSha256": sha256(metadata_path),
            "width": metadata.get("width"),
            "height": metadata.get("height"),
            "vectorCount": metadata.get("vectorCount"),
            "meanMagnitude": metadata.get("meanMagnitude"),
            "maximumMagnitude": metadata.get("maximumMagnitude"),
        })
    manifest_path = output_dir / "motion-pass.json"
    write_json(manifest_path, {
        "schemaVersion": "mere.run/vfx-motion-pass.v1",
        "source": source,
        "fps": fps,
        "accuracy": accuracy,
        "format": "Middlebury .flo",
        "coordinateSpace": "image-pixel-displacement",
        "flowCount": len(flows),
        "flows": flows,
    })
    artifact(manifest, flow_dir, "directory", "middlebury-optical-flow")
    artifact(manifest, manifest_path, "json", "motion-pass")


def match_image_color(generated: Image.Image, source: Image.Image, sample_mask: Image.Image) -> Image.Image:
    generated_stats = ImageStat.Stat(generated, mask=sample_mask)
    source_stats = ImageStat.Stat(source, mask=sample_mask)
    channels: list[Image.Image] = []
    for index, channel in enumerate(generated.split()):
        generated_mean = generated_stats.mean[index]
        source_mean = source_stats.mean[index]
        generated_stddev = generated_stats.stddev[index]
        source_stddev = source_stats.stddev[index]
        scale = source_stddev / generated_stddev if generated_stddev > 1e-6 else 1.0
        lookup = [
            int(max(0.0, min(255.0, (value - generated_mean) * scale + source_mean)))
            for value in range(256)
        ]
        channels.append(channel.point(lookup))
    return Image.merge("RGB", channels)


def execute_clean_plate(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    options = options_for(manifest)
    inputs = as_map(request["inputs"], "request.inputs")
    source_files = image_files(input_path(request, "images"))
    mask_files = image_files(input_path(request, "masks"))
    if len(mask_files) not in {1, len(source_files)}:
        raise PluginError("clean plate requires one shared mask or one mask per source image", 2)
    provided_candidates: list[pathlib.Path] = []
    if isinstance(inputs.get("candidateImages"), str):
        provided_candidates = image_files(input_path(request, "candidateImages"))
        if len(provided_candidates) not in {1, len(source_files)}:
            raise PluginError("clean plate requires one shared candidate or one candidate per source image", 2)
    mask_mode = option_string(options, "maskMode", "bounding-box")
    if mask_mode not in {"matte", "bounding-box"}:
        raise PluginError("request.options.maskMode must be matte or bounding-box", 2)
    candidates_dir = output_dir / "clean-plate-candidates"
    plates_dir = output_dir / "clean-plates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    plates_dir.mkdir(parents=True, exist_ok=True)
    deliveries: list[JsonMap] = []
    for index, source_path in enumerate(source_files):
        mask_path = mask_files[0] if len(mask_files) == 1 else mask_files[index]
        candidate = candidates_dir / f"frame_{index + 1:06d}.png"
        destination = plates_dir / f"frame_{index + 1:06d}.png"
        source = Image.open(source_path).convert("RGB")
        if provided_candidates:
            candidate_source = provided_candidates[0] if len(provided_candidates) == 1 else provided_candidates[index]
            shutil.copy2(candidate_source, candidate)
        else:
            argv = runtime_command(manifest, "mereRunCommand") + [
                "image", "generate",
                "--model", option_string(options, "model", "image-klein-nano"),
                "--ref-image", str(source_path),
                "--strength", str(option_float(options, "strength", 0.65)),
                "--prompt", option_string(
                    options,
                    "prompt",
                    "remove the masked subject and reconstruct a clean background plate with matching lighting and texture",
                ),
                "--seed", str(option_int(options, "seed", 424242) + index),
                "--steps", str(option_int(options, "steps", 4)),
                "--width", str(source.width),
                "--height", str(source.height),
                "--output", str(candidate),
            ]
            run_process(argv, "mere.run image generate")
        generated = Image.open(candidate).convert("RGB")
        if generated.size != source.size:
            generated = generated.resize(source.size, Image.Resampling.LANCZOS)
        matte = refine_mask(Image.open(mask_path), 0, 0, 0)
        if matte.size != source.size:
            matte = matte.resize(source.size, Image.Resampling.LANCZOS)
        sample_region = matte
        if mask_mode == "bounding-box":
            bounds = matte.getbbox()
            if bounds is None:
                raise PluginError(f"clean plate mask has no selected pixels: {mask_path}", 2)
            padding = max(0, option_int(options, "boundingBoxPadding", 16))
            left, top, right, bottom = bounds
            region = Image.new("L", source.size, 0)
            ImageDraw.Draw(region).rectangle(
                (
                    max(0, left - padding),
                    max(0, top - padding),
                    min(source.width, right + padding),
                    min(source.height, bottom + padding),
                ),
                fill=255,
            )
            sample_region = region
            matte = refine_mask(region, 0, 0, option_float(options, "featherRadius", 12.0))
        else:
            matte = refine_mask(
                matte,
                option_int(options, "growPixels", 3),
                option_int(options, "chokePixels", 0),
                option_float(options, "featherRadius", 3.0),
            )
        if option_bool(options, "colorMatch", True):
            generated = match_image_color(generated, source, ImageOps.invert(sample_region))
        Image.composite(generated, source, matte).save(destination)
        deliveries.append({
            "frameIndex": index,
            "source": str(source_path),
            "mask": str(mask_path),
            "candidate": str(candidate),
            "candidateSha256": sha256(candidate),
            "cleanPlate": str(destination),
            "cleanPlateSha256": sha256(destination),
        })
    delivery_path = output_dir / "clean-plate.json"
    write_json(delivery_path, {
        "schemaVersion": "mere.run/vfx-clean-plate.v1",
        "maskMode": mask_mode,
        "colorMatched": option_bool(options, "colorMatch", True),
        "candidateSource": "provided" if provided_candidates else "mere.run image generate",
        "frames": deliveries,
    })
    artifact(manifest, candidates_dir, "directory", "generated-clean-plate-candidates")
    artifact(manifest, plates_dir, "directory", "masked-clean-plates")
    artifact(manifest, delivery_path, "json", "clean-plate-manifest")


def execute_set_extension(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    inputs = as_map(request["inputs"], "request.inputs")
    options = options_for(manifest)
    source_path = input_path(request, "image")
    source = Image.open(source_path).convert("RGB")
    width = option_int(options, "width", math.ceil(source.width * 1.5 / 16) * 16)
    height = option_int(options, "height", math.ceil(source.height * 1.5 / 16) * 16)
    if width < source.width or height < source.height:
        raise PluginError("set extension output dimensions cannot be smaller than the source", 2)
    offset_x = option_int(options, "offsetX", (width - source.width) // 2)
    offset_y = option_int(options, "offsetY", (height - source.height) // 2)
    if offset_x < 0 or offset_y < 0 or offset_x + source.width > width or offset_y + source.height > height:
        raise PluginError("set extension source offset must keep the full source inside the output canvas", 2)
    candidate = output_dir / "set-extension-candidate.png"
    if isinstance(inputs.get("candidateImage"), str):
        shutil.copy2(input_path(request, "candidateImage"), candidate)
        candidate_source = "provided"
    else:
        argv = runtime_command(manifest, "mereRunCommand") + [
            "image", "generate",
            "--model", option_string(options, "model", "image-klein-nano"),
            "--ref-image", str(source_path),
            "--strength", str(option_float(options, "strength", 0.55)),
            "--prompt", option_string(
                options,
                "prompt",
                "extend the environment beyond the original frame with matching perspective, lighting, texture, and continuity",
            ),
            "--seed", str(option_int(options, "seed", 818181)),
            "--steps", str(option_int(options, "steps", 4)),
            "--width", str(width),
            "--height", str(height),
            "--output", str(candidate),
        ]
        run_process(argv, "mere.run image generate")
        candidate_source = "mere.run image generate"
    extended = Image.open(candidate).convert("RGB")
    if extended.size != (width, height):
        extended = extended.resize((width, height), Image.Resampling.LANCZOS)
    source_region = Image.new("L", (width, height), 0)
    ImageDraw.Draw(source_region).rectangle(
        (offset_x, offset_y, offset_x + source.width - 1, offset_y + source.height - 1),
        fill=255,
    )
    source_canvas = extended.copy()
    source_canvas.paste(source, (offset_x, offset_y))
    if option_bool(options, "colorMatch", True):
        extended = match_image_color(extended, source_canvas, source_region)
        source_canvas = extended.copy()
        source_canvas.paste(source, (offset_x, offset_y))
    feather = max(0.0, option_float(options, "edgeFeather", 0.0))
    if feather > 0:
        source_region = source_region.filter(ImageFilter.GaussianBlur(feather))
    final = Image.composite(source_canvas, extended, source_region)
    destination = output_dir / "set-extension.png"
    final.save(destination)
    delivery = output_dir / "set-extension.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-set-extension.v1",
        "source": str(source_path),
        "sourceSize": [source.width, source.height],
        "outputSize": [width, height],
        "sourceOffset": [offset_x, offset_y],
        "edgeFeather": feather,
        "colorMatched": option_bool(options, "colorMatch", True),
        "candidateSource": candidate_source,
        "candidate": str(candidate),
        "candidateSha256": sha256(candidate),
        "output": str(destination),
        "outputSha256": sha256(destination),
    })
    artifact(manifest, candidate, "image", "set-extension-candidate")
    artifact(manifest, destination, "image", "set-extension")
    artifact(manifest, delivery, "json", "set-extension-manifest")


def execute_restore(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    options = options_for(manifest)
    source_files = image_files(input_path(request, "images"))
    scale = option_float(options, "scale", 2.0)
    if scale < 1.0:
        raise PluginError("request.options.scale must be at least 1.0", 2)
    restored_dir = output_dir / "restored"
    baseline_dir = output_dir / "upscale-baseline"
    restored_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    deliveries: list[JsonMap] = []
    for index, source_path in enumerate(source_files):
        source = Image.open(source_path).convert("RGB")
        width = math.ceil(source.width * scale / 16) * 16
        height = math.ceil(source.height * scale / 16) * 16
        destination = restored_dir / f"frame_{index + 1:06d}.png"
        baseline = baseline_dir / f"frame_{index + 1:06d}.png"
        source.resize((width, height), Image.Resampling.LANCZOS).save(baseline)
        argv = runtime_command(manifest, "mereRunCommand") + [
            "image", "generate",
            "--model", option_string(options, "model", "image-klein-nano"),
            "--ref-image", str(source_path),
            "--strength", str(option_float(options, "strength", 0.3)),
            "--prompt", option_string(
                options,
                "prompt",
                "restore the source faithfully, remove compression and noise, recover natural fine detail, preserve identity and composition",
            ),
            "--seed", str(option_int(options, "seed", 616161) + index),
            "--steps", str(option_int(options, "steps", 4)),
            "--width", str(width),
            "--height", str(height),
            "--output", str(destination),
        ]
        run_process(argv, "mere.run image generate")
        restored = Image.open(destination).convert("RGB")
        if restored.size != (width, height):
            restored.resize((width, height), Image.Resampling.LANCZOS).save(destination)
        deliveries.append({
            "frameIndex": index,
            "source": str(source_path),
            "sourceSize": [source.width, source.height],
            "output": str(destination),
            "outputSize": [width, height],
            "sha256": sha256(destination),
            "deterministicBaseline": str(baseline),
            "deterministicBaselineSha256": sha256(baseline),
        })
    delivery = output_dir / "restoration.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-restoration.v1",
        "scale": scale,
        "method": "native reference-guided image generation",
        "synthesizedDetail": True,
        "identityPreservationGuaranteed": False,
        "baselineMethod": "Lanczos resampling",
        "frames": deliveries,
    })
    artifact(manifest, restored_dir, "directory", "restored-sequence")
    artifact(manifest, baseline_dir, "directory", "deterministic-upscale-baseline")
    artifact(manifest, delivery, "json", "restoration-manifest")


def normal_map_from_depth(depth: Image.Image, strength: float) -> Image.Image:
    values = depth.convert("L")
    pixels = values.load()
    if pixels is None:
        raise PluginError("could not read depth pixels")
    normal = Image.new("RGB", values.size)
    output = normal.load()
    if output is None:
        raise PluginError("could not allocate normal-map pixels")
    for y in range(values.height):
        up = max(0, y - 1)
        down = min(values.height - 1, y + 1)
        for x in range(values.width):
            left = max(0, x - 1)
            right = min(values.width - 1, x + 1)
            dx = (cast(float, pixels[right, y]) - cast(float, pixels[left, y])) / 255.0 * strength
            dy = (cast(float, pixels[x, down]) - cast(float, pixels[x, up])) / 255.0 * strength
            nx, ny, nz = -dx, -dy, 1.0
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            output[x, y] = (
                int((nx / length * 0.5 + 0.5) * 255),
                int((ny / length * 0.5 + 0.5) * 255),
                int((nz / length * 0.5 + 0.5) * 255),
            )
    return normal


def execute_depth_normal(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    inputs = as_map(request["inputs"], "request.inputs")
    options = options_for(manifest)
    source_files = image_files(input_path(request, "images"))
    provided_depth: list[pathlib.Path] = []
    if isinstance(inputs.get("depthImages"), str):
        provided_depth = image_files(input_path(request, "depthImages"))
        if len(provided_depth) not in {1, len(source_files)}:
            raise PluginError("depth-normal requires one shared depth image or one per source image", 2)
    raw_dir = output_dir / "depth-candidates"
    depth_dir = output_dir / "depth"
    normal_dir = output_dir / "normals"
    raw_dir.mkdir(parents=True, exist_ok=True)
    depth_dir.mkdir(parents=True, exist_ok=True)
    normal_dir.mkdir(parents=True, exist_ok=True)
    deliveries: list[JsonMap] = []
    for index, source_path in enumerate(source_files):
        source = Image.open(source_path).convert("RGB")
        raw_depth = raw_dir / f"frame_{index + 1:06d}.png"
        if provided_depth:
            provided = provided_depth[0] if len(provided_depth) == 1 else provided_depth[index]
            shutil.copy2(provided, raw_depth)
        else:
            argv = runtime_command(manifest, "mereRunCommand") + [
                "image", "generate",
                "--model", option_string(options, "model", "image-klein-nano"),
                "--ref-image", str(source_path),
                "--strength", str(option_float(options, "strength", 0.25)),
                "--prompt", option_string(
                    options,
                    "prompt",
                    "grayscale monocular depth map of the exact source composition, white is nearest, black is farthest, no color, no text",
                ),
                "--seed", str(option_int(options, "seed", 737373) + index),
                "--steps", str(option_int(options, "steps", 4)),
                "--width", str(source.width),
                "--height", str(source.height),
                "--output", str(raw_depth),
            ]
            run_process(argv, "mere.run image generate")
        depth = ImageOps.grayscale(Image.open(raw_depth)).resize(source.size, Image.Resampling.LANCZOS)
        if option_bool(options, "autocontrast", True):
            depth = ImageOps.autocontrast(depth)
        if option_bool(options, "invertDepth", False):
            depth = ImageOps.invert(depth)
        depth_path = depth_dir / f"frame_{index + 1:06d}.png"
        normal_path = normal_dir / f"frame_{index + 1:06d}.png"
        depth.save(depth_path)
        normal_map_from_depth(depth, option_float(options, "normalStrength", 2.0)).save(normal_path)
        deliveries.append({
            "frameIndex": index,
            "source": str(source_path),
            "depth": str(depth_path),
            "depthSha256": sha256(depth_path),
            "normal": str(normal_path),
            "normalSha256": sha256(normal_path),
        })
    delivery = output_dir / "depth-normal.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-depth-normal.v1",
        "depthSource": "provided" if provided_depth else "generative proxy",
        "metricDepth": False,
        "depthConvention": "white-near-black-far" if not option_bool(options, "invertDepth", False) else "black-near-white-far",
        "normalSpace": "image-space-derived",
        "frames": deliveries,
    })
    artifact(manifest, raw_dir, "directory", "depth-candidates")
    artifact(manifest, depth_dir, "directory", "depth-passes")
    artifact(manifest, normal_dir, "directory", "normal-passes")
    artifact(manifest, delivery, "json", "depth-normal-manifest")


def execute_relight(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    options = options_for(manifest)
    source_files = image_files(input_path(request, "images"))
    normal_files = image_files(input_path(request, "normalMaps"))
    mask_files = image_files(input_path(request, "masks"))
    if len(normal_files) not in {1, len(source_files)}:
        raise PluginError("relight requires one shared normal map or one per source image", 2)
    if len(mask_files) not in {1, len(source_files)}:
        raise PluginError("relight requires one shared matte or one per source image", 2)
    light_x, light_y, light_z = option_vector(options, "lightDirection", (-0.4, -0.5, 1.0))
    light_length = math.sqrt(light_x * light_x + light_y * light_y + light_z * light_z)
    if light_length <= 1e-6:
        raise PluginError("request.options.lightDirection cannot be a zero vector", 2)
    light_x, light_y, light_z = light_x / light_length, light_y / light_length, light_z / light_length
    light_color = option_vector(options, "lightColor", (255.0, 255.0, 255.0))
    ambient = max(0.0, option_float(options, "ambient", 0.35))
    intensity = max(0.0, option_float(options, "intensity", 0.9))
    relit_dir = output_dir / "relit"
    shadow_dir = output_dir / "shadow-catchers"
    shadow_preview_dir = output_dir / "shadow-previews"
    relit_dir.mkdir(parents=True, exist_ok=True)
    shadow_dir.mkdir(parents=True, exist_ok=True)
    shadow_preview_dir.mkdir(parents=True, exist_ok=True)
    deliveries: list[JsonMap] = []
    for index, source_path in enumerate(source_files):
        normal_path = normal_files[0] if len(normal_files) == 1 else normal_files[index]
        mask_path = mask_files[0] if len(mask_files) == 1 else mask_files[index]
        source = Image.open(source_path).convert("RGB")
        normals = Image.open(normal_path).convert("RGB").resize(source.size, Image.Resampling.BILINEAR)
        source_pixels = source.load()
        normal_pixels = normals.load()
        relit = Image.new("RGB", source.size)
        relit_pixels = relit.load()
        if source_pixels is None or normal_pixels is None or relit_pixels is None:
            raise PluginError("could not access relight image pixels")
        for y in range(source.height):
            for x in range(source.width):
                normal_red, normal_green, normal_blue = cast(tuple[int, int, int], normal_pixels[x, y])
                nx = normal_red / 127.5 - 1.0
                ny = normal_green / 127.5 - 1.0
                nz = normal_blue / 127.5 - 1.0
                diffuse = max(0.0, nx * light_x + ny * light_y + nz * light_z)
                gain = ambient + intensity * diffuse
                source_red, source_green, source_blue = cast(tuple[int, int, int], source_pixels[x, y])
                relit_pixels[x, y] = (
                    int(max(0.0, min(255.0, source_red * gain * light_color[0] / 255.0))),
                    int(max(0.0, min(255.0, source_green * gain * light_color[1] / 255.0))),
                    int(max(0.0, min(255.0, source_blue * gain * light_color[2] / 255.0))),
                )
        relit_path = relit_dir / f"frame_{index + 1:06d}.png"
        relit.save(relit_path)

        matte = refine_mask(Image.open(mask_path), 0, 0, 0).resize(source.size, Image.Resampling.LANCZOS)
        offset_x = option_int(options, "shadowOffsetX", 24)
        offset_y = option_int(options, "shadowOffsetY", 12)
        projected = Image.new("L", source.size, 0)
        bounds = matte.getbbox()
        if bounds is None:
            raise PluginError(f"shadow-catcher matte has no selected pixels: {mask_path}", 2)
        left, top, right, bottom = bounds
        subject = matte.crop(bounds)
        shadow_width = max(1, int(subject.width * max(0.01, option_float(options, "shadowScaleX", 1.3))))
        shadow_height = max(1, int(subject.height * max(0.01, option_float(options, "shadowScaleY", 0.2))))
        subject = subject.resize((shadow_width, shadow_height), Image.Resampling.LANCZOS)
        angle = option_float(options, "shadowAngle", 0.0)
        if angle:
            subject = subject.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        projected.paste(subject, (left + offset_x, bottom - subject.height + offset_y))
        projected = projected.filter(ImageFilter.GaussianBlur(max(0.0, option_float(options, "shadowBlur", 18.0))))
        opacity = max(0.0, min(1.0, option_float(options, "shadowOpacity", 0.45)))
        projected = projected.point(lambda value, opacity=opacity: int(value * opacity))
        shadow = Image.new("RGBA", source.size, (0, 0, 0, 0))
        shadow.putalpha(projected)
        shadow_path = shadow_dir / f"frame_{index + 1:06d}.png"
        shadow.save(shadow_path)
        shadow_preview = Image.new("RGBA", source.size, (235, 235, 235, 255))
        shadow_preview.alpha_composite(shadow)
        shadow_preview_path = shadow_preview_dir / f"frame_{index + 1:06d}.png"
        shadow_preview.convert("RGB").save(shadow_preview_path)
        deliveries.append({
            "frameIndex": index,
            "relit": str(relit_path),
            "relitSha256": sha256(relit_path),
            "shadowCatcher": str(shadow_path),
            "shadowCatcherSha256": sha256(shadow_path),
            "shadowPreview": str(shadow_preview_path),
            "shadowPreviewSha256": sha256(shadow_preview_path),
        })
    delivery = output_dir / "relight.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-relight.v1",
        "relightingMode": "image-space-normal-diffuse",
        "shadowMode": "projected-matte-proxy",
        "lightDirection": [light_x, light_y, light_z],
        "lightColor": list(light_color),
        "ambient": ambient,
        "intensity": intensity,
        "frames": deliveries,
    })
    artifact(manifest, relit_dir, "directory", "relit-sequence")
    artifact(manifest, shadow_dir, "directory", "shadow-catcher-sequence")
    artifact(manifest, shadow_preview_dir, "directory", "shadow-catcher-review")
    artifact(manifest, delivery, "json", "relight-manifest")


def execute_image_to_3d(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    inputs = as_map(request["inputs"], "request.inputs")
    options = options_for(manifest)
    if isinstance(inputs.get("video"), str) or isinstance(inputs.get("frames"), str):
        source_files, source_label = sequence_source_frames(manifest, output_dir, "geometry-source-frames")
    else:
        images = input_path(request, "images")
        source_files, source_label = image_files(images), str(images)
    depth_files = image_files(input_path(request, "depthImages"))
    if len(depth_files) not in {1, len(source_files)}:
        raise PluginError("image-to-3d requires one shared depth pass or one per source frame", 2)
    stride = option_int(options, "stride", 8)
    if stride < 1:
        raise PluginError("request.options.stride must be at least 1", 2)
    near_depth = option_float(options, "nearDepth", 0.5)
    far_depth = option_float(options, "farDepth", 5.0)
    if near_depth <= 0 or far_depth <= near_depth:
        raise PluginError("image-to-3d requires 0 < nearDepth < farDepth", 2)
    max_depth_jump = option_float(options, "maxDepthJump", (far_depth - near_depth) * 0.15)
    geometry_dir = output_dir / "geometry"
    geometry_dir.mkdir(parents=True, exist_ok=True)
    deliveries: list[JsonMap] = []
    for frame_index, source_path in enumerate(source_files):
        depth_path = depth_files[0] if len(depth_files) == 1 else depth_files[frame_index]
        source = Image.open(source_path).convert("RGB")
        depth = Image.open(depth_path).convert("L").resize(source.size, Image.Resampling.BILINEAR)
        focal_length = option_float(options, "focalLengthPixels", float(max(source.size)))
        if focal_length <= 0:
            raise PluginError("request.options.focalLengthPixels must be greater than zero", 2)
        xs = list(range(0, source.width, stride))
        ys = list(range(0, source.height, stride))
        source_pixels = source.load()
        depth_pixels = depth.load()
        if source_pixels is None or depth_pixels is None:
            raise PluginError("could not access image-to-3d pixels")
        vertices: list[tuple[float, float, float, int, int, int]] = []
        depths: list[float] = []
        center_x = (source.width - 1) / 2.0
        center_y = (source.height - 1) / 2.0
        for y in ys:
            for x in xs:
                normalized = cast(float, depth_pixels[x, y]) / 255.0
                z = far_depth - normalized * (far_depth - near_depth)
                point_x = (x - center_x) * z / focal_length
                point_y = -(y - center_y) * z / focal_length
                red, green, blue = cast(tuple[int, int, int], source_pixels[x, y])
                vertices.append((point_x, point_y, z, red, green, blue))
                depths.append(z)
        columns = len(xs)
        rows = len(ys)
        faces: list[tuple[int, int, int]] = []
        for row in range(rows - 1):
            for column in range(columns - 1):
                top_left = row * columns + column
                quad = [top_left, top_left + 1, top_left + columns, top_left + columns + 1]
                quad_depths = [depths[index] for index in quad]
                if max(quad_depths) - min(quad_depths) <= max_depth_jump:
                    faces.append((quad[0], quad[2], quad[1]))
                    faces.append((quad[1], quad[2], quad[3]))
        ply_path = geometry_dir / f"frame_{frame_index + 1:06d}.ply"
        obj_path = geometry_dir / f"frame_{frame_index + 1:06d}.obj"
        ply_lines = [
            "ply", "format ascii 1.0", f"element vertex {len(vertices)}",
            "property float x", "property float y", "property float z",
            "property uchar red", "property uchar green", "property uchar blue", "end_header",
        ]
        ply_lines.extend(f"{x:.7f} {y:.7f} {z:.7f} {red} {green} {blue}" for x, y, z, red, green, blue in vertices)
        ply_path.write_text("\n".join(ply_lines) + "\n")
        obj_lines = ["# mere-vfx-tools 2.5D depth projection", "# vertex colors follow xyz as rgb"]
        obj_lines.extend(
            f"v {x:.7f} {y:.7f} {z:.7f} {red / 255.0:.6f} {green / 255.0:.6f} {blue / 255.0:.6f}"
            for x, y, z, red, green, blue in vertices
        )
        obj_lines.extend(f"f {a + 1} {b + 1} {c + 1}" for a, b, c in faces)
        obj_path.write_text("\n".join(obj_lines) + "\n")
        deliveries.append({
            "frameIndex": frame_index,
            "source": str(source_path),
            "depth": str(depth_path),
            "vertexCount": len(vertices),
            "faceCount": len(faces),
            "pointCloud": str(ply_path),
            "pointCloudSha256": sha256(ply_path),
            "mesh": str(obj_path),
            "meshSha256": sha256(obj_path),
        })
    delivery = output_dir / "image-to-3d.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-image-to-3d.v1",
        "source": source_label,
        "geometryMode": "2.5D depth projection",
        "metricGeometry": False,
        "coordinateSpace": "camera-local-x-right-y-up-z-forward",
        "nearDepth": near_depth,
        "farDepth": far_depth,
        "stride": stride,
        "frames": deliveries,
    })
    artifact(manifest, geometry_dir, "directory", "projected-geometry")
    artifact(manifest, delivery, "json", "image-to-3d-manifest")


Executor = Callable[[JsonMap, pathlib.Path], None]
EXECUTORS: dict[str, Executor] = {
    "roto": execute_roto,
    "matte-refine": execute_matte_refine,
    "track-export": execute_track_export,
    "key": execute_key,
    "shot-qc": execute_shot_qc,
    "inbetween": execute_inbetween,
    "turntable": execute_turntable,
    "character-sheet": execute_character_sheet,
    "pose-sequence": execute_pose_sequence,
    "motion-pass": execute_motion_pass,
    "clean-plate": execute_clean_plate,
    "set-extension": execute_set_extension,
    "restore": execute_restore,
    "depth-normal": execute_depth_normal,
    "relight": execute_relight,
    "image-to-3d": execute_image_to_3d,
}


def execute_manifest(path: pathlib.Path, manifest: JsonMap) -> JsonMap:
    output_dir = pathlib.Path(str(as_map(manifest["local"], "local")["outputDirectory"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    tool = str(as_map(manifest["tool"], "tool")["name"])
    executor = EXECUTORS.get(tool)
    if executor is None:
        raise PluginError(f"unsupported VFX tool: {tool}", 2)
    update_manifest(path, manifest, "running")
    try:
        executor(manifest, output_dir)
        update_manifest(path, manifest, "succeeded")
    except Exception as exc:
        manifest["error"] = str(exc)
        update_manifest(path, manifest, "failed")
        raise
    return manifest


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    mere = split_command(args.mere_run_command, "mere.run command")
    ffmpeg = split_command(args.ffmpeg_command, "ffmpeg command")
    checks = [
        {"name": "python", "ok": True, "detail": sys.version.split()[0]},
        {"name": "mere.run", "ok": command_available(mere), "detail": shlex.join(mere)},
        {"name": "ffmpeg", "ok": command_available(ffmpeg), "detail": shlex.join(ffmpeg)},
        {"name": "pillow", "ok": True, "detail": PIL.__version__},
    ]
    ok = all(bool(item["ok"]) for item in checks)
    print_json({"ok": ok, "checks": checks})
    return 0 if ok else 3


def command_plan(args: argparse.Namespace) -> int:
    manifest = make_manifest(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "run.json", manifest)
    print_json(manifest)
    return 0


def command_run(args: argparse.Namespace) -> int:
    manifest = as_map(json.loads(args.run_manifest.read_text()), "run manifest")
    if args.dry_run:
        print_json(manifest)
        return 0
    print_json(execute_manifest(args.run_manifest, manifest))
    return 0


def command_resume(args: argparse.Namespace) -> int:
    manifest = as_map(json.loads(args.run_manifest.read_text()), "run manifest")
    if args.execute and manifest.get("status") in {"planned", "failed"}:
        print_json(execute_manifest(args.run_manifest, manifest))
    else:
        print_json({key: manifest.get(key) for key in ("runId", "status", "tool", "artifacts", "cleanup", "error")})
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    manifest = as_map(json.loads(args.run_manifest.read_text()), "run manifest")
    cleanup = as_map(manifest.setdefault("cleanup", {"default": "none", "status": "not-started"}), "cleanup")
    cleanup.update({"status": "skipped", "reason": "local VFX runs do not create remote resources"})
    update_manifest(args.run_manifest, manifest)
    print_json(manifest)
    return 0


def command_one_shot(args: argparse.Namespace) -> int:
    manifest = make_manifest(args)
    path = args.output_dir / "run.json"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(path, manifest)
    if args.dry_run:
        print_json(manifest)
    else:
        print_json(execute_manifest(path, manifest))
    return 0


def add_workflow_args(parser: argparse.ArgumentParser, include_tool: bool) -> None:
    if include_tool:
        parser.add_argument("--tool", required=True, choices=sorted(TOOLS))
    parser.add_argument("--request-json", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--mere-run-command", default="")
    parser.add_argument("--ffmpeg-command", default="")


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    for name in ("request_json", "output_dir", "run_manifest"):
        if hasattr(args, name):
            value = getattr(args, name)
            if value is not None:
                setattr(args, name, value.expanduser().resolve())
    if hasattr(args, "mere_run_command") and not args.mere_run_command:
        args.mere_run_command = os.environ.get("MERE_VFX_TOOLS_MERE_RUN", "mere.run")
    if hasattr(args, "ffmpeg_command") and not args.ffmpeg_command:
        args.ffmpeg_command = os.environ.get("MERE_VFX_TOOLS_FFMPEG", "ffmpeg")
    if hasattr(args, "run_id") and not args.run_id:
        args.run_id = default_run_id(args.tool)
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME)
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--mere-run-command", default="")
    doctor.add_argument("--ffmpeg-command", default="")
    doctor.set_defaults(func=command_doctor)
    plan = sub.add_parser("plan")
    add_workflow_args(plan, True)
    plan.set_defaults(func=command_plan)
    run = sub.add_parser("run")
    run.add_argument("run_manifest", type=pathlib.Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run)
    resume = sub.add_parser("resume")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.add_argument("--execute", action="store_true")
    resume.set_defaults(func=command_resume)
    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=command_cleanup)
    for tool, spec in TOOLS.items():
        command = sub.add_parser(tool, help=spec.description)
        add_workflow_args(command, False)
        command.set_defaults(tool=tool, func=command_one_shot)
        command.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(normalize_args(args).func(args))
    except PluginError as exc:
        eprint(f"Error: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        eprint("Interrupted.")
        return 130
    except Exception as exc:
        eprint(f"Unexpected error: {exc}")
        return 1

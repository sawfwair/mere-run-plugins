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
MOGE_MODEL_ID = "vision-geometry-moge2-small"
MOGE_REPOSITORY = "Ruicheng/moge-2-vits-normal-onnx"
MOGE_REVISION = "e50ffda41565591092adea54c6ac83d6212e1e23"
MOGE_WEIGHTS_SHA256 = "24eacb5dc7a2c54c7bc98f7de085ffbed79ad006ea5b664c2c2cdc02ff3a52f0"
VDA_MODEL_PINS: dict[str, tuple[str, str, str, frozenset[str]]] = {
    "vision-depth-vda-small": (
        "depth-anything/Video-Depth-Anything-Small",
        "256875362cff76724b920335dfb4b29dd611f66e",
        "affine-relative",
        frozenset({
            "13379300b739e659f076a59d52e9801bd8d38c541a7e71f73bbca4dcfb013609",
            "85c583474dcafda4d417776431343afcdfdfc97952d8ec00029d3452c55a05a2",
        }),
    ),
    "vision-depth-vda-small-metric": (
        "depth-anything/Metric-Video-Depth-Anything-Small",
        "273d090f2ce17df50c2872d82c8322c45da5b4dd",
        "metric-meters",
        frozenset({
            "3c28432b4e1f0d7bb31cad5151b6313b49457db5aa58d82e85bfb0f8b1311b33",
            "0acf1e186750abddf5ae867a3a659ed67cd0c041e4e524e698a0dcb40195c779",
        }),
    ),
}
INSTANTMESH_MODEL_ID = "image-3d-instantmesh-base"
INSTANTMESH_REPOSITORY = "TencentARC/InstantMesh"
INSTANTMESH_REVISION = "b785b4ecfb6636ef34a08c748f96f6a5686244d0"
INSTANTMESH_SOURCE_REVISION = "08822c52fdc399b93ea00e4fa9e596344ed52ccc"
INSTANTMESH_LICENSE = "Apache-2.0 reconstruction weights; view generation excluded"
INSTANTMESH_WEIGHTS_BYTE_COUNT = 1_253_463_832
INSTANTMESH_WEIGHTS_SHA256 = "2380601d17f6a817de0bf5328188ccea397af9d75c07b4b3cc476322dcca76af"
INSTANTMESH_SOURCE_SHA256 = "22701cd25201d624ebb1568b93cf91b43a2c32006835c08fe73e1f3c9f6c44b5"
INSTANTMESH_CONFIGURATION_SHA256 = "33f89581172ab2d46759a1632b6e57ca9f9f1c6c23567468157cb4b48a3bc781"
INSTANTMESH_SOURCE_MANIFEST_SHA256 = "74787d99b53952df12722323521b16056bb91d7ed708cb757b7efff519ee39fa"
INSTANTMESH_EXTRACTION_ALGORITHM = "native-marching-tetrahedra"
INSTANTMESH_TOPOLOGY_COMPATIBILITY = "learned-field-parity-no-topology-parity-with-upstream-flexicubes"


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


@dataclass(frozen=True)
class NativeRun:
    payload: JsonMap
    manifest_path: pathlib.Path
    manifest: JsonMap
    artifacts_by_kind: dict[str, list[pathlib.Path]]
    artifact_records: list[JsonMap]


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
        "Generate native metric depth, normal, camera, and point-cloud passes.",
        ("depth-pass", "normal-pass", "camera", "point-cloud", "blender", "nuke"),
    ),
    "relight": ToolSpec(
        "relight",
        "Relight and Shadow Catcher",
        "Relight frames from supplied or native geometry normals and project matte-based shadow layers.",
        ("relighting", "shadow-catcher", "normal-pass", "alpha-matte"),
    ),
    "video-depth": ToolSpec(
        "video-depth",
        "Video Depth",
        "Generate temporally consistent native video-depth sequences and review media.",
        ("video-depth", "depth-pass", "depth-sequence", "nuke", "blender"),
    ),
    "multiview-geometry": ToolSpec(
        "multiview-geometry",
        "Multi-view Geometry",
        "Solve ordered views into native relative cameras and colored point-cloud handoffs.",
        ("multi-view", "relative-depth", "camera", "point-cloud", "glb", "3dgs-initialization"),
    ),
    "image-to-3d": ToolSpec(
        "image-to-3d",
        "Image to Native 3D",
        "Reconstruct one image into verified native TripoSR OBJ, PLY, and GLB meshes.",
        ("image-to-3d", "triposr", "obj", "ply", "glb", "mesh", "blender"),
    ),
    "multiview-image-to-3d": ToolSpec(
        "multiview-image-to-3d",
        "Multi-view Image to Native 3D",
        "Reconstruct exactly 4 or 6 ordered user views into verified native InstantMesh meshes.",
        (
            "multiview-image-to-3d",
            "instantmesh",
            "multi-view",
            "obj",
            "ply",
            "glb",
            "mesh",
            "blender",
        ),
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


def run_json_process(argv: list[str], label: str) -> JsonMap:
    if not command_available(argv):
        raise PluginError(f"{label} command not found: {argv[0]}", 3)
    eprint("$ " + shlex.join(argv))
    process = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if process.stderr:
        for line in process.stderr.splitlines():
            eprint(line)
    if process.returncode != 0:
        if process.stdout:
            for line in process.stdout.splitlines():
                eprint(line)
        raise PluginError(f"{label} failed with exit {process.returncode}")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise PluginError(f"{label} did not return valid JSON: {exc}") from None
    return as_map(payload, f"{label} result")


def read_json_map(path: pathlib.Path, context: str) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), context)
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginError(f"could not read {context} {path}: {exc}") from None


def confined_path(root: pathlib.Path, value: str, context: str) -> pathlib.Path:
    root = root.resolve()
    candidate = pathlib.Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise PluginError(f"{context} escapes native output directory: {candidate}") from None
    if not candidate.is_file():
        raise PluginError(f"{context} does not exist: {candidate}")
    return candidate


def normalized_sha256(value: str) -> str:
    return value if value.startswith("sha256:") else "sha256:" + value


def validate_native_input_identity(
    document: JsonMap,
    source: pathlib.Path,
    label: str,
) -> JsonMap:
    if document.get("schemaVersion") != 2:
        raise PluginError(f"{label} manifest schemaVersion must be 2")
    source = source.resolve()
    input_path = document.get("inputPath")
    if not isinstance(input_path, str) or pathlib.Path(input_path).resolve() != source:
        raise PluginError(f"{label} manifest inputPath does not match the requested source")
    byte_count = document.get("inputByteCount")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count != source.stat().st_size:
        raise PluginError(f"{label} manifest inputByteCount does not match the requested source")
    input_sha = validated_sha256(document.get("inputSHA256"), f"{label} manifest inputSHA256")
    if normalized_sha256(input_sha) != sha256(source):
        raise PluginError(f"{label} manifest inputSHA256 does not match the requested source")
    return {
        "path": str(source),
        "byteCount": byte_count,
        "sha256": normalized_sha256(input_sha),
    }


def validate_native_model_identity(
    value: object,
    *,
    label: str,
    model_id: str,
    repository: str,
    revision: str,
    license_name: str,
    allowed_weight_hashes: frozenset[str],
) -> JsonMap:
    model = as_map(value, f"{label} model")
    expected = {
        "modelID": model_id,
        "upstreamRepository": repository,
        "upstreamRevision": revision,
        "license": license_name,
        "inferenceBackend": "mere.run-native-mlx",
    }
    for key, expected_value in expected.items():
        if model.get(key) != expected_value:
            raise PluginError(f"{label} model {key} does not match the pinned native contract")
    weights_sha = validated_sha256(model.get("weightsSHA256"), f"{label} model weightsSHA256")
    if weights_sha.removeprefix("sha256:") not in allowed_weight_hashes:
        raise PluginError(f"{label} model weightsSHA256 is not an accepted pinned runtime digest")
    return model


def load_native_run(
    payload: JsonMap,
    output_directory: pathlib.Path,
    label: str,
    artifact_items: JsonList | None = None,
) -> NativeRun:
    if payload.get("status") != "completed":
        raise PluginError(f"{label} did not report completed status")
    manifest_value = payload.get("manifestPath")
    if not isinstance(manifest_value, str) or not manifest_value:
        raise PluginError(f"{label} result is missing manifestPath")
    manifest_path = confined_path(output_directory, manifest_value, f"{label} manifest")
    manifest = read_json_map(manifest_path, f"{label} manifest")
    manifest_sha = sha256(manifest_path)
    expected_manifest_sha = payload.get("manifestSHA256")
    if expected_manifest_sha is not None:
        if not isinstance(expected_manifest_sha, str):
            raise PluginError(f"{label} result manifestSHA256 must be a string")
        if normalized_sha256(expected_manifest_sha) != manifest_sha:
            raise PluginError(f"{label} manifest checksum mismatch: {manifest_path}")
    if artifact_items is None:
        artifact_items = as_list(manifest.get("artifacts", []), f"{label} manifest artifacts")
    artifacts_by_kind: dict[str, list[pathlib.Path]] = {}
    records: list[JsonMap] = []
    for index, value in enumerate(artifact_items):
        item = as_map(value, f"{label} artifact {index}")
        kind = item.get("kind")
        relative_path = item.get("relativePath")
        if not isinstance(kind, str) or not kind:
            raise PluginError(f"{label} artifact {index} is missing kind")
        if not isinstance(relative_path, str) or not relative_path:
            raise PluginError(f"{label} artifact {index} is missing relativePath")
        path = confined_path(output_directory, relative_path, f"{label} artifact {kind}")
        actual_sha = sha256(path)
        expected_sha = item.get("sha256")
        if not isinstance(expected_sha, str) or not expected_sha:
            raise PluginError(f"{label} artifact {index} is missing sha256")
        if normalized_sha256(expected_sha) != actual_sha:
            raise PluginError(f"{label} artifact checksum mismatch: {path}")
        byte_count = item.get("byteCount")
        if byte_count is not None:
            if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
                raise PluginError(f"{label} artifact {index} has invalid byteCount")
            if path.stat().st_size != byte_count:
                raise PluginError(f"{label} artifact byte count mismatch: {path}")
        record: JsonMap = {
            "kind": kind,
            "path": str(path),
            "relativePath": str(path.relative_to(output_directory.resolve())),
            "sha256": actual_sha,
        }
        media_type = item.get("mediaType")
        if isinstance(media_type, str):
            record["mediaType"] = media_type
        if isinstance(byte_count, int):
            record["byteCount"] = byte_count
        view_index = item.get("viewIndex")
        if isinstance(view_index, int):
            record["viewIndex"] = view_index
        artifacts_by_kind.setdefault(kind, []).append(path)
        records.append(record)
    return NativeRun(payload, manifest_path, manifest, artifacts_by_kind, records)


def one_native_artifact(run: NativeRun, kind: str, label: str) -> pathlib.Path:
    paths = run.artifacts_by_kind.get(kind, [])
    if len(paths) != 1:
        raise PluginError(f"{label} expected exactly one {kind} artifact, found {len(paths)}")
    return paths[0]


def geometry_model_option(options: JsonMap) -> str:
    return option_string(options, "geometryModel")


def run_native_geometry(
    manifest: JsonMap,
    source_path: pathlib.Path,
    output_directory: pathlib.Path,
    options: JsonMap,
) -> NativeRun:
    argv = runtime_command(manifest, "mereRunCommand") + [
        "vision", "geometry", str(source_path),
        "--output", str(output_directory),
        "--resolution-level", str(option_int(options, "resolutionLevel", 9)),
        "--json",
    ]
    model = geometry_model_option(options)
    if model:
        argv.extend(["--model", model])
    if isinstance(options.get("tokenCount"), (int, float)):
        argv.extend(["--token-count", str(option_int(options, "tokenCount", 0))])
    if isinstance(options.get("maxPoints"), (int, float)):
        argv.extend(["--max-points", str(option_int(options, "maxPoints", 0))])
    payload = run_json_process(argv, "mere.run vision geometry")
    run = load_native_run(payload, output_directory, "mere.run vision geometry")
    input_identity = validate_native_input_identity(run.manifest, source_path, "native geometry")
    if run.manifest.get("outputDirectory") != str(output_directory.resolve()):
        raise PluginError("native geometry manifest outputDirectory is not confined to the native run")
    model_identity = validate_native_model_identity(
        run.manifest.get("model"),
        label="native geometry",
        model_id=MOGE_MODEL_ID,
        repository=MOGE_REPOSITORY,
        revision=MOGE_REVISION,
        license_name="MIT",
        allowed_weight_hashes=frozenset({MOGE_WEIGHTS_SHA256}),
    )
    if payload.get("modelID") != MOGE_MODEL_ID:
        raise PluginError("native geometry result modelID does not match the pinned manifest")
    if run.manifest.get("units") != "meters":
        raise PluginError("native geometry did not report metric meter depth")
    for kind in ("depth-exr", "depth-preview", "normal-exr", "normal-preview", "camera", "point-cloud"):
        one_native_artifact(run, kind, "native geometry")
    run.manifest["validatedInput"] = input_identity
    run.manifest["validatedModel"] = model_identity
    return run


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


def ordered_image_inputs(request: JsonMap, key: str = "images") -> list[pathlib.Path]:
    inputs = as_map(request["inputs"], "request.inputs")
    value = inputs.get(key)
    if isinstance(value, str):
        return image_files(input_path(request, key))
    if not isinstance(value, list) or not value:
        raise PluginError(f"request.inputs.{key} must be a local image path or ordered path array", 2)
    paths: list[pathlib.Path] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise PluginError(f"request.inputs.{key}[{index}] must be a local image path", 2)
        path = pathlib.Path(item).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise PluginError(f"request image does not exist or is unsupported: {path}", 2)
        paths.append(path)
    return paths


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
    files, _source = sequence_source_frames(manifest, output_dir, "qc-source-frames")
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
    elif inputs.get("depthImages") is not None:
        raise PluginError("request.inputs.depthImages must be a local image or directory path", 2)
    deliveries: list[JsonMap] = []
    if provided_depth:
        raw_dir = output_dir / "provided-depth"
        depth_dir = output_dir / "depth"
        normal_dir = output_dir / "normals"
        raw_dir.mkdir(parents=True, exist_ok=True)
        depth_dir.mkdir(parents=True, exist_ok=True)
        normal_dir.mkdir(parents=True, exist_ok=True)
        for index, source_path in enumerate(source_files):
            source = Image.open(source_path).convert("RGB")
            raw_depth = raw_dir / f"frame_{index + 1:06d}.png"
            provided = provided_depth[0] if len(provided_depth) == 1 else provided_depth[index]
            shutil.copy2(provided, raw_depth)
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
                "normalPreview": str(normal_path),
                "normalPreviewSha256": sha256(normal_path),
                "camera": None,
                "pointCloud": None,
            })
        artifact(manifest, raw_dir, "directory", "provided-depth-source")
        artifact(manifest, depth_dir, "directory", "normalized-provided-depth")
        artifact(manifest, normal_dir, "directory", "image-space-derived-normals")
    else:
        native_root = output_dir / "native-geometry"
        for index, source_path in enumerate(source_files):
            native_output = native_root / f"frame_{index + 1:06d}"
            run = run_native_geometry(manifest, source_path, native_output, options)
            depth_path = one_native_artifact(run, "depth-exr", "native geometry")
            depth_preview = one_native_artifact(run, "depth-preview", "native geometry")
            normal_path = one_native_artifact(run, "normal-exr", "native geometry")
            normal_preview = one_native_artifact(run, "normal-preview", "native geometry")
            camera_path = one_native_artifact(run, "camera", "native geometry")
            point_cloud_path = one_native_artifact(run, "point-cloud", "native geometry")
            deliveries.append({
                "frameIndex": index,
                "source": str(source_path),
                "depth": str(depth_path),
                "depthSha256": sha256(depth_path),
                "depthPreview": str(depth_preview),
                "depthPreviewSha256": sha256(depth_preview),
                "normal": str(normal_path),
                "normalSha256": sha256(normal_path),
                "normalPreview": str(normal_preview),
                "normalPreviewSha256": sha256(normal_preview),
                "camera": str(camera_path),
                "cameraSha256": sha256(camera_path),
                "pointCloud": str(point_cloud_path),
                "pointCloudSha256": sha256(point_cloud_path),
                "geometryManifest": str(run.manifest_path),
                "geometryManifestSha256": sha256(run.manifest_path),
                "input": run.manifest.get("validatedInput"),
                "model": run.manifest.get("validatedModel"),
                "units": run.manifest.get("units"),
                "coordinateSystem": run.manifest.get("coordinateSystem"),
                "nativeArtifacts": run.artifact_records,
            })
            artifact(manifest, run.manifest_path, "json", f"native-geometry-manifest-{index + 1}")
            for kind in ("depth-exr", "depth-preview", "normal-exr", "normal-preview", "camera", "point-cloud"):
                path = one_native_artifact(run, kind, "native geometry")
                artifact(manifest, path, "file", f"native-{kind}-{index + 1}")
        artifact(manifest, native_root, "directory", "native-geometry-runs")
    delivery = output_dir / "depth-normal.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-depth-normal.v2",
        "depthSource": "provided grayscale fallback" if provided_depth else "mere.run vision geometry",
        "metricDepth": not provided_depth,
        "depthUnits": "normalized-display-values" if provided_depth else "meters",
        "depthConvention": (
            "white-near-black-far" if provided_depth and not option_bool(options, "invertDepth", False)
            else "black-near-white-far" if provided_depth
            else "positive-camera-space-z"
        ),
        "normalSource": "depth-gradient fallback" if provided_depth else "native geometry normal output",
        "normalSpace": "image-space-derived" if provided_depth else "native camera coordinate system; see each frame",
        "cameraSource": None if provided_depth else "native model-inferred camera metadata",
        "frames": deliveries,
    })
    artifact(manifest, delivery, "json", "depth-normal-manifest")


def execute_relight(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    inputs = as_map(request["inputs"], "request.inputs")
    options = options_for(manifest)
    source_files = image_files(input_path(request, "images"))
    normal_files: list[pathlib.Path] = []
    native_geometry_runs: list[NativeRun] = []
    if isinstance(inputs.get("normalMaps"), str):
        normal_files = image_files(input_path(request, "normalMaps"))
    elif inputs.get("normalMaps") is not None:
        raise PluginError("request.inputs.normalMaps must be a local image or directory path", 2)
    else:
        native_root = output_dir / "native-geometry"
        for index, source_path in enumerate(source_files):
            run = run_native_geometry(
                manifest,
                source_path,
                native_root / f"frame_{index + 1:06d}",
                options,
            )
            native_geometry_runs.append(run)
            normal_files.append(one_native_artifact(run, "normal-preview", "native geometry"))
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
            "source": str(source_path),
            "normal": str(normal_path),
            "normalSha256": sha256(normal_path),
            "relit": str(relit_path),
            "relitSha256": sha256(relit_path),
            "shadowCatcher": str(shadow_path),
            "shadowCatcherSha256": sha256(shadow_path),
            "shadowPreview": str(shadow_preview_path),
            "shadowPreviewSha256": sha256(shadow_preview_path),
            "geometryManifest": (
                str(native_geometry_runs[index].manifest_path) if native_geometry_runs else None
            ),
            "geometryManifestSha256": (
                sha256(native_geometry_runs[index].manifest_path) if native_geometry_runs else None
            ),
        })
    delivery = output_dir / "relight.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-relight.v2",
        "relightingMode": "image-space-normal-diffuse",
        "normalSource": "mere.run vision geometry" if native_geometry_runs else "provided normal maps",
        "nativeGeometry": [
            {
                "manifest": str(run.manifest_path),
                "manifestSha256": sha256(run.manifest_path),
                "input": run.manifest.get("validatedInput"),
                "model": run.manifest.get("validatedModel"),
                "units": run.manifest.get("units"),
                "coordinateSystem": run.manifest.get("coordinateSystem"),
                "artifacts": run.artifact_records,
            }
            for run in native_geometry_runs
        ],
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
    if native_geometry_runs:
        native_root = output_dir / "native-geometry"
        artifact(manifest, native_root, "directory", "native-geometry-runs")
        for index, run in enumerate(native_geometry_runs):
            artifact(manifest, run.manifest_path, "json", f"native-geometry-manifest-{index + 1}")
            artifact(
                manifest,
                one_native_artifact(run, "normal-preview", "native geometry"),
                "image",
                f"native-normal-preview-{index + 1}",
            )
    artifact(manifest, delivery, "json", "relight-manifest")


def execute_video_depth(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    options = options_for(manifest)
    video_path = input_path(request, "video")
    native_output = output_dir / "native-video-depth"
    argv = runtime_command(manifest, "mereRunCommand") + [
        "vision", "depth-video", str(video_path),
        "--output", str(native_output),
        "--input-size", str(option_int(options, "inputSize", 518)),
        "--json",
    ]
    model = option_string(options, "model")
    if model:
        argv.extend(["--model", model])
    if isinstance(options.get("maxFrames"), (int, float)):
        argv.extend(["--max-frames", str(option_int(options, "maxFrames", 0))])
    payload = run_json_process(argv, "mere.run vision depth-video")
    initial = load_native_run(payload, native_output, "mere.run vision depth-video")
    native_frames = as_list(initial.manifest.get("frames", []), "native video-depth frames")
    frame_artifacts: JsonList = []
    for index, value in enumerate(native_frames):
        frame = as_map(value, f"native video-depth frame {index}")
        frame_artifacts.extend(as_list(frame.get("artifacts", []), f"native video-depth frame {index} artifacts"))
    run = load_native_run(
        payload,
        native_output,
        "mere.run vision depth-video",
        artifact_items=frame_artifacts,
    )
    frame_count = payload.get("frameCount")
    if not isinstance(frame_count, int) or frame_count != len(native_frames):
        raise PluginError("native video-depth frame count does not match its manifest")
    if len(run.artifacts_by_kind.get("depth-exr", [])) != frame_count:
        raise PluginError("native video-depth did not emit one depth EXR per frame")
    if len(run.artifacts_by_kind.get("depth-preview", [])) != frame_count:
        raise PluginError("native video-depth did not emit one depth preview per frame")
    semantics = run.manifest.get("semantics")
    if semantics not in {"affine-relative", "metric-meters"}:
        raise PluginError(f"native video-depth reported unsupported semantics: {semantics}")
    if payload.get("semantics") != semantics:
        raise PluginError("native video-depth result and manifest semantics disagree")
    input_identity = validate_native_input_identity(
        run.manifest,
        video_path,
        "native video-depth",
    )
    if run.manifest.get("outputDirectory") != str(native_output.resolve()):
        raise PluginError("native video-depth manifest outputDirectory is not confined to the native run")
    model_id = payload.get("modelID")
    if not isinstance(model_id, str) or model_id not in VDA_MODEL_PINS:
        raise PluginError("native video-depth returned an unsupported modelID")
    repository, revision, expected_semantics, allowed_hashes = VDA_MODEL_PINS[model_id]
    if semantics != expected_semantics:
        raise PluginError("native video-depth modelID and depth semantics disagree")
    model_identity = validate_native_model_identity(
        run.manifest.get("model"),
        label="native video-depth",
        model_id=model_id,
        repository=repository,
        revision=revision,
        license_name="Apache-2.0",
        allowed_weight_hashes=allowed_hashes,
    )
    checkpoint_sha = validated_sha256(
        payload.get("checkpointSHA256"),
        "native video-depth result checkpointSHA256",
    )
    if checkpoint_sha != validated_sha256(
        model_identity.get("weightsSHA256"),
        "native video-depth model weightsSHA256",
    ):
        raise PluginError("native video-depth result and manifest runtime weights disagree")
    review_value = payload.get("reviewVideo")
    review = as_map(review_value, "native video-depth reviewVideo")
    review_relative = review.get("relativePath")
    if not isinstance(review_relative, str) or not review_relative:
        raise PluginError("native video-depth result is missing reviewVideo.relativePath")
    review_path = confined_path(native_output, review_relative, "native video-depth review")
    expected_review_sha = review.get("sha256")
    if isinstance(expected_review_sha, str) and normalized_sha256(expected_review_sha) != sha256(review_path):
        raise PluginError("native video-depth review checksum mismatch")
    delivery = output_dir / "video-depth.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-video-depth.v1",
        "source": str(video_path),
        "input": input_identity,
        "nativeManifest": str(run.manifest_path),
        "nativeManifestSha256": sha256(run.manifest_path),
        "nativeOutputDirectory": str(native_output.resolve()),
        "reviewVideo": str(review_path),
        "reviewVideoSha256": sha256(review_path),
        "modelID": payload.get("modelID"),
        "model": model_identity,
        "checkpointSHA256": checkpoint_sha,
        "depthSemantics": semantics,
        "metricDepth": semantics == "metric-meters",
        "width": payload.get("width"),
        "height": payload.get("height"),
        "fps": payload.get("fps"),
        "frameCount": frame_count,
        "temporalWindowLength": payload.get("temporalWindowLength"),
        "temporalOverlap": payload.get("temporalOverlap"),
        "streamsFinalizedFrames": payload.get("streamsFinalizedFrames"),
        "hasConfidence": payload.get("hasConfidence"),
        "hasCameraIntrinsics": payload.get("hasCameraIntrinsics"),
        "hasPointCloud": payload.get("hasPointCloud"),
        "nativeArtifacts": run.artifact_records,
    })
    artifact(manifest, native_output, "directory", "native-video-depth-sequence")
    artifact(manifest, run.manifest_path, "json", "native-video-depth-manifest")
    artifact(manifest, review_path, "video", "native-video-depth-review")
    artifact(manifest, delivery, "json", "video-depth-handoff")


def execute_multiview_geometry(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    inputs = as_map(request["inputs"], "request.inputs")
    options = options_for(manifest)
    images = ordered_image_inputs(request)
    process_resolution = option_int(options, "processResolution", 504)
    reference_view = option_string(options, "referenceView", "saddle-balanced")
    confidence_percentile = option_float(options, "confidencePercentile", 40.0)
    maximum_point_count = option_int(options, "maxPoints", 1_000_000)
    native_output = output_dir / "native-multiview-geometry"
    argv = runtime_command(manifest, "mereRunCommand") + [
        "vision", "geometry-multiview", *[str(path) for path in images],
        "--output", str(native_output),
        "--process-resolution", str(process_resolution),
        "--reference-view", reference_view,
        "--confidence-percentile", str(confidence_percentile),
        "--max-points", str(maximum_point_count),
        "--json",
    ]
    model = option_string(options, "model")
    if model:
        argv.extend(["--model", model])
    camera_path: pathlib.Path | None = None
    camera_value = inputs.get("cameras")
    if isinstance(camera_value, str):
        camera_path = input_path(request, "cameras")
        argv.extend(["--cameras", str(camera_path)])
    elif camera_value is not None:
        raise PluginError("request.inputs.cameras must be a local camera JSON path", 2)
    payload = run_json_process(argv, "mere.run vision geometry-multiview")
    run = load_native_run(payload, native_output, "mere.run vision geometry-multiview")
    if validated_sha256(
        payload.get("manifestSHA256"), "native multi-view geometry result manifestSHA256"
    ) != sha256(run.manifest_path):
        raise PluginError("native multi-view geometry manifest checksum mismatch")
    if run.manifest.get("schemaVersion") != 2:
        raise PluginError("native multi-view geometry manifest schemaVersion must be 2")
    reported_output = run.manifest.get("outputDirectory")
    if not isinstance(reported_output, str) or pathlib.Path(reported_output).resolve() != native_output.resolve():
        raise PluginError("native multi-view geometry manifest outputDirectory is not confined to the native run")
    if payload.get("depthUnits") != "relative" or run.manifest.get("units") != "relative":
        raise PluginError("native multi-view geometry did not report relative depth units")
    if payload.get("pointCloudRepresentation") != "colored-points-not-mesh":
        raise PluginError("native multi-view geometry reported an unexpected point representation")
    if payload.get("containsGaussianParameters") is not False:
        raise PluginError("native multi-view geometry must explicitly report no Gaussian parameters")
    if (camera_path is not None) != (payload.get("poseConditioned") is True):
        raise PluginError("native multi-view pose-conditioning status does not match the camera request")
    if payload.get("viewCount") != len(images):
        raise PluginError("native multi-view geometry result has the wrong view count")
    if payload.get("referenceViewStrategy") != reference_view:
        raise PluginError("native multi-view geometry result changed the requested reference view strategy")

    manifest_process_resolution = run.manifest.get("processResolution")
    if (
        isinstance(manifest_process_resolution, bool)
        or not isinstance(manifest_process_resolution, int)
        or manifest_process_resolution != process_resolution
    ):
        raise PluginError("native multi-view geometry manifest changed the requested processResolution")
    if run.manifest.get("referenceViewStrategy") != reference_view:
        raise PluginError("native multi-view geometry manifest changed the requested referenceViewStrategy")
    manifest_confidence_percentile = run.manifest.get("confidencePercentile")
    if (
        isinstance(manifest_confidence_percentile, bool)
        or not isinstance(manifest_confidence_percentile, (int, float))
        or not math.isfinite(float(manifest_confidence_percentile))
        or float(manifest_confidence_percentile) != confidence_percentile
    ):
        raise PluginError("native multi-view geometry manifest changed the requested confidencePercentile")
    manifest_maximum_point_count = run.manifest.get("maximumPointCount")
    if (
        isinstance(manifest_maximum_point_count, bool)
        or not isinstance(manifest_maximum_point_count, int)
        or manifest_maximum_point_count != maximum_point_count
    ):
        raise PluginError("native multi-view geometry manifest changed the requested maximumPointCount")

    checkpoint = validated_multiview_geometry_checkpoint(run, payload)
    native_views = as_list(run.manifest.get("views"), "native multi-view geometry views")
    if len(native_views) != len(images):
        raise PluginError("native multi-view geometry manifest has the wrong ordered view count")
    ordered_view_provenance: list[JsonMap] = []
    for index, source in enumerate(images):
        view = as_map(native_views[index], f"native multi-view geometry view {index}")
        if (
            isinstance(view.get("index"), bool)
            or view.get("index") != index
            or view.get("sourcePath") != str(source)
        ):
            raise PluginError("native multi-view geometry changed the requested view order or source path")
        source_byte_count = view.get("sourceByteCount")
        if (
            isinstance(source_byte_count, bool)
            or not isinstance(source_byte_count, int)
            or source_byte_count != source.stat().st_size
        ):
            raise PluginError(f"native multi-view geometry source byte count mismatch for view {index}")
        source_sha256 = validated_sha256(
            view.get("sourceSHA256"),
            f"native multi-view geometry view {index} sourceSHA256",
        )
        if source_sha256 != sha256(source):
            raise PluginError(f"native multi-view geometry source checksum mismatch for view {index}")
        ordered_view_provenance.append({
            "index": index,
            "sourcePath": str(source),
            "sourceByteCount": source_byte_count,
            "sourceSHA256": source_sha256,
        })
    handoff = as_map(run.manifest.get("threeDGaussianHandoff"), "native 3DGS handoff")
    if handoff.get("containsGaussianParameters") is not False:
        raise PluginError("native multi-view manifest must explicitly report no Gaussian parameters")
    required = {
        "point-cloud-ply": one_native_artifact(run, "point-cloud-ply", "native multi-view geometry"),
        "point-cloud-glb": one_native_artifact(run, "point-cloud-glb", "native multi-view geometry"),
        "cameras-json": one_native_artifact(run, "cameras-json", "native multi-view geometry"),
        "3dgs-transforms-json": one_native_artifact(run, "3dgs-transforms-json", "native multi-view geometry"),
    }
    delivery = output_dir / "multiview-geometry.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-multiview-geometry.v1",
        "orderedViews": [str(path) for path in images],
        "orderedViewProvenance": ordered_view_provenance,
        "checkpoint": checkpoint,
        "processResolution": process_resolution,
        "referenceViewStrategy": reference_view,
        "confidencePercentile": confidence_percentile,
        "maximumPointCount": maximum_point_count,
        "nativeManifest": str(run.manifest_path),
        "nativeManifestSha256": sha256(run.manifest_path),
        "nativeOutputDirectory": str(native_output.resolve()),
        "geometryMode": "native-multiview-relative-reconstruction",
        "metricGeometry": False,
        "depthUnits": "relative",
        "coordinateSystem": run.manifest.get("coordinateSystem"),
        "cameraSemantics": payload.get("cameraSemantics"),
        "cameraScaleAlignment": payload.get("cameraScaleAlignment"),
        "poseConditioned": payload.get("poseConditioned"),
        "suppliedCameraDocument": str(camera_path) if camera_path else None,
        "pointCount": payload.get("pointCount"),
        "pointCloudRepresentation": "colored-points-not-mesh",
        "meshProduced": False,
        "pointCloudPLY": str(required["point-cloud-ply"]),
        "pointCloudGLB": str(required["point-cloud-glb"]),
        "cameras": str(required["cameras-json"]),
        "transforms": str(required["3dgs-transforms-json"]),
        "threeDGaussianHandoff": handoff,
        "containsGaussianParameters": False,
        "nativeArtifacts": run.artifact_records,
    })
    artifact(manifest, native_output, "directory", "native-multiview-geometry")
    artifact(manifest, run.manifest_path, "json", "native-multiview-geometry-manifest")
    for kind, path in required.items():
        artifact(manifest, path, "file", f"native-{kind}")
    artifact(manifest, delivery, "json", "multiview-geometry-handoff")


def validated_sha256(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise PluginError(f"{context} must be a SHA-256 string")
    normalized = normalized_sha256(value.lower())
    if re.fullmatch(r"sha256:[0-9a-f]{64}", normalized) is None:
        raise PluginError(f"{context} must contain exactly 64 hexadecimal digits")
    return normalized


def validated_multiview_geometry_checkpoint(run: NativeRun, payload: JsonMap) -> JsonMap:
    checkpoint = as_map(run.manifest.get("checkpoint"), "native multi-view geometry checkpoint")
    model_id = checkpoint.get("modelID")
    if not isinstance(model_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", model_id) is None:
        raise PluginError("native multi-view geometry checkpoint has an invalid modelID")
    if payload.get("modelID") != model_id:
        raise PluginError("native multi-view geometry result and checkpoint modelID disagree")
    for key in ("repository", "sourceRepository"):
        value = checkpoint.get(key)
        if not isinstance(value, str) or re.fullmatch(r"[^/\s]+/[^/\s]+", value) is None:
            raise PluginError(f"native multi-view geometry checkpoint has an invalid {key}")
    for key in ("revision", "sourceRevision"):
        value = checkpoint.get(key)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{40}", value) is None:
            raise PluginError(f"native multi-view geometry checkpoint has an invalid {key}")
    for key in ("weightsByteCount", "configurationByteCount"):
        value = checkpoint.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise PluginError(f"native multi-view geometry checkpoint has an invalid {key}")
    weights_sha256 = validated_sha256(
        checkpoint.get("weightsSHA256"),
        "native multi-view geometry checkpoint weightsSHA256",
    )
    validated_sha256(
        checkpoint.get("configurationSHA256"),
        "native multi-view geometry checkpoint configurationSHA256",
    )
    if validated_sha256(
        payload.get("checkpointSHA256"),
        "native multi-view geometry result checkpointSHA256",
    ) != weights_sha256:
        raise PluginError("native multi-view geometry result and checkpoint weightsSHA256 disagree")
    if checkpoint.get("inferenceBackend") != "mere.run-native-mlx":
        raise PluginError("native multi-view geometry checkpoint must report mere.run-native-mlx inference")
    return checkpoint


def native_artifact_contract(items: JsonList, context: str) -> dict[tuple[str, str], tuple[str, int, str]]:
    contract: dict[tuple[str, str], tuple[str, int, str]] = {}
    for index, value in enumerate(items):
        item = as_map(value, f"{context} artifact {index}")
        kind = item.get("kind")
        relative_path = item.get("relativePath")
        media_type = item.get("mediaType")
        byte_count = item.get("byteCount")
        if not isinstance(kind, str) or not kind:
            raise PluginError(f"{context} artifact {index} is missing kind")
        if not isinstance(relative_path, str) or not relative_path:
            raise PluginError(f"{context} artifact {index} is missing relativePath")
        if not isinstance(media_type, str) or not media_type:
            raise PluginError(f"{context} artifact {index} is missing mediaType")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 1:
            raise PluginError(f"{context} artifact {index} has invalid byteCount")
        key = (kind, relative_path)
        if key in contract:
            raise PluginError(f"{context} contains duplicate artifact {kind}: {relative_path}")
        contract[key] = (
            validated_sha256(item.get("sha256"), f"{context} artifact {index} sha256"),
            byte_count,
            media_type,
        )
    return contract


def single_image_to_3d_source(request: JsonMap) -> pathlib.Path:
    inputs = as_map(request["inputs"], "request.inputs")
    if inputs.get("image") is not None and inputs.get("images") is not None:
        raise PluginError("image-to-3d accepts request.inputs.image or request.inputs.images, not both", 2)
    key = "image" if inputs.get("image") is not None else "images"
    if inputs.get(key) is None:
        raise PluginError("native image-to-3d requires one image in request.inputs.image or request.inputs.images", 2)
    value = inputs.get(key)
    if isinstance(value, list):
        paths = ordered_image_inputs(request, key)
    elif isinstance(value, str):
        paths = image_files(input_path(request, key))
    else:
        raise PluginError(f"request.inputs.{key} must be one local image path", 2)
    if len(paths) != 1:
        raise PluginError(
            "native TripoSR image-to-3d requires exactly one image; use multiview-geometry for ordered views",
            2,
        )
    return paths[0].resolve()


def execute_native_image_to_3d(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    inputs = as_map(request["inputs"], "request.inputs")
    options = options_for(manifest)
    if inputs.get("depthImages") is not None:
        raise PluginError(
            "supplied depth is the legacy 2.5D fallback; set request.options.reconstructionMode "
            "to 'supplied-depth-2.5d' to use it explicitly",
            2,
        )
    if inputs.get("video") is not None or inputs.get("frames") is not None:
        raise PluginError(
            "native TripoSR reconstructs one image; use reconstructionMode 'supplied-depth-2.5d' "
            "for the legacy frame projection fallback",
            2,
        )
    source = single_image_to_3d_source(request)
    resolution = option_int(options, "resolution", 256)
    density_threshold = option_float(options, "densityThreshold", 25.0)
    foreground_ratio = option_float(options, "foregroundRatio", 0.85)
    if not 2 <= resolution <= 512:
        raise PluginError("request.options.resolution must be between 2 and 512", 2)
    if not math.isfinite(density_threshold):
        raise PluginError("request.options.densityThreshold must be finite", 2)
    if not math.isfinite(foreground_ratio) or not 0 < foreground_ratio <= 1:
        raise PluginError("request.options.foregroundRatio must be greater than 0 and at most 1", 2)

    already_framed = option_bool(options, "alreadyFramed", False)
    no_vertex_colors = option_bool(options, "noVertexColors", False)
    native_output = output_dir / "native-triposr"
    argv = runtime_command(manifest, "mereRunCommand") + [
        "image", "reconstruct-3d", str(source),
        "--output", str(native_output),
        "--resolution", str(resolution),
        "--density-threshold", str(density_threshold),
        "--foreground-ratio", str(foreground_ratio),
    ]
    model = option_string(options, "model")
    if model:
        argv.extend(["--model", model])
    if already_framed:
        argv.append("--already-framed")
    if no_vertex_colors:
        argv.append("--no-vertex-colors")
    argv.append("--json")

    payload = run_json_process(argv, "mere.run image reconstruct-3d")
    run = load_native_run(payload, native_output, "mere.run image reconstruct-3d")
    if validated_sha256(payload.get("manifestSHA256"), "native TripoSR result manifestSHA256") != sha256(
        run.manifest_path
    ):
        raise PluginError("native TripoSR manifest checksum mismatch")
    if run.manifest.get("schemaVersion") != 1:
        raise PluginError("native TripoSR run manifest has an unsupported schemaVersion")
    reported_output = run.manifest.get("outputDirectory")
    if not isinstance(reported_output, str) or pathlib.Path(reported_output).resolve() != native_output.resolve():
        raise PluginError("native TripoSR manifest outputDirectory does not match the confined output directory")

    checkpoint = as_map(run.manifest.get("checkpoint"), "native TripoSR checkpoint")
    if checkpoint.get("modelID") != "image-3d-triposr":
        raise PluginError("native reconstruction did not report the audited image-3d-triposr model")
    if checkpoint.get("repository") != "stabilityai/TripoSR" or checkpoint.get("sourceRepository") != "VAST-AI-Research/TripoSR":
        raise PluginError("native reconstruction manifest has unexpected TripoSR provenance")
    if checkpoint.get("license") != "MIT":
        raise PluginError("native TripoSR checkpoint did not report its MIT license")
    for field in ("revision", "sourceRevision", "format"):
        if not isinstance(checkpoint.get(field), str) or not checkpoint.get(field):
            raise PluginError(f"native TripoSR checkpoint is missing {field}")
    weights_byte_count = checkpoint.get("weightsByteCount")
    if isinstance(weights_byte_count, bool) or not isinstance(weights_byte_count, int) or weights_byte_count < 1:
        raise PluginError("native TripoSR checkpoint has invalid weightsByteCount")
    checkpoint_sha = validated_sha256(checkpoint.get("weightsSHA256"), "native TripoSR checkpoint weightsSHA256")
    source_checkpoint_sha = validated_sha256(
        checkpoint.get("sourceSHA256"), "native TripoSR checkpoint sourceSHA256"
    )
    validated_sha256(checkpoint.get("configurationSHA256"), "native TripoSR checkpoint configurationSHA256")
    if payload.get("modelID") != checkpoint.get("modelID"):
        raise PluginError("native TripoSR result and manifest modelID disagree")
    if validated_sha256(payload.get("checkpointSHA256"), "native TripoSR result checkpointSHA256") != checkpoint_sha:
        raise PluginError("native TripoSR result and manifest checkpoint checksum disagree")
    if validated_sha256(
        payload.get("sourceCheckpointSHA256"), "native TripoSR result sourceCheckpointSHA256"
    ) != source_checkpoint_sha:
        raise PluginError("native TripoSR result and manifest source checkpoint checksum disagree")

    native_input = as_map(run.manifest.get("input"), "native TripoSR input")
    if native_input.get("path") != str(source):
        raise PluginError("native TripoSR manifest input path does not match the requested image")
    expected_policy = "already-framed" if already_framed else "automatic-transparent-alpha"
    if native_input.get("foregroundPolicy") != expected_policy:
        raise PluginError("native TripoSR foreground policy does not match the request")
    if payload.get("foregroundPolicy") != native_input.get("foregroundPolicy") or payload.get(
        "foregroundRatio"
    ) != native_input.get("foregroundRatio"):
        raise PluginError("native TripoSR result and manifest foreground preprocessing disagree")

    extraction = as_map(run.manifest.get("extraction"), "native TripoSR extraction")
    if extraction.get("resolution") != resolution:
        raise PluginError("native TripoSR extraction resolution does not match the request")
    if extraction.get("includesVertexColors") != (not no_vertex_colors):
        raise PluginError("native TripoSR vertex-color status does not match the request")
    if extraction.get("algorithm") != "native-marching-tetrahedra":
        raise PluginError("native TripoSR manifest reported an unexpected mesh extraction algorithm")
    if extraction.get("topologyCompatibility") != "same-sampled-isosurface-not-byte-topology-parity-with-torchmcubes":
        raise PluginError("native TripoSR manifest is missing the topology compatibility boundary")
    for payload_key, manifest_key in (
        ("extractionResolution", "resolution"),
        ("densityThreshold", "densityThreshold"),
        ("includesVertexColors", "includesVertexColors"),
        ("meshExtractionAlgorithm", "algorithm"),
    ):
        if payload.get(payload_key) != extraction.get(manifest_key):
            raise PluginError(f"native TripoSR result and manifest disagree on {payload_key}")

    mesh = as_map(run.manifest.get("mesh"), "native TripoSR mesh")
    if mesh.get("coordinateSystem") != "model-x-right-y-up-z-forward":
        raise PluginError("native TripoSR mesh reported an unexpected coordinate system")
    if mesh.get("units") != "normalized-object-space":
        raise PluginError("native TripoSR mesh must report normalized object-space units")
    if mesh.get("inferredUnseenGeometry") is not True:
        raise PluginError("native TripoSR mesh must disclose inferred unseen geometry")
    for count_key in ("vertexCount", "triangleCount"):
        count = mesh.get(count_key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise PluginError(f"native TripoSR mesh has invalid {count_key}")
    for key in ("coordinateSystem", "units", "inferredUnseenGeometry", "vertexCount", "triangleCount", "bounds"):
        if payload.get(key) != mesh.get(key):
            raise PluginError(f"native TripoSR result and manifest disagree on {key}")

    required = {
        "obj": one_native_artifact(run, "obj", "native TripoSR"),
        "ply": one_native_artifact(run, "ply", "native TripoSR"),
        "glb": one_native_artifact(run, "glb", "native TripoSR"),
        "mesh-manifest": one_native_artifact(run, "mesh-manifest", "native TripoSR"),
    }
    manifest_artifacts = as_list(run.manifest.get("artifacts"), "native TripoSR manifest artifacts")
    payload_artifacts = as_list(payload.get("artifacts"), "native TripoSR result artifacts")
    if native_artifact_contract(manifest_artifacts, "native TripoSR manifest") != native_artifact_contract(
        payload_artifacts, "native TripoSR result"
    ):
        raise PluginError("native TripoSR result and manifest artifact contracts disagree")

    mesh_manifest_value = payload.get("meshManifestPath")
    if not isinstance(mesh_manifest_value, str) or not mesh_manifest_value:
        raise PluginError("native TripoSR result is missing meshManifestPath")
    mesh_manifest_path = confined_path(native_output, mesh_manifest_value, "native TripoSR mesh manifest")
    if mesh_manifest_path != required["mesh-manifest"]:
        raise PluginError("native TripoSR result points to a different mesh manifest artifact")
    expected_mesh_manifest_sha = validated_sha256(
        payload.get("meshManifestSHA256"), "native TripoSR result meshManifestSHA256"
    )
    if expected_mesh_manifest_sha != sha256(mesh_manifest_path):
        raise PluginError("native TripoSR mesh manifest checksum mismatch")
    mesh_document = read_json_map(mesh_manifest_path, "native TripoSR mesh manifest")
    if mesh_document.get("schemaVersion") != 1:
        raise PluginError("native TripoSR mesh manifest has an unsupported schemaVersion")
    if mesh_document.get("outputDirectory") != str(native_output.resolve()):
        raise PluginError("native TripoSR mesh manifest outputDirectory is not confined to the native run")
    if mesh_document.get("inputPaths") != [str(source)]:
        raise PluginError("native TripoSR mesh manifest input path does not match the requested image")
    for key in ("coordinateSystem", "units", "inferredUnseenGeometry", "vertexCount", "triangleCount", "bounds"):
        if mesh_document.get(key) != mesh.get(key):
            raise PluginError(f"native TripoSR run and mesh manifests disagree on {key}")
    mesh_model = as_map(mesh_document.get("model"), "native TripoSR mesh model")
    if mesh_model.get("modelID") != "image-3d-triposr" or mesh_model.get("inferenceBackend") != "mere.run-native-mlx":
        raise PluginError("native TripoSR mesh manifest does not identify the native MLX backend")
    if (
        mesh_model.get("upstreamRepository") != checkpoint.get("repository")
        or mesh_model.get("upstreamRevision") != checkpoint.get("revision")
        or mesh_model.get("license") != checkpoint.get("license")
    ):
        raise PluginError("native TripoSR run and mesh manifests disagree on model provenance")
    mesh_artifacts = native_artifact_contract(
        as_list(mesh_document.get("artifacts"), "native TripoSR mesh artifacts"),
        "native TripoSR mesh manifest",
    )
    run_mesh_artifacts = {
        key: value
        for key, value in native_artifact_contract(manifest_artifacts, "native TripoSR run manifest").items()
        if key[0] in {"obj", "ply", "glb"}
    }
    if mesh_artifacts != run_mesh_artifacts:
        raise PluginError("native TripoSR run and mesh manifest artifact contracts disagree")

    delivery = output_dir / "image-to-3d.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-image-to-3d.v2",
        "source": str(source),
        "reconstructionMode": "native-triposr",
        "geometryMode": "native-single-image-object-reconstruction",
        "nativeInference": True,
        "modelID": checkpoint.get("modelID"),
        "checkpoint": checkpoint,
        "nativeManifest": str(run.manifest_path),
        "nativeManifestSha256": sha256(run.manifest_path),
        "meshManifest": str(mesh_manifest_path),
        "meshManifestSha256": sha256(mesh_manifest_path),
        "nativeOutputDirectory": str(native_output.resolve()),
        "coordinateSystem": mesh.get("coordinateSystem"),
        "units": mesh.get("units"),
        "metricGeometry": False,
        "inferredUnseenGeometry": True,
        "extraction": extraction,
        "mesh": mesh,
        "assets": {
            kind: {"path": str(path), "sha256": sha256(path)}
            for kind, path in required.items() if kind != "mesh-manifest"
        },
        "nativeArtifacts": run.artifact_records,
    })
    artifact(manifest, native_output, "directory", "native-triposr-reconstruction")
    artifact(manifest, run.manifest_path, "json", "native-triposr-run-manifest")
    artifact(manifest, mesh_manifest_path, "json", "native-triposr-mesh-manifest")
    for kind in ("obj", "ply", "glb"):
        artifact(manifest, required[kind], "mesh", f"native-triposr-{kind}")
    artifact(manifest, delivery, "json", "image-to-3d-handoff")


def execute_supplied_depth_image_to_3d(manifest: JsonMap, output_dir: pathlib.Path) -> None:
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
        "schemaVersion": "mere.run/vfx-image-to-3d.v2",
        "source": source_label,
        "reconstructionMode": "supplied-depth-2.5d",
        "geometryMode": "supplied-depth-2.5d-fallback",
        "nativeInference": False,
        "metricGeometry": False,
        "depthSemantics": "normalized-display-values-mapped-to-assumed-range",
        "inferredUnseenGeometry": False,
        "fallbackDisclosure": (
            "Legacy camera-local projection from artist-supplied grayscale depth; "
            "this is not native object reconstruction and does not infer occluded geometry."
        ),
        "coordinateSpace": "camera-local-x-right-y-up-z-forward",
        "nearDepth": near_depth,
        "farDepth": far_depth,
        "stride": stride,
        "frames": deliveries,
    })
    artifact(manifest, geometry_dir, "directory", "projected-geometry")
    artifact(manifest, delivery, "json", "image-to-3d-manifest")


def execute_image_to_3d(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    options = options_for(manifest)
    mode = option_string(options, "reconstructionMode", "native-triposr")
    if mode == "native-triposr":
        execute_native_image_to_3d(manifest, output_dir)
        return
    if mode == "supplied-depth-2.5d":
        execute_supplied_depth_image_to_3d(manifest, output_dir)
        return
    raise PluginError(
        "request.options.reconstructionMode must be 'native-triposr' or 'supplied-depth-2.5d'",
        2,
    )


def instantmesh_ordered_views(request: JsonMap) -> list[pathlib.Path]:
    inputs = as_map(request["inputs"], "request.inputs")
    if inputs.get("image") is not None:
        raise PluginError(
            "multiview-image-to-3d never generates views from one image; "
            "provide exactly 4 or 6 paths in request.inputs.images",
            2,
        )
    value = inputs.get("images")
    if not isinstance(value, list):
        raise PluginError(
            "multiview-image-to-3d requires request.inputs.images as an explicitly ordered path array",
            2,
        )
    images = ordered_image_inputs(request)
    if len(images) not in {4, 6}:
        raise PluginError(
            "multiview-image-to-3d requires exactly 4 or 6 ordered user-supplied views; no views are generated",
            2,
        )
    return images


def validated_instantmesh_cameras(
    value: object,
    view_count: int,
    context: str,
    exit_code: int = 1,
) -> list[list[object]]:
    if not isinstance(value, list):
        raise PluginError(f"{context} must be a JSON array", exit_code)
    if len(value) != view_count:
        raise PluginError(f"{context} must contain exactly {view_count} cameras", exit_code)
    cameras: list[list[object]] = []
    for camera_index, raw_camera in enumerate(value):
        if not isinstance(raw_camera, list):
            raise PluginError(f"{context} camera {camera_index} must be a JSON array", exit_code)
        if len(raw_camera) != 16:
            raise PluginError(f"{context} camera {camera_index} must contain 16 values", exit_code)
        if not all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(float(item))
            for item in raw_camera
        ):
            raise PluginError(f"{context} camera {camera_index} must contain only finite numbers", exit_code)
        cameras.append(raw_camera)
    return cameras


def validate_instantmesh_camera_document(
    path: pathlib.Path,
    view_count: int,
) -> list[list[object]]:
    document = read_json_map(path, "InstantMesh camera document")
    if document.get("schemaVersion") != 1:
        raise PluginError("InstantMesh camera document schemaVersion must be 1", 2)
    return validated_instantmesh_cameras(
        document.get("cameras"),
        view_count,
        "InstantMesh camera document",
        exit_code=2,
    )


def validated_instantmesh_checkpoint(run: NativeRun) -> JsonMap:
    checkpoint = as_map(run.manifest.get("checkpoint"), "native InstantMesh checkpoint")
    expected_strings = {
        "modelID": INSTANTMESH_MODEL_ID,
        "repository": INSTANTMESH_REPOSITORY,
        "revision": INSTANTMESH_REVISION,
        "sourceRepository": INSTANTMESH_REPOSITORY,
        "sourceRevision": INSTANTMESH_SOURCE_REVISION,
        "license": INSTANTMESH_LICENSE,
        "format": "verified-converted-safetensors",
    }
    for key, expected in expected_strings.items():
        if checkpoint.get(key) != expected:
            raise PluginError(f"native InstantMesh checkpoint has unexpected {key}")
    if checkpoint.get("weightsByteCount") != INSTANTMESH_WEIGHTS_BYTE_COUNT:
        raise PluginError("native InstantMesh checkpoint has an unexpected converted byte count")
    expected_hashes = {
        "weightsSHA256": INSTANTMESH_WEIGHTS_SHA256,
        "sourceSHA256": INSTANTMESH_SOURCE_SHA256,
        "configurationSHA256": INSTANTMESH_CONFIGURATION_SHA256,
        "sourceManifestSHA256": INSTANTMESH_SOURCE_MANIFEST_SHA256,
    }
    for key, expected in expected_hashes.items():
        if validated_sha256(checkpoint.get(key), f"native InstantMesh checkpoint {key}") != f"sha256:{expected}":
            raise PluginError(f"native InstantMesh checkpoint has unexpected {key}")
    if checkpoint.get("viewGenerationIncluded") is not False:
        raise PluginError("native InstantMesh checkpoint must exclude view generation")
    return checkpoint


def execute_multiview_image_to_3d(manifest: JsonMap, output_dir: pathlib.Path) -> None:
    request = as_map(manifest["request"], "request")
    inputs = as_map(request["inputs"], "request.inputs")
    options = options_for(manifest)
    for key in (
        "generateViews",
        "viewGeneration",
        "zero123PlusPlus",
        "runtimePython",
        "useFlexiCubes",
    ):
        if key in options:
            raise PluginError(
                f"request.options.{key} is outside the reconstruction-only InstantMesh workflow",
                2,
            )
    images = instantmesh_ordered_views(request)

    resolution_value = options.get("resolution", 128)
    if isinstance(resolution_value, bool) or not isinstance(resolution_value, int):
        raise PluginError("request.options.resolution must be an integer from 2 through 256", 2)
    resolution = resolution_value
    if not 2 <= resolution <= 256:
        raise PluginError("request.options.resolution must be from 2 through 256", 2)
    no_vertex_colors_value = options.get("noVertexColors", False)
    if not isinstance(no_vertex_colors_value, bool):
        raise PluginError("request.options.noVertexColors must be a boolean", 2)
    no_vertex_colors = no_vertex_colors_value
    model_value = options.get("model")
    if model_value is not None and (not isinstance(model_value, str) or not model_value):
        raise PluginError("request.options.model must be a managed model id or converted package path", 2)

    camera_path: pathlib.Path | None = None
    requested_cameras: list[list[object]] | None = None
    camera_value = inputs.get("cameras")
    if camera_value is not None:
        if not isinstance(camera_value, str) or not camera_value:
            raise PluginError("request.inputs.cameras must be a local camera JSON path", 2)
        camera_path = input_path(request, "cameras")
        requested_cameras = validate_instantmesh_camera_document(camera_path, len(images))

    native_output = output_dir / "native-instantmesh"
    argv = runtime_command(manifest, "mereRunCommand") + [
        "image",
        "reconstruct-3d-multiview",
    ]
    for image in images:
        argv.extend(["--view", str(image)])
    argv.extend(["--output", str(native_output), "--resolution", str(resolution)])
    if isinstance(model_value, str):
        argv.extend(["--model", model_value])
    if camera_path is not None:
        argv.extend(["--cameras", str(camera_path)])
    if no_vertex_colors:
        argv.append("--no-vertex-colors")
    argv.append("--json")

    payload = run_json_process(argv, "mere.run image reconstruct-3d-multiview")
    run = load_native_run(payload, native_output, "mere.run image reconstruct-3d-multiview")
    if validated_sha256(
        payload.get("manifestSHA256"), "native InstantMesh result manifestSHA256"
    ) != sha256(run.manifest_path):
        raise PluginError("native InstantMesh run manifest checksum mismatch")
    if run.manifest.get("schemaVersion") != 1:
        raise PluginError("native InstantMesh run manifest has an unsupported schemaVersion")
    reported_output = run.manifest.get("outputDirectory")
    if not isinstance(reported_output, str) or pathlib.Path(reported_output).resolve() != native_output.resolve():
        raise PluginError("native InstantMesh run manifest outputDirectory is not confined to the native run")

    checkpoint = validated_instantmesh_checkpoint(run)
    payload_hashes = {
        "checkpointSHA256": checkpoint.get("weightsSHA256"),
        "sourceCheckpointSHA256": checkpoint.get("sourceSHA256"),
        "sourceManifestSHA256": checkpoint.get("sourceManifestSHA256"),
    }
    if payload.get("modelID") != checkpoint.get("modelID"):
        raise PluginError("native InstantMesh result and run manifest modelID disagree")
    if payload.get("checkpointFormat") != checkpoint.get("format"):
        raise PluginError("native InstantMesh result and run manifest checkpoint format disagree")
    for payload_key, expected in payload_hashes.items():
        if validated_sha256(payload.get(payload_key), f"native InstantMesh result {payload_key}") != validated_sha256(
            expected, f"native InstantMesh checkpoint {payload_key}"
        ):
            raise PluginError(f"native InstantMesh result and run manifest disagree on {payload_key}")

    native_input = as_map(run.manifest.get("input"), "native InstantMesh input")
    if native_input.get("viewCount") != len(images) or payload.get("viewCount") != len(images):
        raise PluginError("native InstantMesh view count does not match the ordered request")
    if native_input.get("userSuppliedViews") is not True or payload.get("userSuppliedViews") is not True:
        raise PluginError("native InstantMesh must identify every view as user supplied")
    ordered_views = as_list(native_input.get("orderedViews"), "native InstantMesh ordered views")
    if len(ordered_views) != len(images):
        raise PluginError("native InstantMesh run manifest has the wrong ordered view count")
    payload_dimensions = as_list(payload.get("sourceDimensions"), "native InstantMesh source dimensions")
    if len(payload_dimensions) != len(images):
        raise PluginError("native InstantMesh result has the wrong source-dimension count")
    for index, source in enumerate(images):
        item = as_map(ordered_views[index], f"native InstantMesh ordered view {index}")
        dimensions = as_map(payload_dimensions[index], f"native InstantMesh source dimensions {index}")
        if item.get("index") != index or item.get("path") != str(source):
            raise PluginError("native InstantMesh changed the requested view order")
        for key in ("sourceWidth", "sourceHeight", "preparedWidth", "preparedHeight"):
            value = item.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PluginError(f"native InstantMesh ordered view {index} has invalid {key}")
        if dimensions.get("width") != item.get("sourceWidth") or dimensions.get("height") != item.get(
            "sourceHeight"
        ):
            raise PluginError(f"native InstantMesh source dimensions disagree for view {index}")

    native_cameras = validated_instantmesh_cameras(
        native_input.get("cameras"),
        len(images),
        "native InstantMesh input cameras",
    )
    if requested_cameras is not None and native_cameras != requested_cameras:
        raise PluginError("native InstantMesh cameras do not exactly match the supplied camera document")

    expected_official_rig = camera_path is None
    expected_camera_rig = (
        "official-deterministic-conditioning-rig" if expected_official_rig else "supplied-c2w-intrinsics"
    )
    if native_input.get("cameraConditioning") != expected_camera_rig:
        raise PluginError("native InstantMesh camera rig does not match the request")
    if payload.get("usedOfficialCameraRig") is not expected_official_rig:
        raise PluginError("native InstantMesh result and request disagree on camera rig")

    boundary = as_map(run.manifest.get("boundary"), "native InstantMesh boundary")
    exclusion_fields = (
        "viewGenerationIncluded",
        "zero123PlusPlusIncluded",
        "runtimePython",
        "proprietaryFlexiCubesIncluded",
    )
    for field in exclusion_fields:
        if boundary.get(field) is not False or payload.get(field) is not False:
            raise PluginError(f"native InstantMesh reconstruction boundary must report {field}=false")
    if payload.get("topologyMatchesUpstreamFlexiCubes") is not False:
        raise PluginError("native InstantMesh must not claim topology parity with proprietary FlexiCubes")

    extraction = as_map(run.manifest.get("extraction"), "native InstantMesh extraction")
    expected_extraction = {
        "resolution": resolution,
        "includesVertexColors": not no_vertex_colors,
        "algorithm": INSTANTMESH_EXTRACTION_ALGORITHM,
        "topologyCompatibility": INSTANTMESH_TOPOLOGY_COMPATIBILITY,
    }
    for key, expected in expected_extraction.items():
        if extraction.get(key) != expected:
            raise PluginError(f"native InstantMesh extraction has unexpected {key}")
    upstream_empty_field_repair = extraction.get("upstreamEmptyFieldRepairApplied")
    if not isinstance(upstream_empty_field_repair, bool):
        raise PluginError(
            "native InstantMesh extraction upstreamEmptyFieldRepairApplied must be a boolean"
        )
    payload_upstream_empty_field_repair = payload.get("upstreamEmptyFieldRepairApplied")
    if not isinstance(payload_upstream_empty_field_repair, bool):
        raise PluginError(
            "native InstantMesh result upstreamEmptyFieldRepairApplied must be a boolean"
        )
    if payload_upstream_empty_field_repair is not upstream_empty_field_repair:
        raise PluginError(
            "native InstantMesh result and extraction disagree on upstreamEmptyFieldRepairApplied"
        )
    for payload_key, expected in (
        ("extractionResolution", resolution),
        ("includesVertexColors", not no_vertex_colors),
        ("meshExtractionAlgorithm", INSTANTMESH_EXTRACTION_ALGORITHM),
    ):
        if payload.get(payload_key) != expected:
            raise PluginError(f"native InstantMesh result has unexpected {payload_key}")

    mesh = as_map(run.manifest.get("mesh"), "native InstantMesh mesh")
    if mesh.get("coordinateSystem") != "model-x-right-y-up-z-forward":
        raise PluginError("native InstantMesh mesh reported an unexpected coordinate system")
    if mesh.get("units") != "normalized-object-space":
        raise PluginError("native InstantMesh mesh must report normalized object-space units")
    if mesh.get("inferredUnseenGeometry") is not True:
        raise PluginError("native InstantMesh mesh must disclose inferred unseen geometry")
    for count_key in ("vertexCount", "triangleCount"):
        count = mesh.get(count_key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise PluginError(f"native InstantMesh mesh has invalid {count_key}")
    for key in ("coordinateSystem", "units", "inferredUnseenGeometry", "vertexCount", "triangleCount", "bounds"):
        if payload.get(key) != mesh.get(key):
            raise PluginError(f"native InstantMesh result and run manifest disagree on {key}")

    required = {
        "obj": one_native_artifact(run, "obj", "native InstantMesh"),
        "ply": one_native_artifact(run, "ply", "native InstantMesh"),
        "glb": one_native_artifact(run, "glb", "native InstantMesh"),
        "mesh-manifest": one_native_artifact(run, "mesh-manifest", "native InstantMesh"),
    }
    manifest_artifacts = as_list(run.manifest.get("artifacts"), "native InstantMesh run artifacts")
    payload_artifacts = as_list(payload.get("artifacts"), "native InstantMesh result artifacts")
    if native_artifact_contract(manifest_artifacts, "native InstantMesh run manifest") != native_artifact_contract(
        payload_artifacts, "native InstantMesh result"
    ):
        raise PluginError("native InstantMesh result and run manifest artifact contracts disagree")

    mesh_manifest_value = payload.get("meshManifestPath")
    if not isinstance(mesh_manifest_value, str) or not mesh_manifest_value:
        raise PluginError("native InstantMesh result is missing meshManifestPath")
    mesh_manifest_path = confined_path(native_output, mesh_manifest_value, "native InstantMesh mesh manifest")
    if mesh_manifest_path != required["mesh-manifest"]:
        raise PluginError("native InstantMesh result points to a different mesh manifest artifact")
    if validated_sha256(
        payload.get("meshManifestSHA256"), "native InstantMesh result meshManifestSHA256"
    ) != sha256(mesh_manifest_path):
        raise PluginError("native InstantMesh mesh manifest checksum mismatch")
    mesh_document = read_json_map(mesh_manifest_path, "native InstantMesh mesh manifest")
    if mesh_document.get("schemaVersion") != 1:
        raise PluginError("native InstantMesh mesh manifest has an unsupported schemaVersion")
    if mesh_document.get("outputDirectory") != str(native_output.resolve()):
        raise PluginError("native InstantMesh mesh manifest outputDirectory is not confined to the native run")
    if mesh_document.get("inputPaths") != [str(path) for path in images]:
        raise PluginError("native InstantMesh mesh manifest changed the requested view order")
    for key in ("coordinateSystem", "units", "inferredUnseenGeometry", "vertexCount", "triangleCount", "bounds"):
        if mesh_document.get(key) != mesh.get(key):
            raise PluginError(f"native InstantMesh run and mesh manifests disagree on {key}")
    mesh_model = as_map(mesh_document.get("model"), "native InstantMesh mesh model")
    expected_mesh_model = {
        "modelID": checkpoint.get("modelID"),
        "upstreamRepository": checkpoint.get("repository"),
        "upstreamRevision": checkpoint.get("revision"),
        "license": checkpoint.get("license"),
        "weightsSHA256": checkpoint.get("weightsSHA256"),
        "inferenceBackend": "mere.run-native-mlx",
    }
    for key, expected in expected_mesh_model.items():
        if mesh_model.get(key) != expected:
            raise PluginError(f"native InstantMesh mesh manifest has unexpected model {key}")
    mesh_artifacts = native_artifact_contract(
        as_list(mesh_document.get("artifacts"), "native InstantMesh mesh artifacts"),
        "native InstantMesh mesh manifest",
    )
    run_mesh_artifacts = {
        key: value
        for key, value in native_artifact_contract(
            manifest_artifacts, "native InstantMesh run manifest"
        ).items()
        if key[0] in {"obj", "ply", "glb"}
    }
    if mesh_artifacts != run_mesh_artifacts:
        raise PluginError("native InstantMesh run and mesh manifest artifact contracts disagree")

    delivery = output_dir / "multiview-image-to-3d.json"
    write_json(delivery, {
        "schemaVersion": "mere.run/vfx-multiview-image-to-3d.v1",
        "orderedViews": [str(path) for path in images],
        "reconstructionMode": "native-instantmesh-reconstruction-only",
        "geometryMode": "native-multiview-object-reconstruction",
        "nativeInference": True,
        "runtimePython": False,
        "modelID": checkpoint.get("modelID"),
        "checkpoint": checkpoint,
        "nativeManifest": str(run.manifest_path),
        "nativeManifestSha256": sha256(run.manifest_path),
        "meshManifest": str(mesh_manifest_path),
        "meshManifestSha256": sha256(mesh_manifest_path),
        "nativeOutputDirectory": str(native_output.resolve()),
        "viewCount": len(images),
        "userSuppliedViews": True,
        "viewGenerationIncluded": False,
        "zero123PlusPlusIncluded": False,
        "proprietaryFlexiCubesIncluded": False,
        "cameraRig": expected_camera_rig,
        "usedOfficialCameraRig": expected_official_rig,
        "suppliedCameraDocument": str(camera_path) if camera_path else None,
        "suppliedCameraDocumentSha256": sha256(camera_path) if camera_path else None,
        "upstreamEmptyFieldRepairApplied": upstream_empty_field_repair,
        "coordinateSystem": mesh.get("coordinateSystem"),
        "units": mesh.get("units"),
        "metricGeometry": False,
        "inferredUnseenGeometry": True,
        "topologyMatchesUpstreamFlexiCubes": False,
        "extraction": extraction,
        "mesh": mesh,
        "assets": {
            kind: {"path": str(path), "sha256": sha256(path)}
            for kind, path in required.items() if kind != "mesh-manifest"
        },
        "nativeArtifacts": run.artifact_records,
    })
    artifact(manifest, native_output, "directory", "native-instantmesh-reconstruction")
    artifact(manifest, run.manifest_path, "json", "native-instantmesh-run-manifest")
    artifact(manifest, mesh_manifest_path, "json", "native-instantmesh-mesh-manifest")
    for kind in ("obj", "ply", "glb"):
        artifact(manifest, required[kind], "mesh", f"native-instantmesh-{kind}")
    artifact(manifest, delivery, "json", "multiview-image-to-3d-handoff")


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
    "video-depth": execute_video_depth,
    "multiview-geometry": execute_multiview_geometry,
    "image-to-3d": execute_image_to_3d,
    "multiview-image-to-3d": execute_multiview_image_to_3d,
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

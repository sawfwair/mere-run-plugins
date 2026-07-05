from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
from typing import cast

from PIL import Image, ImageChops, ImageFilter, ImageOps

from . import __version__

PLUGIN_NAME = "mere-image-tools"
DEFAULT_MERE_RUN = "mere.run"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
JsonMap = dict[str, object]


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


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


def as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    raise PluginError(f"manifest field is not an object: {label}", 1)


def string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def number_value(value: object, default: float = 0) -> float:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def split_command(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise PluginError(f"invalid command: {exc}", 2) from None
    if not parts:
        raise PluginError("command is empty", 2)
    return parts


def command_available(command: list[str]) -> bool:
    executable = command[0]
    if pathlib.Path(executable).expanduser().is_file():
        return True
    return shutil.which(executable) is not None


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise PluginError(
            "--run-id must start with a letter or digit and contain only letters, digits, '.', '_', or '-'",
            2,
        )


def default_run_id() -> str:
    return "image-tools-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def default_manifest_path(output: pathlib.Path) -> pathlib.Path:
    return output.with_suffix(".run.json")


def default_mask_path(output: pathlib.Path) -> pathlib.Path:
    return output.with_name(f"{output.stem}-mask.png")


def default_work_dir(output: pathlib.Path) -> pathlib.Path:
    return output.with_suffix(".sam31")


def ensure_input_image(path: pathlib.Path) -> None:
    if not path.is_file():
        raise PluginError(f"input image does not exist: {path}", 2)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise PluginError(f"unsupported image extension: {path.suffix}", 2)


def plugin_manifest() -> JsonMap:
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": "mere-image-tools",
        "description": "Local image-production tools for mere.run workflows.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-image-tools",
        "commands": [
            {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
            {"name": "doctor", "description": "Check local readiness and mere.run availability.", "stdout": "json"},
            {"name": "plan", "description": "Create a knockout run manifest without executing mere.run.", "stdout": "json"},
            {"name": "run", "description": "Execute a planned image-tools run manifest.", "stdout": "json"},
            {"name": "resume", "description": "Inspect a recorded image-tools run manifest.", "stdout": "json"},
            {"name": "cleanup", "description": "Mark a local run manifest as having no remote cleanup.", "stdout": "json"},
            {"name": "knockout", "description": "Plan and run a subject knockout in one command.", "stdout": "json"},
        ],
        "capabilities": ["image-tools", "knockout", "segmentation", "alpha-mask", "sam31"],
        "stdout": {
            "machineReadableByDefault": True,
            "diagnostics": "stderr",
        },
        "security": {
            "usesUserCredentials": False,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def make_knockout_manifest(args: argparse.Namespace) -> JsonMap:
    ensure_input_image(args.input)
    mere_run_command = split_command(args.mere_run_command)
    created = now_iso()
    work_dir = args.work_dir or default_work_dir(args.output)
    segmented_image = work_dir / "segmented.png"
    segmentation_json = work_dir / "segmented.json"
    mask_dir = work_dir / "masks"
    command = [
        "mere-image-tools",
        "knockout",
        "--input",
        str(args.input),
        "--output",
        str(args.output),
        "--mask-output",
        str(args.mask_output),
        "--model",
        args.model,
        "--mere-run-command",
        args.mere_run_command,
        "--mode",
        args.mode,
        "--threshold",
        str(args.threshold),
        "--resolution",
        str(args.resolution),
        "--feather-radius",
        str(args.feather_radius),
    ]
    if args.work_dir is not None:
        command.extend(["--work-dir", str(work_dir)])
    for prompt in args.prompt:
        command.extend(["--prompt", prompt])
    for box in args.box:
        command.extend(["--box", box])
    for point in args.point:
        command.extend(["--point", point])
    return {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {"id": "image-knockout", "family": "image-tool", "title": "Subject knockout"},
        "status": "planned",
        "createdAt": created,
        "updatedAt": created,
        "dataset": {
            "path": str(args.input.parent),
            "pairCount": 1,
            "sha256": file_sha256(args.input),
        },
        "command": command,
        "local": {
            "input": str(args.input),
            "output": str(args.output),
            "maskOutput": str(args.mask_output),
            "runManifest": str(args.manifest),
            "workDirectory": str(work_dir),
        },
        "tool": {
            "name": "knockout",
            "backend": "mere.run/vision-segment",
            "mereRunCommand": mere_run_command,
            "model": args.model,
            "mode": args.mode,
            "prompts": args.prompt,
            "boxes": args.box,
            "points": args.point,
            "threshold": args.threshold,
            "resolution": args.resolution,
            "featherRadius": args.feather_radius,
        },
        "artifacts": {
            "localDirectory": str(args.output.parent),
            "image": str(args.output),
            "mask": str(args.mask_output),
            "segmentedImage": str(segmented_image),
            "segmentationJson": str(segmentation_json),
            "maskDirectory": str(mask_dir),
            "selectedSourceMask": None,
            "selectedSourceMasks": [],
            "sha256": None,
            "maskSha256": None,
        },
        "cleanup": {"default": "none", "status": "not-started"},
    }


def update_manifest(path: pathlib.Path, manifest: JsonMap, **updates: object) -> None:
    manifest.update(updates)
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def segment_argv(manifest: JsonMap) -> list[str]:
    tool = as_map(manifest["tool"], "tool")
    local = as_map(manifest["local"], "local")
    artifacts = as_map(manifest["artifacts"], "artifacts")
    mere_run_command = tool["mereRunCommand"]
    if not isinstance(mere_run_command, list) or not all(isinstance(item, str) for item in mere_run_command):
        raise PluginError("manifest tool.mereRunCommand must be a string list", 1)
    argv = list(mere_run_command)
    argv.extend([
        "vision",
        "segment",
        str(local["input"]),
        "--model",
        str(tool["model"]),
        "--output",
        str(artifacts["segmentedImage"]),
        "--json-output",
        str(artifacts["segmentationJson"]),
        "--mask-output-dir",
        str(artifacts["maskDirectory"]),
        "--threshold",
        str(tool["threshold"]),
        "--resolution",
        str(tool["resolution"]),
    ])
    for prompt in string_items(tool.get("prompts")):
        argv.extend(["--prompt", prompt])
    for box in string_items(tool.get("boxes")):
        argv.extend(["--box", box])
    for point in string_items(tool.get("points")):
        argv.extend(["--point", point])
    return argv


def run_segment(manifest: JsonMap) -> None:
    argv = segment_argv(manifest)
    if not command_available(argv):
        raise PluginError(f"mere.run command not found: {argv[0]}. Install mere.run or pass --mere-run-command.", 3)
    artifacts = as_map(manifest["artifacts"], "artifacts")
    pathlib.Path(str(artifacts["maskDirectory"])).mkdir(parents=True, exist_ok=True)
    eprint("$ " + shlex.join(argv))
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        eprint(line.rstrip("\n"))
    returncode = process.wait()
    if returncode != 0:
        raise PluginError(f"mere.run vision segment failed with exit {returncode}", 1)


def selected_detections(manifest: JsonMap) -> list[JsonMap]:
    artifacts = as_map(manifest["artifacts"], "artifacts")
    path = pathlib.Path(str(artifacts["segmentationJson"]))
    try:
        payload = json.loads(path.read_text())
    except OSError as exc:
        raise PluginError(f"could not read segmentation JSON: {path}: {exc}", 1) from None
    payload_map = as_map(payload, "segmentation payload")
    detections_raw = payload_map.get("detections")
    detections: list[JsonMap] = []
    if isinstance(detections_raw, list):
        detections = [cast(JsonMap, item) for item in detections_raw if isinstance(item, dict) and item.get("maskPath")]
    if not detections:
        raise PluginError("mere.run segmentation produced no mask artifacts", 1)
    by_label: dict[str, JsonMap] = {}
    for item in detections:
        label = str(item.get("label") or "default")
        current = by_label.get(label)
        if current is None or detection_rank(item) > detection_rank(current):
            by_label[label] = item
    return sorted(by_label.values(), key=detection_rank, reverse=True)


def detection_rank(item: JsonMap) -> tuple[float, int]:
    return (number_value(item.get("score")), int(number_value(item.get("maskAreaPixels"))))


def normalize_mask(mask_path: pathlib.Path) -> Image.Image:
    raw = Image.open(mask_path)
    if raw.mode in {"RGBA", "LA"}:
        alpha = raw.getchannel("A")
        mask_source = alpha if alpha.getextrema() != (255, 255) else ImageOps.grayscale(raw.convert("RGB"))
    else:
        mask_source = ImageOps.grayscale(raw.convert("RGB"))
    mask = mask_source.point(lambda p: 255 if p > 16 else 0)
    width, height = mask.size
    histogram = mask.histogram()
    foreground = sum(histogram[1:])
    if foreground > int(width * height * 0.65):
        mask = mask.point(lambda p: 0 if p else 255)
    return keep_significant_components(mask)


def keep_significant_components(mask: Image.Image) -> Image.Image:
    mask = mask.convert("L").point(lambda p: 255 if p > 0 else 0)
    width, height = mask.size
    pixels = mask.load()
    if pixels is None:
        raise PluginError("could not read mask pixels", 1)
    visited = bytearray(width * height)
    components: list[list[tuple[int, int]]] = []
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if visited[index] or pixels[x, y] == 0:
                continue
            stack = [(x, y)]
            visited[index] = 1
            component: list[tuple[int, int]] = []
            while stack:
                cx, cy = stack.pop()
                component.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    next_index = ny * width + nx
                    if visited[next_index] or pixels[nx, ny] == 0:
                        continue
                    visited[next_index] = 1
                    stack.append((nx, ny))
            components.append(component)
    if not components:
        return Image.new("L", (width, height), 0)
    largest = max(len(component) for component in components)
    minimum = max(32, int(largest * 0.02))
    clean = Image.new("L", (width, height), 0)
    clean_pixels = clean.load()
    if clean_pixels is None:
        raise PluginError("could not write mask pixels", 1)
    for component in components:
        if len(component) < minimum:
            continue
        for x, y in component:
            clean_pixels[x, y] = 255
    return clean


def composite_knockout(manifest: JsonMap) -> None:
    detections = selected_detections(manifest)
    mask_paths = [pathlib.Path(str(detection["maskPath"])) for detection in detections]
    mask = normalize_mask(mask_paths[0])
    for mask_path in mask_paths[1:]:
        next_mask = normalize_mask(mask_path)
        if next_mask.size != mask.size:
            next_mask = next_mask.resize(mask.size)
        mask = ImageChops.lighter(mask, next_mask)
    tool = as_map(manifest["tool"], "tool")
    local = as_map(manifest["local"], "local")
    artifacts = as_map(manifest["artifacts"], "artifacts")
    radius = number_value(tool.get("featherRadius"))
    alpha = mask.filter(ImageFilter.GaussianBlur(radius=radius)) if radius > 0 else mask
    image = Image.open(str(local["input"])).convert("RGBA")
    if alpha.size != image.size:
        alpha = alpha.resize(image.size)
        mask = mask.resize(image.size)
    output = pathlib.Path(str(local["output"]))
    mask_output = pathlib.Path(str(local["maskOutput"]))
    result = image.copy()
    result.putalpha(alpha)
    result.save(output)
    mask.save(mask_output)
    artifacts["selectedSourceMask"] = str(mask_paths[0])
    artifacts["selectedSourceMasks"] = [str(mask_path) for mask_path in mask_paths]


def execute_manifest(manifest_path: pathlib.Path, manifest: JsonMap) -> JsonMap:
    local = as_map(manifest["local"], "local")
    artifacts = as_map(manifest["artifacts"], "artifacts")
    output = pathlib.Path(str(local["output"]))
    mask = pathlib.Path(str(local["maskOutput"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    mask.parent.mkdir(parents=True, exist_ok=True)
    update_manifest(manifest_path, manifest, status="running")
    try:
        run_segment(manifest)
        composite_knockout(manifest)
        if not output.is_file():
            raise PluginError(f"knockout did not write output: {output}", 1)
        if not mask.is_file():
            raise PluginError(f"knockout did not write mask output: {mask}", 1)
        artifacts["sha256"] = file_sha256(output)
        artifacts["maskSha256"] = file_sha256(mask)
        update_manifest(manifest_path, manifest, status="succeeded")
    except Exception as exc:
        manifest["error"] = str(exc)
        update_manifest(manifest_path, manifest, status="failed")
        raise
    return manifest


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    mere_run_command = split_command(args.mere_run_command)
    checks = [
        {"name": "python", "ok": True, "detail": sys.version.split()[0]},
        {"name": "mere.run", "ok": command_available(mere_run_command), "detail": shlex.join(mere_run_command)},
    ]
    ok = all(item["ok"] for item in checks)
    print_json({"ok": ok, "checks": checks})
    return 0 if ok else 3


def command_plan(args: argparse.Namespace) -> int:
    manifest = make_knockout_manifest(args)
    write_json(args.manifest, manifest)
    print_json(manifest)
    return 0


def command_run(args: argparse.Namespace) -> int:
    manifest_path = args.run_manifest
    manifest = json.loads(manifest_path.read_text())
    if args.dry_run:
        print_json(manifest)
        return 0
    manifest = execute_manifest(manifest_path, manifest)
    print_json(manifest)
    return 0


def command_knockout(args: argparse.Namespace) -> int:
    manifest = make_knockout_manifest(args)
    write_json(args.manifest, manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    manifest = execute_manifest(args.manifest, manifest)
    print_json(manifest)
    return 0


def command_resume(args: argparse.Namespace) -> int:
    manifest = json.loads(args.run_manifest.read_text())
    print_json({
        "runId": manifest.get("runId"),
        "status": manifest.get("status"),
        "tool": manifest.get("tool"),
        "artifacts": manifest.get("artifacts"),
        "cleanup": manifest.get("cleanup"),
    })
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    manifest_path = args.run_manifest
    manifest = json.loads(manifest_path.read_text())
    cleanup = manifest.setdefault("cleanup", {"default": "none", "status": "not-started"})
    cleanup["status"] = "skipped"
    cleanup["reason"] = "local image-tools runs do not create remote resources"
    update_manifest(manifest_path, manifest)
    print_json(manifest)
    return 0


def add_knockout_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, type=pathlib.Path, help="Input image.")
    parser.add_argument("--output", required=True, type=pathlib.Path, help="Transparent PNG output.")
    parser.add_argument("--mask-output", type=pathlib.Path, help="Grayscale alpha mask output.")
    parser.add_argument("--manifest", type=pathlib.Path, help="Run manifest path. Defaults beside --output.")
    parser.add_argument("--work-dir", type=pathlib.Path, help="Directory for SAM 3.1 intermediate artifacts.")
    parser.add_argument("--model", default="vision-segment-sam31", help="mere.run vision segment model id or local root.")
    parser.add_argument("--mere-run-command", default="", help="mere.run executable command.")
    parser.add_argument("--mode", default="subject", choices=["subject", "foreground"])
    parser.add_argument("--prompt", action="append", default=[], help="Text prompt passed to mere.run vision segment.")
    parser.add_argument("--box", action="append", default=[], help="Box prompt passed to mere.run vision segment.")
    parser.add_argument("--point", action="append", default=[], help="Point prompt passed to mere.run vision segment.")
    parser.add_argument("--threshold", type=float, default=0.05)
    parser.add_argument("--resolution", type=int, default=1008)
    parser.add_argument("--feather-radius", type=float, default=0.7)
    parser.add_argument("--run-id", default=default_run_id())


def normalize_common_args(args: argparse.Namespace) -> argparse.Namespace:
    if hasattr(args, "run_id"):
        validate_run_id(args.run_id)
    if hasattr(args, "mere_run_command") and not args.mere_run_command:
        args.mere_run_command = os.environ.get("MERE_IMAGE_TOOLS_MERE_RUN") or DEFAULT_MERE_RUN
    if hasattr(args, "prompt") and not args.prompt and not getattr(args, "box", None) and not getattr(args, "point", None):
        args.prompt = ["subject"]
    for name in ("input", "output", "mask_output", "manifest", "run_manifest", "work_dir"):
        if hasattr(args, name):
            value = getattr(args, name)
            if value is not None:
                setattr(args, name, value.expanduser().resolve())
    if hasattr(args, "output"):
        if getattr(args, "mask_output", None) is None:
            args.mask_output = default_mask_path(args.output).resolve()
        if getattr(args, "manifest", None) is None:
            args.manifest = default_manifest_path(args.output).resolve()
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mere-image-tools")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check local readiness.")
    doctor.add_argument("--mere-run-command", default="")
    doctor.set_defaults(func=command_doctor)

    plan = sub.add_parser("plan", help="Create a knockout plan.")
    add_knockout_args(plan)
    plan.set_defaults(func=command_plan)

    run = sub.add_parser("run", help="Execute a planned image-tools run manifest.")
    run.add_argument("run_manifest", type=pathlib.Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run)

    resume = sub.add_parser("resume", help="Inspect a run manifest.")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.set_defaults(func=command_resume)

    cleanup = sub.add_parser("cleanup", help="Mark local cleanup as skipped.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=command_cleanup)

    knockout = sub.add_parser("knockout", help="Plan and run a subject knockout.")
    add_knockout_args(knockout)
    knockout.add_argument("--dry-run", action="store_true")
    knockout.set_defaults(func=command_knockout)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args = normalize_common_args(args)
        return int(args.func(args))
    except PluginError as exc:
        eprint(f"Error: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        eprint("Interrupted.")
        return 130
    except Exception as exc:
        eprint(f"Unexpected error: {exc}")
        return 1

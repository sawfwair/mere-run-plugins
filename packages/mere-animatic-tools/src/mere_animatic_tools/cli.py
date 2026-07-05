from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, cast

import PIL
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import __version__

JsonMap = dict[str, object]
JsonList = list[object]

PLUGIN_NAME = "mere-animatic-tools"
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
    capabilities: list[str]
    artifact_prefix: str


TOOLS: dict[str, ToolSpec] = {
    "character-knockout": ToolSpec(
        "character-knockout",
        "Character Knockout",
        "Create transparent character cutouts and alpha masks for compositing.",
        ["animatic", "character-knockout", "knockout", "alpha-mask", "production-art"],
        "character",
    ),
    "reference-pack": ToolSpec(
        "reference-pack",
        "Reference Pack",
        "Assemble visual references, contact sheets, and a structured reference index.",
        ["animatic", "reference-pack", "continuity", "production-art"],
        "reference",
    ),
    "continuity-check": ToolSpec(
        "continuity-check",
        "Continuity Check",
        "Compare scene notes and references for visible continuity risks.",
        ["animatic", "continuity-check", "qa", "script"],
        "continuity",
    ),
    "shot-kit": ToolSpec(
        "shot-kit",
        "Shot Kit",
        "Generate scene shot lists, coverage notes, and frame setup guidance.",
        ["animatic", "shot-kit", "storyboard", "planning"],
        "shot-kit",
    ),
    "storyboard-repair": ToolSpec(
        "storyboard-repair",
        "Storyboard Repair",
        "Identify storyboard gaps and create repair notes for missing transitions.",
        ["animatic", "storyboard-repair", "storyboard", "qa"],
        "storyboard-repair",
    ),
    "edit-doctor": ToolSpec(
        "edit-doctor",
        "Edit Doctor",
        "Diagnose edit pacing, scene order, and missing bridge beats.",
        ["animatic", "edit-doctor", "editing", "qa"],
        "edit-doctor",
    ),
    "actor-voice-kit": ToolSpec(
        "actor-voice-kit",
        "Actor Voice Kit",
        "Build voice direction, sides, and line read notes for a character.",
        ["animatic", "actor-voice-kit", "voice", "script"],
        "voice-kit",
    ),
    "location-plates": ToolSpec(
        "location-plates",
        "Location Plates",
        "Prepare plate notes, coverage gaps, and location reference contact sheets.",
        ["animatic", "location-plates", "location", "production-art"],
        "location",
    ),
    "style-lock": ToolSpec(
        "style-lock",
        "Style Lock",
        "Extract a style bible seed, palette swatches, and consistency rules.",
        ["animatic", "style-lock", "style", "continuity"],
        "style-lock",
    ),
    "delivery-prep": ToolSpec(
        "delivery-prep",
        "Delivery Prep",
        "Create final delivery manifests, issue lists, and review checklists.",
        ["animatic", "delivery-prep", "delivery", "qa"],
        "delivery",
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


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).strip() + "\n")


def as_map(value: object, context: str) -> JsonMap:
    if not isinstance(value, dict):
        raise PluginError(f"{context} must be a JSON object", 2)
    return cast(JsonMap, value)


def as_list(value: object, context: str) -> JsonList:
    if not isinstance(value, list):
        raise PluginError(f"{context} must be a JSON array", 2)
    return cast(JsonList, value)


def string_field(mapping: JsonMap, key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise PluginError(f"{context}.{key} must be a string", 2)
    return value


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise PluginError(
            "--run-id must start with a letter or digit and contain only letters, digits, '.', '_', or '-'",
            2,
        )


def default_run_id() -> str:
    return "animatic-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def load_json_file(path: pathlib.Path) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), f"JSON file {path}")
    except json.JSONDecodeError as exc:
        raise PluginError(f"invalid JSON in {path}: {exc}", 2) from None


def load_request(args: argparse.Namespace) -> JsonMap:
    if args.request_json:
        return load_json_file(args.request_json)
    return {}


def plugin_manifest() -> JsonMap:
    commands = [
        {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
        {"name": "doctor", "description": "Check local readiness.", "stdout": "json"},
        {"name": "plan", "description": "Write a run manifest without executing.", "stdout": "json"},
        {"name": "run", "description": "Execute a planned animatic tool run.", "stdout": "json"},
        {"name": "resume", "description": "Inspect a recorded animatic run manifest.", "stdout": "json"},
        {"name": "cleanup", "description": "Mark local cleanup as skipped.", "stdout": "json"},
    ]
    commands.extend(
        {"name": spec.name, "description": spec.description, "stdout": "json"}
        for spec in TOOLS.values()
    )
    capabilities = sorted({capability for spec in TOOLS.values() for capability in spec.capabilities})
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": "mere-animatic-tools",
        "description": "Local Animatic production tools for relay-connected mere.run nodes.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-animatic-tools",
        "commands": commands,
        "capabilities": capabilities,
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


def request_inputs(request: JsonMap) -> JsonMap:
    inputs = request.get("inputs")
    return as_map(inputs, "request.inputs") if isinstance(inputs, dict) else {}


def request_options(request: JsonMap) -> JsonMap:
    options = request.get("options")
    return as_map(options, "request.options") if isinstance(options, dict) else {}


def normalize_assets(request: JsonMap) -> list[JsonMap]:
    inputs = request_inputs(request)
    raw_assets = inputs.get("assets") or request.get("assets") or []
    if not isinstance(raw_assets, list):
        return []
    assets: list[JsonMap] = []
    for index, item in enumerate(raw_assets, start=1):
        if isinstance(item, str):
            assets.append({"name": f"asset-{index}", "url": item})
        elif isinstance(item, dict):
            asset = as_map(item, "request asset").copy()
            asset.setdefault("name", f"asset-{index}")
            assets.append(asset)
    for key in ("source_image_url", "input_image_url", "image_url"):
        value = inputs.get(key) or request.get(key)
        if isinstance(value, str) and value:
            assets.insert(0, {"name": key.replace("_url", ""), "url": value})
            break
    refs = inputs.get("reference_image_urls") or request.get("reference_image_urls") or []
    if isinstance(refs, list):
        for index, value in enumerate(refs, start=1):
            if isinstance(value, str) and value:
                assets.append({"name": f"reference-{index}", "url": value})
    return assets


def safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return stem[:80] or "asset"


def extension_from_url(url: str, default: str = ".png") -> str:
    suffix = pathlib.Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return suffix
    return default


def download_assets(request: JsonMap, output_dir: pathlib.Path) -> list[pathlib.Path]:  # pragma: no cover
    downloaded: list[pathlib.Path] = []
    asset_dir = output_dir / "inputs"
    for index, asset in enumerate(normalize_assets(request), start=1):
        url = asset.get("url")
        path_value = asset.get("path")
        name = safe_stem(str(asset.get("name") or f"asset-{index}"))
        if isinstance(path_value, str) and path_value:
            path = pathlib.Path(path_value).expanduser().resolve()
            if path.is_file():
                downloaded.append(path)
            continue
        if not isinstance(url, str) or not url:
            continue
        suffix = extension_from_url(url)
        target = asset_dir / f"{index:02d}-{name}{suffix}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=30) as response:
                target.write_bytes(response.read())
            downloaded.append(target)
        except Exception as exc:
            eprint(f"Skipping asset download {url}: {exc}")
    return downloaded


def is_image(path: pathlib.Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def image_files(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    return [path for path in paths if is_image(path)]


def make_manifest(spec: ToolSpec, args: argparse.Namespace, request: JsonMap) -> JsonMap:
    created = now_iso()
    manifest_path = args.manifest or (args.output_dir / "run.json")
    request_digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {
            "id": f"animatic-{spec.name}",
            "family": "animatic-production",
            "title": spec.title,
        },
        "status": "planned",
        "createdAt": created,
        "updatedAt": created,
        "dataset": {
            "path": str(args.output_dir),
            "pairCount": max(1, len(normalize_assets(request))),
            "sha256": "sha256:" + request_digest,
        },
        "command": command_for_manifest(spec, args),
        "local": {
            "outputDirectory": str(args.output_dir),
            "runManifest": str(manifest_path),
        },
        "tool": {
            "name": spec.name,
            "title": spec.title,
            "backend": "local-animatic",
            "capabilities": spec.capabilities,
        },
        "request": request,
        "artifacts": {
            "localDirectory": str(args.output_dir),
            "files": [],
            "items": [],
            "sha256": {},
        },
        "cleanup": {"default": "none", "status": "not-started"},
    }


def command_for_manifest(spec: ToolSpec, args: argparse.Namespace) -> list[str]:
    command = [
        "mere-animatic-tools",
        spec.name,
        "--output-dir",
        str(args.output_dir),
        "--run-id",
        args.run_id,
    ]
    if args.request_json:
        command.extend(["--request-json", str(args.request_json)])
    if args.manifest:
        command.extend(["--manifest", str(args.manifest)])
    return command


def artifact_item(path: pathlib.Path, kind: str, label: str, content_type: str) -> JsonMap:
    return {
        "name": path.name,
        "path": str(path),
        "kind": kind,
        "label": label,
        "contentType": content_type,
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def add_artifact(manifest: JsonMap, path: pathlib.Path, kind: str, label: str, content_type: str) -> None:
    item = artifact_item(path, kind, label, content_type)
    artifacts = as_map(manifest.get("artifacts"), "manifest.artifacts")
    as_list(artifacts.get("files"), "manifest.artifacts.files").append(str(path))
    as_list(artifacts.get("items"), "manifest.artifacts.items").append(item)
    as_map(artifacts.get("sha256"), "manifest.artifacts.sha256")[str(path)] = item["sha256"]


def markdown_artifact(manifest: JsonMap, path: pathlib.Path, label: str, text: str) -> None:
    write_text(path, text)
    add_artifact(manifest, path, "text", label, "text/markdown")


def json_artifact(manifest: JsonMap, path: pathlib.Path, label: str, payload: object) -> None:
    write_json(path, payload)
    add_artifact(manifest, path, "json", label, "application/json")


def manifest_output_dir(manifest: JsonMap) -> pathlib.Path:
    local = as_map(manifest.get("local"), "manifest.local")
    return pathlib.Path(string_field(local, "outputDirectory", "manifest.local"))


def manifest_request(manifest: JsonMap) -> JsonMap:
    return as_map(manifest.get("request", {}), "manifest.request")


def placeholder_image(path: pathlib.Path, title: str, subtitle: str, size: tuple[int, int] = (1280, 720)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, (32, 36, 42))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 84), fill=(236, 196, 83))
    draw.text((36, 28), title[:96], fill=(24, 24, 24))
    for index, line in enumerate(textwrap.wrap(subtitle, width=54)[:8]):
        draw.text((54, 142 + index * 42), line, fill=(238, 238, 232))
    image.save(path)


def make_contact_sheet(images: list[pathlib.Path], output: pathlib.Path, title: str) -> bool:
    if not images:
        return False
    thumbs: list[Image.Image] = []
    for image_path in images[:12]:
        image = Image.open(image_path).convert("RGB")
        image = ImageOps.contain(image, (220, 160), method=Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (240, 210), (246, 246, 242))
        tile.paste(image, ((240 - image.width) // 2, 14))
        ImageDraw.Draw(tile).text((12, 184), image_path.stem[:28], fill=(40, 40, 40))
        thumbs.append(tile)
    columns = min(4, max(1, len(thumbs)))
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 240, rows * 210 + 56), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle((0, 0, sheet.width, 56), fill=(42, 52, 62))
    draw.text((18, 20), title[:80], fill=(255, 255, 255))
    for index, tile in enumerate(thumbs):
        sheet.paste(tile, ((index % columns) * 240, 56 + (index // columns) * 210))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return True


def request_summary(request: JsonMap) -> JsonMap:
    inputs = request_inputs(request)
    return {
        "projectId": request.get("project_id") or request.get("projectId"),
        "parentType": request.get("parent_type") or request.get("parentType"),
        "parentId": request.get("parent_id") or request.get("parentId"),
        "prompt": inputs.get("prompt") or request.get("prompt"),
        "assetCount": len(normalize_assets(request)),
        "options": request_options(request),
    }


def script_text(request: JsonMap) -> str:
    inputs = request_inputs(request)
    value = inputs.get("script") or inputs.get("notes") or request.get("script") or request.get("prompt") or ""
    return str(value)


def execute_character_knockout(manifest: JsonMap, images: list[pathlib.Path]) -> None:
    output_dir = manifest_output_dir(manifest)
    source = images[0] if images else None
    if source:
        output = output_dir / "character-knockout.png"
        mask = output_dir / "character-mask.png"
        knockout_cli = shutil.which("mere-image-tools")
        if knockout_cli:
            command = [
                knockout_cli,
                "knockout",
                "--input",
                str(source),
                "--output",
                str(output),
                "--mask-output",
                str(mask),
                "--run-id",
                string_field(manifest, "runId", "manifest") + "-knockout",
            ]
            process = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if process.returncode != 0:
                eprint(process.stderr.strip() or process.stdout.strip())
        if not output.is_file() or not mask.is_file():
            image = Image.open(source).convert("RGBA")
            gray = ImageOps.grayscale(image)
            alpha = gray.point(lambda pixel: 255 if pixel > 18 else 0).filter(ImageFilter.GaussianBlur(radius=0.6))
            result = image.copy()
            result.putalpha(alpha)
            result.save(output)
            alpha.save(mask)
    else:
        output = output_dir / "character-knockout.png"
        mask = output_dir / "character-mask.png"
        placeholder_image(output, "Character Knockout", "No source image was provided; this placeholder marks the requested knockout.")
        Image.new("L", (1280, 720), 255).save(mask)
    add_artifact(manifest, output, "image", "transparent-character", "image/png")
    add_artifact(manifest, mask, "mask", "alpha-mask", "image/png")


def execute_reference_pack(manifest: JsonMap, images: list[pathlib.Path]) -> None:
    output_dir = manifest_output_dir(manifest)
    sheet = output_dir / "reference-contact-sheet.jpg"
    if not make_contact_sheet(images, sheet, "Reference Pack"):
        placeholder_image(sheet, "Reference Pack", "No source images were available for the reference pack.")
    add_artifact(manifest, sheet, "image", "contact-sheet", "image/jpeg")
    payload = {
        "summary": request_summary(manifest_request(manifest)),
        "references": [
            {"name": path.name, "path": str(path), "sha256": file_sha256(path)}
            for path in images
        ],
    }
    json_artifact(manifest, output_dir / "reference-pack.json", "reference-index", payload)


def execute_continuity_check(manifest: JsonMap, images: list[pathlib.Path]) -> None:
    request = manifest_request(manifest)
    text = script_text(request)
    findings = [
        "Confirm wardrobe, prop, and location state across adjacent beats.",
        "Lock character scale and eyelines before final shot generation.",
        "Check whether reference images cover every named character in the beat.",
    ]
    if len(images) <= 1:
        findings.append("Only one or no visual reference was supplied; visual continuity confidence is limited.")
    payload = {"summary": request_summary(request), "scriptBytes": len(text.encode("utf-8")), "findings": findings}
    output_dir = manifest_output_dir(manifest)
    json_artifact(manifest, output_dir / "continuity-report.json", "continuity-report", payload)
    markdown_artifact(manifest, output_dir / "continuity-report.md", "continuity-notes", "\n".join(f"- {item}" for item in findings))


def execute_shot_kit(manifest: JsonMap, _images: list[pathlib.Path]) -> None:
    request = manifest_request(manifest)
    inputs = request_inputs(request)
    beat = str(inputs.get("beat") or inputs.get("prompt") or request.get("prompt") or "Scene beat")
    shots = [
        {"slug": "establish", "lens": "wide", "purpose": "anchor geography", "prompt": f"Wide establishing frame for {beat}"},
        {"slug": "character-intent", "lens": "medium", "purpose": "read performance", "prompt": f"Medium character frame showing intent in {beat}"},
        {"slug": "insert-detail", "lens": "close", "purpose": "clarify prop or action", "prompt": f"Close insert detail for {beat}"},
    ]
    output_dir = manifest_output_dir(manifest)
    json_artifact(manifest, output_dir / "shot-kit.json", "shot-kit", {"summary": request_summary(request), "shots": shots})
    markdown_artifact(
        manifest,
        output_dir / "shot-list.md",
        "shot-list",
        "\n".join(f"- {shot['slug']}: {shot['lens']} - {shot['purpose']} - {shot['prompt']}" for shot in shots),
    )


def execute_storyboard_repair(manifest: JsonMap, images: list[pathlib.Path]) -> None:
    repairs = [
        "Add an entry frame if the scene starts on a close-up without geography.",
        "Add a bridge pose when the action changes direction between frames.",
        "Add a reaction frame before dialogue payoff if emotion changes abruptly.",
    ]
    output_dir = manifest_output_dir(manifest)
    if images:
        sheet = output_dir / "storyboard-repair-contact-sheet.jpg"
        make_contact_sheet(images, sheet, "Storyboard Repair")
        add_artifact(manifest, sheet, "image", "repair-contact-sheet", "image/jpeg")
    json_artifact(manifest, output_dir / "storyboard-repair.json", "repair-plan", {"summary": request_summary(manifest_request(manifest)), "repairs": repairs})
    markdown_artifact(manifest, output_dir / "storyboard-repair.md", "repair-notes", "\n".join(f"- {item}" for item in repairs))


def execute_edit_doctor(manifest: JsonMap, _images: list[pathlib.Path]) -> None:
    notes = [
        "Mark the clearest action reversal and give it one readable anticipation beat.",
        "Trim duplicate setup frames once character geography is established.",
        "Preserve a reaction beat after the highest-information line.",
    ]
    output_dir = manifest_output_dir(manifest)
    json_artifact(manifest, output_dir / "edit-doctor.json", "edit-report", {"summary": request_summary(manifest_request(manifest)), "notes": notes})
    markdown_artifact(manifest, output_dir / "edit-doctor.md", "edit-notes", "\n".join(f"- {item}" for item in notes))


def execute_actor_voice_kit(manifest: JsonMap, _images: list[pathlib.Path]) -> None:
    inputs = request_inputs(manifest_request(manifest))
    character = str(inputs.get("character") or inputs.get("character_name") or "Character")
    lines_raw = inputs.get("lines")
    lines = lines_raw if isinstance(lines_raw, list) else []
    sides = [str(line) for line in lines] or ["Add selected dialogue lines to the request inputs for generated sides."]
    payload = {
        "character": character,
        "direction": ["intent-first reads", "avoid announcing exposition", "keep breaths usable for edit handles"],
        "sides": sides,
    }
    output_dir = manifest_output_dir(manifest)
    json_artifact(manifest, output_dir / "actor-voice-kit.json", "voice-kit", payload)
    markdown_artifact(manifest, output_dir / "actor-sides.md", "actor-sides", "\n".join(f"- {line}" for line in sides))


def execute_location_plates(manifest: JsonMap, images: list[pathlib.Path]) -> None:
    output_dir = manifest_output_dir(manifest)
    sheet = output_dir / "location-plates.jpg"
    if not make_contact_sheet(images, sheet, "Location Plates"):
        placeholder_image(sheet, "Location Plates", "No plate references were supplied.")
    add_artifact(manifest, sheet, "image", "location-contact-sheet", "image/jpeg")
    notes = ["wide clean plate", "action-safe mid plate", "lighting reference", "negative space for characters"]
    json_artifact(manifest, output_dir / "location-plates.json", "location-plate-plan", {"summary": request_summary(manifest_request(manifest)), "needed": notes})


def execute_style_lock(manifest: JsonMap, images: list[pathlib.Path]) -> None:
    output_dir = manifest_output_dir(manifest)
    palette = output_dir / "style-palette.png"
    colors = [(45, 54, 62), (232, 196, 82), (200, 86, 72), (80, 139, 126), (238, 236, 228)]
    if images:
        sample = Image.open(images[0]).convert("RGB").resize((1, 1))
        pixel = sample.getpixel((0, 0))
        if isinstance(pixel, tuple):
            colors[0] = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
    image = Image.new("RGB", (640, 160), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for index, color in enumerate(colors):
        draw.rectangle((index * 128, 0, (index + 1) * 128, 160), fill=color)
        draw.text((index * 128 + 12, 124), "#{:02x}{:02x}{:02x}".format(*color), fill=(0, 0, 0))
    palette.parent.mkdir(parents=True, exist_ok=True)
    image.save(palette)
    add_artifact(manifest, palette, "image", "style-palette", "image/png")
    rules = ["Use the palette as a constraint, not a wash.", "Keep character silhouettes readable at thumbnail size.", "Do not change material language between adjacent shots."]
    json_artifact(manifest, output_dir / "style-lock.json", "style-lock", {"summary": request_summary(manifest_request(manifest)), "palette": colors, "rules": rules})
    markdown_artifact(manifest, output_dir / "style-bible-seed.md", "style-bible-seed", "\n".join(f"- {item}" for item in rules))


def execute_delivery_prep(manifest: JsonMap, _images: list[pathlib.Path]) -> None:
    checklist = [
        "Every shot has a final frame, source prompt, and parent scene.",
        "Character refs, location refs, and style locks are linked in metadata.",
        "Generated media URLs are durable and reviewable.",
        "Open issues are listed before delivery export.",
    ]
    output_dir = manifest_output_dir(manifest)
    json_artifact(manifest, output_dir / "delivery-manifest.json", "delivery-manifest", {"summary": request_summary(manifest_request(manifest)), "checklist": checklist})
    markdown_artifact(manifest, output_dir / "delivery-checklist.md", "delivery-checklist", "\n".join(f"- {item}" for item in checklist))


EXECUTORS: dict[str, Callable[[JsonMap, list[pathlib.Path]], None]] = {
    "character-knockout": execute_character_knockout,
    "reference-pack": execute_reference_pack,
    "continuity-check": execute_continuity_check,
    "shot-kit": execute_shot_kit,
    "storyboard-repair": execute_storyboard_repair,
    "edit-doctor": execute_edit_doctor,
    "actor-voice-kit": execute_actor_voice_kit,
    "location-plates": execute_location_plates,
    "style-lock": execute_style_lock,
    "delivery-prep": execute_delivery_prep,
}


def update_manifest(path: pathlib.Path, manifest: JsonMap, **updates: object) -> None:
    manifest.update(updates)
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def execute_manifest(manifest_path: pathlib.Path, manifest: JsonMap) -> JsonMap:
    tool = as_map(manifest.get("tool", {}), "manifest.tool")
    spec_name = tool.get("name")
    if not isinstance(spec_name, str) or spec_name not in EXECUTORS:
        raise PluginError(f"unsupported animatic tool: {spec_name}", 2)
    output_dir = manifest_output_dir(manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    update_manifest(manifest_path, manifest, status="running")
    try:
        local = as_map(manifest.get("local"), "manifest.local")
        downloaded = download_assets(manifest_request(manifest), output_dir)
        local["downloadedInputs"] = [str(path) for path in downloaded]
        EXECUTORS[spec_name](manifest, image_files(downloaded))
        result_path = output_dir / "tool-result.json"
        artifacts = as_map(manifest.get("artifacts"), "manifest.artifacts")
        result = {
            "runId": string_field(manifest, "runId", "manifest"),
            "tool": spec_name,
            "status": "succeeded",
            "artifacts": artifacts["items"],
        }
        write_json(result_path, result)
        add_artifact(manifest, result_path, "json", "tool-result", "application/json")
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


def command_doctor(_args: argparse.Namespace) -> int:
    checks = [
        {"name": "python", "ok": True, "detail": sys.version.split()[0]},
        {"name": "pillow", "ok": True, "detail": PIL.__version__},
        {"name": "mere-image-tools", "ok": shutil.which("mere-image-tools") is not None, "optional": True},
    ]
    print_json({"ok": all(item["ok"] or item.get("optional") for item in checks), "checks": checks})
    return 0


def command_plan(args: argparse.Namespace) -> int:
    spec = TOOLS[args.tool]
    request = load_request(args)
    manifest = make_manifest(spec, args, request)
    local = as_map(manifest.get("local"), "manifest.local")
    write_json(pathlib.Path(string_field(local, "runManifest", "manifest.local")), manifest)
    print_json(manifest)
    return 0


def command_run(args: argparse.Namespace) -> int:
    manifest = load_json_file(args.run_manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    manifest = execute_manifest(args.run_manifest, manifest)
    print_json(manifest)
    return 0


def command_tool(spec: ToolSpec, args: argparse.Namespace) -> int:
    request = load_request(args)
    if not request:
        request = {"tool": spec.name, "inputs": {"prompt": args.prompt or ""}, "options": {}}
    manifest = make_manifest(spec, args, request)
    local = as_map(manifest.get("local"), "manifest.local")
    manifest_path = pathlib.Path(string_field(local, "runManifest", "manifest.local"))
    write_json(manifest_path, manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    manifest = execute_manifest(manifest_path, manifest)
    print_json(manifest)
    return 0


def command_resume(args: argparse.Namespace) -> int:
    manifest = load_json_file(args.run_manifest)
    print_json({
        "runId": manifest.get("runId"),
        "status": manifest.get("status"),
        "tool": manifest.get("tool"),
        "artifacts": manifest.get("artifacts"),
        "cleanup": manifest.get("cleanup"),
    })
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    manifest = load_json_file(args.run_manifest)
    cleanup = as_map(
        manifest.setdefault("cleanup", {"default": "none", "status": "not-started"}),
        "manifest.cleanup",
    )
    cleanup["status"] = "skipped"
    cleanup["reason"] = "local animatic tools do not create remote resources"
    update_manifest(args.run_manifest, manifest)
    print_json(manifest)
    return 0


def add_request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--request-json", type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--run-id", default=default_run_id())


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if hasattr(args, "run_id"):
        validate_run_id(args.run_id)
    for name in ("request_json", "output_dir", "manifest", "run_manifest"):
        if hasattr(args, name):
            value = getattr(args, name)
            if value is not None:
                setattr(args, name, value.expanduser().resolve())
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mere-animatic-tools")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=lambda args: command_manifest(args))

    doctor = sub.add_parser("doctor", help="Check local readiness.")
    doctor.set_defaults(func=lambda args: command_doctor(args))

    plan = sub.add_parser("plan", help="Create an animatic tool plan.")
    plan.add_argument("--tool", required=True, choices=sorted(TOOLS))
    add_request_args(plan)
    plan.set_defaults(func=lambda args: command_plan(args))

    run = sub.add_parser("run", help="Execute a planned animatic run manifest.")
    run.add_argument("run_manifest", type=pathlib.Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=lambda args: command_run(args))

    resume = sub.add_parser("resume", help="Inspect a run manifest.")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.set_defaults(func=lambda args: command_resume(args))

    cleanup = sub.add_parser("cleanup", help="Mark local cleanup as skipped.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=lambda args: command_cleanup(args))

    for spec in TOOLS.values():
        tool = sub.add_parser(spec.name, help=spec.description)
        add_request_args(tool)
        tool.add_argument("--prompt")
        tool.add_argument("--dry-run", action="store_true")
        tool.set_defaults(func=lambda args, current=spec: command_tool(current, args))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args = normalize_args(args)
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

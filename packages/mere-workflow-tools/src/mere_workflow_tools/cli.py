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
from dataclasses import dataclass
from typing import Callable, cast

from PIL import Image, ImageDraw, ImageOps

from . import __version__, comfy_bridge, graph_compiler, graph_provider, graph_templates
from .graph_sdk import GraphProviderError

DEFAULT_MERE_RUN = "mere.run"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac"}
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
JsonMap = dict[str, object]
JsonList = list[object]


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class ToolSpec:
    kind: str
    plugin_name: str
    executable: str
    description: str
    capabilities: list[str]
    one_shot: str
    recipe_id: str
    recipe_title: str


TOOLS: dict[str, ToolSpec] = {
    "doc": ToolSpec(
        kind="doc",
        plugin_name="mere-doc-tools",
        executable="mere-doc-tools",
        description="OCR documents and redact PII with local mere.run models.",
        capabilities=["documents", "ocr", "pii-redaction", "privacy"],
        one_shot="process",
        recipe_id="doc-ocr-redact",
        recipe_title="Document OCR and PII redaction",
    ),
    "media": ToolSpec(
        kind="media",
        plugin_name="mere-media-scrub",
        executable="mere-media-scrub",
        description="Scan media frames for local text extraction and PII redaction.",
        capabilities=["media", "ocr", "pii-redaction", "privacy"],
        one_shot="scrub",
        recipe_id="media-ocr-scrub",
        recipe_title="Media OCR scrub",
    ),
    "dataset": ToolSpec(
        kind="dataset",
        plugin_name="mere-dataset-tools",
        executable="mere-dataset-tools",
        description="Prepare LoRA datasets with local captions, OCR sidecars, and contact sheets.",
        capabilities=["dataset", "captioning", "ocr", "lora"],
        one_shot="caption",
        recipe_id="dataset-caption",
        recipe_title="Dataset caption preparation",
    ),
    "transcript": ToolSpec(
        kind="transcript",
        plugin_name="mere-transcript-tools",
        executable="mere-transcript-tools",
        description="Transcribe local audio and optionally remove PII.",
        capabilities=["speech", "transcription", "pii-redaction", "privacy"],
        one_shot="transcribe",
        recipe_id="audio-transcribe-redact",
        recipe_title="Audio transcription and PII redaction",
    ),
    "image_compose": ToolSpec(
        kind="image_compose",
        plugin_name="mere-image-compose",
        executable="mere-image-compose",
        description="Generate production images with local mere.run models and recorded settings.",
        capabilities=["image", "generation", "reference-image", "lora"],
        one_shot="generate",
        recipe_id="image-compose-generate",
        recipe_title="Image generation composition",
    ),
    "batch": ToolSpec(
        kind="batch",
        plugin_name="mere-batch-runner",
        executable="mere-batch-runner",
        description="Run resumable local batches of mere.run commands from JSONL.",
        capabilities=["batch", "automation", "local-runner"],
        one_shot="run-jobs",
        recipe_id="batch-mere-run",
        recipe_title="Batch mere.run execution",
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


def as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    raise PluginError(f"manifest field is not an object: {label}", 1)


def as_list(value: object, label: str) -> JsonList:
    if isinstance(value, list):
        return value
    raise PluginError(f"manifest field is not a list: {label}", 1)


def manifest_local(manifest: JsonMap) -> JsonMap:
    return as_map(manifest["local"], "local")


def manifest_tool(manifest: JsonMap) -> JsonMap:
    return as_map(manifest["tool"], "tool")


def manifest_artifacts(manifest: JsonMap) -> JsonMap:
    return as_map(manifest["artifacts"], "artifacts")


def manifest_steps(manifest: JsonMap) -> JsonList:
    return as_list(manifest["steps"], "steps")


def string_list(value: object, label: str) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise PluginError(f"manifest field is not a string list: {label}", 1)


def load_json(path: pathlib.Path) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), str(path))
    except json.JSONDecodeError as exc:
        raise PluginError(f"invalid JSON in {path}: {exc}", 2) from None


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def tree_sha256(paths: list[pathlib.Path]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(paths):
        encoded = str(path).encode("utf-8")
        hasher.update(len(encoded).to_bytes(4, "big"))
        hasher.update(encoded)
        if path.is_file():
            hasher.update(path.read_bytes())
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


def default_run_id(spec: ToolSpec) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{spec.plugin_name}-{stamp}"


def default_manifest_path(output_dir: pathlib.Path) -> pathlib.Path:
    return output_dir / "run.json"


def ensure_file(path: pathlib.Path, label: str) -> None:
    if not path.is_file():
        raise PluginError(f"{label} does not exist: {path}", 2)


def ensure_dir(path: pathlib.Path, label: str) -> None:
    if not path.is_dir():
        raise PluginError(f"{label} does not exist: {path}", 2)


def image_inputs(path: pathlib.Path) -> list[pathlib.Path]:
    if path.is_file():
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise PluginError(f"unsupported image extension: {path.suffix}", 2)
        return [path]
    ensure_dir(path, "input directory")
    images = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
    if not images:
        raise PluginError(f"no image files found in {path}", 2)
    return images


def plugin_manifest(spec: ToolSpec) -> JsonMap:
    commands = [
        {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
        {"name": "doctor", "description": "Check local readiness and mere.run availability.", "stdout": "json"},
        {"name": "plan", "description": "Write a run manifest without executing mere.run.", "stdout": "json"},
        {"name": "run", "description": "Execute a planned local workflow manifest.", "stdout": "json"},
        {"name": "resume", "description": "Inspect a recorded workflow manifest.", "stdout": "json"},
        {"name": "cleanup", "description": "Mark a local run as cleanup-skipped.", "stdout": "json"},
        {"name": spec.one_shot, "description": f"Plan and run {spec.recipe_title}.", "stdout": "json"},
    ]
    capabilities = list(spec.capabilities)
    manifest: JsonMap = {
        "contractVersion": "mere.run/plugin.v1",
        "name": spec.plugin_name,
        "version": __version__,
        "executable": spec.executable,
        "description": spec.description,
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-workflow-tools",
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
    if spec.kind == "dataset":
        commands.append({"name": "graph", "description": "Expose portable graph nodes.", "stdout": "json"})
        capabilities.append("graph-node-provider-v1")
        manifest["graphProvider"] = {"contractVersion": graph_provider.CONTRACT_VERSION}
    return manifest


def base_manifest(spec: ToolSpec, args: argparse.Namespace, inputs: list[pathlib.Path]) -> JsonMap:
    created = now_iso()
    output_dir = args.output_dir
    manifest_path = args.manifest or default_manifest_path(output_dir)
    return {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": spec.plugin_name, "version": __version__},
        "recipe": {"id": spec.recipe_id, "family": "local-workflow", "title": spec.recipe_title},
        "status": "planned",
        "createdAt": created,
        "updatedAt": created,
        "dataset": {
            "path": str(inputs[0].parent if inputs and inputs[0].is_file() else output_dir.parent),
            "pairCount": max(1, len(inputs)),
            "sha256": tree_sha256(inputs),
        },
        "command": [],
        "local": {
            "outputDirectory": str(output_dir),
            "runManifest": str(manifest_path),
        },
        "tool": {
            "name": spec.plugin_name,
            "backend": "mere.run",
            "mereRunCommand": split_command(args.mere_run_command),
        },
        "artifacts": {
            "localDirectory": str(output_dir),
            "files": [],
            "sha256": {},
        },
        "steps": [],
        "cleanup": {"default": "none", "status": "not-started"},
    }


def make_manifest(spec: ToolSpec, args: argparse.Namespace) -> JsonMap:
    builders: dict[str, Callable[[ToolSpec, argparse.Namespace], JsonMap]] = {
        "doc": make_doc_manifest,
        "media": make_media_manifest,
        "dataset": make_dataset_manifest,
        "transcript": make_transcript_manifest,
        "image_compose": make_image_manifest,
        "batch": make_batch_manifest,
    }
    return builders[spec.kind](spec, args)


def add_step(manifest: JsonMap, name: str, argv: list[str], outputs: dict[str, str], stdin_path: str | None = None) -> None:
    step = {"name": name, "argv": argv, "outputs": outputs}
    if stdin_path is not None:
        step["stdinPath"] = stdin_path
    manifest_steps(manifest).append(step)


def make_doc_manifest(spec: ToolSpec, args: argparse.Namespace) -> JsonMap:
    input_path = args.input
    ensure_file(input_path, "input document image")
    manifest = base_manifest(spec, args, [input_path])
    ocr_dir = args.output_dir / "ocr"
    ocr_text = ocr_dir / f"{input_path.stem}.txt"
    redacted_text = args.output_dir / f"{input_path.stem}.redacted.txt"
    spans_json = args.output_dir / f"{input_path.stem}.pii.json"
    manifest["command"] = one_shot_command(spec, args)
    manifest_local(manifest)["input"] = str(input_path)
    manifest_tool(manifest).update({"workflow": "ocr-redact", "ocrBackend": args.ocr_backend, "redact": args.redact})
    add_step(
        manifest,
        "ocr",
        ["vision", "ocr", "--backend", args.ocr_backend, "--output-dir", str(ocr_dir), str(input_path)],
        {"text": str(ocr_text)},
    )
    if args.redact:
        add_step(
            manifest,
            "redact-text",
            ["text", "anonymize", "--output", str(redacted_text), "--replacement", args.replacement],
            {"redactedText": str(redacted_text)},
            stdin_path=str(ocr_text),
        )
        add_step(
            manifest,
            "redact-json",
            ["text", "anonymize", "--json", "--pretty", "--output", str(spans_json), "--replacement", args.replacement],
            {"spans": str(spans_json)},
            stdin_path=str(ocr_text),
        )
    return manifest


def make_media_manifest(spec: ToolSpec, args: argparse.Namespace) -> JsonMap:
    inputs = image_inputs(args.input)
    manifest = base_manifest(spec, args, inputs)
    ocr_dir = args.output_dir / "ocr"
    redacted_dir = args.output_dir / "redacted"
    manifest["command"] = one_shot_command(spec, args)
    manifest_local(manifest)["input"] = str(args.input)
    manifest_tool(manifest).update({"workflow": "media-ocr-scrub", "ocrBackend": args.ocr_backend, "redact": args.redact})
    add_step(
        manifest,
        "ocr",
        ["vision", "ocr", "--backend", args.ocr_backend, "--output-dir", str(ocr_dir)] + [str(path) for path in inputs],
        {"textDirectory": str(ocr_dir)},
    )
    if args.redact:
        for image in inputs:
            source_text = ocr_dir / f"{image.stem}.txt"
            redacted_text = redacted_dir / f"{image.stem}.redacted.txt"
            add_step(
                manifest,
                f"redact-{image.stem}",
                ["text", "anonymize", "--output", str(redacted_text), "--replacement", args.replacement],
                {"redactedText": str(redacted_text)},
                stdin_path=str(source_text),
            )
    return manifest


def make_dataset_manifest(spec: ToolSpec, args: argparse.Namespace) -> JsonMap:
    ensure_dir(args.input, "dataset directory")
    inputs = image_inputs(args.input)
    manifest = base_manifest(spec, args, inputs)
    captions_dir = args.output_dir / "captions"
    ocr_dir = args.output_dir / "ocr"
    contact_sheet = args.output_dir / "contact-sheet.jpg"
    manifest["command"] = one_shot_command(spec, args)
    manifest_local(manifest)["input"] = str(args.input)
    manifest_tool(manifest).update({
        "workflow": "dataset-caption",
        "triggerToken": args.trigger_token,
        "focus": args.focus,
        "ocr": args.ocr,
        "contactSheet": args.contact_sheet,
    })
    caption_argv = ["vision", "caption", "--output-dir", str(captions_dir)]
    if args.prompt:
        caption_argv.extend(["--prompt", args.prompt])
    if args.trigger_token:
        caption_argv.extend(["--trigger-token", args.trigger_token])
    caption_argv.extend(str(path) for path in inputs)
    # mere.run parses --focus greedily (up to the next option), swallowing any bare
    # argument after it, so focus terms must stay last; `=` keeps dash-led terms intact.
    caption_argv.extend(f"--focus={focus}" for focus in args.focus)
    add_step(manifest, "caption", caption_argv, {"captionDirectory": str(captions_dir)})
    if args.ocr:
        add_step(
            manifest,
            "ocr-sidecars",
            ["vision", "ocr", "--backend", args.ocr_backend, "--output-dir", str(ocr_dir)] + [str(path) for path in inputs],
            {"ocrDirectory": str(ocr_dir)},
        )
    if args.contact_sheet:
        manifest_steps(manifest).append({
            "name": "contact-sheet",
            "python": "contact-sheet",
            "inputs": [str(path) for path in inputs],
            "outputs": {"contactSheet": str(contact_sheet)},
        })
    return manifest


def make_transcript_manifest(spec: ToolSpec, args: argparse.Namespace) -> JsonMap:
    ensure_file(args.input, "audio input")
    if args.input.suffix.lower() not in AUDIO_EXTENSIONS:
        raise PluginError(f"unsupported audio extension: {args.input.suffix}", 2)
    manifest = base_manifest(spec, args, [args.input])
    transcript = args.output_dir / f"{args.input.stem}.txt"
    redacted = args.output_dir / f"{args.input.stem}.redacted.txt"
    manifest["command"] = one_shot_command(spec, args)
    manifest_local(manifest)["input"] = str(args.input)
    manifest_tool(manifest).update({"workflow": "transcribe-redact", "asrBackend": args.backend, "redact": args.redact})
    transcribe_argv = ["speech", "transcribe", str(args.input), "--output", str(transcript), "--backend", args.backend]
    if args.language:
        transcribe_argv.extend(["--language", args.language])
    add_step(manifest, "transcribe", transcribe_argv, {"transcript": str(transcript)})
    if args.redact:
        add_step(
            manifest,
            "redact-transcript",
            ["text", "anonymize", "--output", str(redacted), "--replacement", args.replacement],
            {"redactedTranscript": str(redacted)},
            stdin_path=str(transcript),
        )
    return manifest


def make_image_manifest(spec: ToolSpec, args: argparse.Namespace) -> JsonMap:
    output_image = args.output_dir / "image.png"
    inputs = [args.ref_image] if args.ref_image else [args.output_dir]
    if args.ref_image:
        ensure_file(args.ref_image, "reference image")
    manifest = base_manifest(spec, args, inputs)
    manifest["command"] = one_shot_command(spec, args)
    manifest_tool(manifest).update({
        "workflow": "image-generate",
        "model": args.model,
        "prompt": args.prompt,
        "width": args.width,
        "height": args.height,
        "steps": args.steps,
        "seed": args.seed,
        "lora": str(args.lora) if args.lora else None,
        "loraScale": args.lora_scale,
        "referenceImage": str(args.ref_image) if args.ref_image else None,
    })
    argv = [
        "image",
        "generate",
        "--model",
        args.model,
        "--prompt",
        args.prompt,
        "--output",
        str(output_image),
        "--width",
        str(args.width),
        "--height",
        str(args.height),
    ]
    if args.steps is not None:
        argv.extend(["--steps", str(args.steps)])
    if args.seed is not None:
        argv.extend(["--seed", str(args.seed)])
    if args.ref_image:
        argv.extend(["--ref-image", str(args.ref_image)])
        argv.extend(["--strength", str(args.strength)])
    if args.lora:
        argv.extend(["--lora", str(args.lora), "--lora-scale", str(args.lora_scale)])
    add_step(manifest, "generate", argv, {"image": str(output_image)})
    return manifest


def make_batch_manifest(spec: ToolSpec, args: argparse.Namespace) -> JsonMap:
    ensure_file(args.jobs, "jobs file")
    jobs: list[tuple[list[str], dict[str, str]]] = []
    for index, line in enumerate(args.jobs.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        job = json.loads(line)
        argv = job.get("argv")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise PluginError(f"job {index} must contain string-array argv", 2)
        outputs_raw = job.get("outputs") if isinstance(job.get("outputs"), dict) else {}
        outputs = {str(key): str(value) for key, value in outputs_raw.items()}
        jobs.append((argv, outputs))
    if not jobs:
        raise PluginError(f"jobs file contains no runnable jobs: {args.jobs}", 2)
    manifest = base_manifest(spec, args, [args.jobs])
    manifest["command"] = one_shot_command(spec, args)
    manifest_local(manifest)["jobs"] = str(args.jobs)
    manifest_tool(manifest).update({"workflow": "batch", "jobCount": len(jobs), "continueOnError": args.continue_on_error})
    for index, (argv, outputs) in enumerate(jobs, start=1):
        add_step(manifest, f"job-{index:03d}", argv, outputs)
    return manifest


def one_shot_command(spec: ToolSpec, args: argparse.Namespace) -> list[str]:
    command = [
        spec.executable,
        spec.one_shot,
        "--output-dir",
        str(args.output_dir),
        "--run-id",
        args.run_id,
        "--mere-run-command",
        args.mere_run_command,
    ]
    if args.manifest:
        command.extend(["--manifest", str(args.manifest)])
    for name in ("input", "jobs"):
        if hasattr(args, name):
            command.extend([f"--{name.replace('_', '-')}", str(getattr(args, name))])
    return command


def execute_manifest(manifest_path: pathlib.Path, manifest: JsonMap) -> JsonMap:
    output_dir = pathlib.Path(str(manifest_local(manifest)["outputDirectory"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    update_manifest(manifest_path, manifest, status="running")
    try:
        for raw_step in manifest_steps(manifest):
            step = as_map(raw_step, "step")
            if step.get("python") == "contact-sheet":
                outputs = as_map(step["outputs"], "step.outputs")
                make_contact_sheet(
                    [pathlib.Path(item) for item in string_list(step["inputs"], "step.inputs")],
                    pathlib.Path(str(outputs["contactSheet"])),
                )
            else:
                run_mere_step(manifest, step)
        files = collect_artifacts(manifest)
        artifacts = manifest_artifacts(manifest)
        artifacts["files"] = files
        artifacts["sha256"] = {
            str(path): file_sha256(pathlib.Path(path))
            for path in files
            if pathlib.Path(path).is_file()
        }
        update_manifest(manifest_path, manifest, status="succeeded")
    except Exception as exc:
        manifest["error"] = str(exc)
        update_manifest(manifest_path, manifest, status="failed")
        raise
    return manifest


def run_mere_step(manifest: JsonMap, step: JsonMap) -> None:
    command = string_list(manifest_tool(manifest)["mereRunCommand"], "tool.mereRunCommand") + string_list(
        step["argv"],
        "step.argv",
    )
    if not command_available(command):
        raise PluginError(f"mere.run command not found: {command[0]}. Install mere.run or pass --mere-run-command.", 3)
    stdin_data = None
    if "stdinPath" in step:
        stdin_path = pathlib.Path(str(step["stdinPath"]))
        if not stdin_path.is_file():
            raise PluginError(f"step input missing for {step['name']}: {stdin_path}", 1)
        stdin_data = stdin_path.read_text()
    outputs = as_map(step.get("outputs", {}), "step.outputs")
    for output in outputs.values():
        pathlib.Path(str(output)).parent.mkdir(parents=True, exist_ok=True)
    eprint("$ " + shlex.join(command))
    process = subprocess.run(
        command,
        input=stdin_data,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if process.stdout:
        for line in process.stdout.splitlines():
            eprint(line)
    if process.returncode != 0:
        raise PluginError(f"mere.run step {step['name']} failed with exit {process.returncode}", 1)


def collect_artifacts(manifest: JsonMap) -> list[str]:
    files: list[str] = []
    for raw_step in manifest_steps(manifest):
        step = as_map(raw_step, "step")
        outputs = as_map(step.get("outputs", {}), "step.outputs")
        for output in outputs.values():
            path = pathlib.Path(str(output))
            if path.is_file():
                files.append(str(path))
            elif path.is_dir():
                files.extend(str(item) for item in sorted(path.rglob("*")) if item.is_file())
    return sorted(dict.fromkeys(files))


def make_contact_sheet(images: list[pathlib.Path], output: pathlib.Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    thumbs: list[Image.Image] = []
    for image_path in images[:64]:
        image = Image.open(image_path).convert("RGB")
        image = ImageOps.contain(image, (160, 160), method=Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (180, 205), (245, 245, 245))
        tile.paste(image, ((180 - image.width) // 2, 8))
        draw = ImageDraw.Draw(tile)
        label = image_path.stem[:22]
        draw.text((8, 182), label, fill=(40, 40, 40))
        thumbs.append(tile)
    columns = min(4, max(1, len(thumbs)))
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 180, rows * 205), (255, 255, 255))
    for index, tile in enumerate(thumbs):
        sheet.paste(tile, ((index % columns) * 180, (index // columns) * 205))
    sheet.save(output)


def update_manifest(path: pathlib.Path, manifest: JsonMap, **updates: object) -> None:
    manifest.update(updates)
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def command_manifest(spec: ToolSpec, args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest(spec))
    return 0


def command_doctor(_spec: ToolSpec, args: argparse.Namespace) -> int:
    mere_run_command = split_command(args.mere_run_command)
    checks = [
        {"name": "python", "ok": True, "detail": sys.version.split()[0]},
        {"name": "mere.run", "ok": command_available(mere_run_command), "detail": shlex.join(mere_run_command)},
    ]
    ok = all(item["ok"] for item in checks)
    print_json({"ok": ok, "checks": checks})
    return 0 if ok else 3


def command_plan(spec: ToolSpec, args: argparse.Namespace) -> int:
    manifest = make_manifest(spec, args)
    write_json(pathlib.Path(str(manifest_local(manifest)["runManifest"])), manifest)
    print_json(manifest)
    return 0


def command_run(_spec: ToolSpec, args: argparse.Namespace) -> int:
    manifest_path = args.run_manifest
    manifest = load_json(manifest_path)
    if args.dry_run:
        print_json(manifest)
        return 0
    manifest = execute_manifest(manifest_path, manifest)
    print_json(manifest)
    return 0


def command_one_shot(spec: ToolSpec, args: argparse.Namespace) -> int:
    manifest = make_manifest(spec, args)
    manifest_path = pathlib.Path(str(manifest_local(manifest)["runManifest"]))
    write_json(manifest_path, manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    manifest = execute_manifest(manifest_path, manifest)
    print_json(manifest)
    return 0


def command_resume(_spec: ToolSpec, args: argparse.Namespace) -> int:
    manifest = load_json(args.run_manifest)
    print_json({
        "runId": manifest.get("runId"),
        "status": manifest.get("status"),
        "tool": manifest.get("tool"),
        "artifacts": manifest.get("artifacts"),
        "cleanup": manifest.get("cleanup"),
    })
    return 0


def command_cleanup(_spec: ToolSpec, args: argparse.Namespace) -> int:
    manifest = load_json(args.run_manifest)
    cleanup = as_map(manifest.setdefault("cleanup", {"default": "none", "status": "not-started"}), "cleanup")
    cleanup["status"] = "skipped"
    cleanup["reason"] = "local workflow tools do not create remote resources"
    update_manifest(args.run_manifest, manifest)
    print_json(manifest)
    return 0


def command_graph_catalog(spec: ToolSpec, _args: argparse.Namespace) -> int:
    print_json(graph_provider.graph_catalog(spec.plugin_name, __version__))
    return 0


def command_graph_preflight(_spec: ToolSpec, args: argparse.Namespace) -> int:
    try:
        invocation = graph_provider.load_invocation(args.request)
        print_json(graph_provider.graph_preflight(invocation, args.graph_run_dir))
        return 0
    except GraphProviderError as exc:
        raise PluginError(str(exc), 2) from None


def command_graph_execute(_spec: ToolSpec, args: argparse.Namespace) -> int:
    try:
        invocation = graph_provider.load_invocation(args.request)

        def write_event(payload: JsonMap) -> None:
            sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            sys.stdout.flush()

        graph_provider.graph_execute(invocation, args.graph_run_dir, write_event)
        return 0
    except GraphProviderError as exc:
        raise PluginError(str(exc), 1) from None


def command_comfy_inspect(_spec: ToolSpec, args: argparse.Namespace) -> int:
    try:
        print_json(comfy_bridge.inspect_workflow(comfy_bridge.load_workflow(args.workflow)))
        return 0
    except (comfy_bridge.ComfyBridgeError, OSError) as exc:
        raise PluginError(str(exc), 2) from None


def command_comfy_import(_spec: ToolSpec, args: argparse.Namespace) -> int:
    try:
        graph, inputs, report = comfy_bridge.import_workflow(
            comfy_bridge.load_workflow(args.workflow),
            model_id=args.model,
            source_name=args.workflow.name,
            asset_root=args.asset_root,
        )
        comfy_bridge.write_json(args.output, graph)
        comfy_bridge.write_json(args.inputs_output, inputs)
        print_json(
            {
                "contract_version": comfy_bridge.BRIDGE_CONTRACT_VERSION,
                "status": "imported",
                "graph": str(args.output),
                "inputs": str(args.inputs_output),
                "report": report,
            }
        )
        return 0
    except (comfy_bridge.ComfyBridgeError, OSError) as exc:
        raise PluginError(str(exc), 2) from None


def command_graph_template_list(_spec: ToolSpec, _args: argparse.Namespace) -> int:
    print_json(graph_templates.catalog())
    return 0


def command_graph_template_export(_spec: ToolSpec, args: argparse.Namespace) -> int:
    try:
        graph_templates.export_template(args.template_id, args.output)
        print_json(
            {
                "contract_version": "mere.run/graph-template-export.v1",
                "status": "exported",
                "template_id": args.template_id,
                "output": str(args.output),
            }
        )
        return 0
    except (GraphProviderError, OSError) as exc:
        raise PluginError(str(exc), 2) from None


def command_graph_template_publish(_spec: ToolSpec, args: argparse.Namespace) -> int:
    try:
        graph = load_json(args.graph)
        inputs = load_json(args.inputs_json) if args.inputs_json else {}
        package = graph_templates.publish_template(
            graph,
            inputs,
            args.output_dir,
            args.template_id,
            args.title,
            args.description,
            args.tag,
        )
        print_json({"status": "published", "package": package, "output_directory": str(args.output_dir)})
        return 0
    except (GraphProviderError, OSError) as exc:
        raise PluginError(str(exc), 2) from None


def command_graph_compile(_spec: ToolSpec, args: argparse.Namespace) -> int:
    try:
        print_json(graph_compiler.run(args))
        return 0
    except (GraphProviderError, OSError) as exc:
        raise PluginError(str(exc), 2) from None


def add_common_plan_args(parser: argparse.ArgumentParser, spec: ToolSpec) -> None:
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--mere-run-command", default="")
    parser.add_argument("--run-id", default=default_run_id(spec))


def add_kind_args(parser: argparse.ArgumentParser, spec: ToolSpec) -> None:
    if spec.kind in {"doc", "media", "dataset", "transcript"}:
        parser.add_argument("--input", required=True, type=pathlib.Path)
    if spec.kind in {"doc", "media"}:
        parser.add_argument("--ocr-backend", default="lighton", choices=["lighton", "glm", "infinity"])
        parser.add_argument("--redact", action=argparse.BooleanOptionalAction, default=True)
        parser.add_argument("--replacement", default="[{label}]")
    if spec.kind == "dataset":
        parser.add_argument("--prompt")
        parser.add_argument("--focus", action="append", default=[])
        parser.add_argument("--trigger-token")
        parser.add_argument("--ocr", action="store_true")
        parser.add_argument("--ocr-backend", default="lighton", choices=["lighton", "glm", "infinity"])
        parser.add_argument("--contact-sheet", action=argparse.BooleanOptionalAction, default=True)
    if spec.kind == "transcript":
        parser.add_argument("--backend", default="auto", choices=["auto", "parakeet", "qwen"])
        parser.add_argument("--language")
        parser.add_argument("--redact", action=argparse.BooleanOptionalAction, default=True)
        parser.add_argument("--replacement", default="[{label}]")
    if spec.kind == "image_compose":
        parser.add_argument("--prompt", required=True)
        parser.add_argument("--model", default="image-klein-9b")
        parser.add_argument("--width", type=int, default=1024)
        parser.add_argument("--height", type=int, default=1024)
        parser.add_argument("--steps", type=int)
        parser.add_argument("--seed", type=int)
        parser.add_argument("--ref-image", type=pathlib.Path)
        parser.add_argument("--strength", type=float, default=0.55)
        parser.add_argument("--lora", type=pathlib.Path)
        parser.add_argument("--lora-scale", type=float, default=1.5)
    if spec.kind == "batch":
        parser.add_argument("--jobs", required=True, type=pathlib.Path)
        parser.add_argument("--continue-on-error", action="store_true")


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if hasattr(args, "run_id"):
        validate_run_id(args.run_id)
    if hasattr(args, "mere_run_command") and not args.mere_run_command:
        args.mere_run_command = os.environ.get("MERE_WORKFLOW_TOOLS_MERE_RUN") or DEFAULT_MERE_RUN
    for name in (
        "input",
        "output_dir",
        "manifest",
        "run_manifest",
        "jobs",
        "ref_image",
        "lora",
        "request",
        "graph_run_dir",
        "workflow",
        "output",
        "inputs_output",
        "asset_root",
    ):
        if hasattr(args, name):
            value = getattr(args, name)
            if value is not None:
                setattr(args, name, value.expanduser().resolve())
    return args


def build_parser(spec: ToolSpec) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=spec.executable)
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check local readiness.")
    doctor.add_argument("--mere-run-command", default="")
    doctor.set_defaults(func=command_doctor)

    plan = sub.add_parser("plan", help="Create a local workflow plan.")
    add_common_plan_args(plan, spec)
    add_kind_args(plan, spec)
    plan.set_defaults(func=command_plan)

    run = sub.add_parser("run", help="Execute a planned workflow run manifest.")
    run.add_argument("run_manifest", type=pathlib.Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run)

    resume = sub.add_parser("resume", help="Inspect a run manifest.")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.set_defaults(func=command_resume)

    cleanup = sub.add_parser("cleanup", help="Mark local cleanup as skipped.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=command_cleanup)

    if spec.kind == "dataset":
        graph = sub.add_parser("graph", help="Expose portable graph nodes.")
        graph_sub = graph.add_subparsers(dest="graph_command", required=True)

        graph_catalog = graph_sub.add_parser("catalog", help="Print the graph node catalog.")
        graph_catalog.add_argument("--json", action="store_true")
        graph_catalog.set_defaults(func=command_graph_catalog)

        graph_preflight = graph_sub.add_parser("preflight", help="Preflight one graph node invocation.")
        graph_preflight.add_argument("--request", required=True, type=pathlib.Path)
        graph_preflight.add_argument("--run-dir", required=True, type=pathlib.Path, dest="graph_run_dir")
        graph_preflight.add_argument("--json", action="store_true")
        graph_preflight.set_defaults(func=command_graph_preflight)

        graph_execute = graph_sub.add_parser("execute", help="Execute one graph node invocation.")
        graph_execute.add_argument("--request", required=True, type=pathlib.Path)
        graph_execute.add_argument("--run-dir", required=True, type=pathlib.Path, dest="graph_run_dir")
        graph_execute.add_argument("--json-stream", action="store_true")
        graph_execute.set_defaults(func=command_graph_execute)

        graph_compile = graph_sub.add_parser(
            "compile",
            help="Compile reusable modules, maps, and branches into a portable graph.",
        )
        graph_compile.add_argument("source", type=pathlib.Path)
        graph_compile.add_argument("--output", required=True, type=pathlib.Path)
        graph_compile.add_argument("--report-output", type=pathlib.Path)
        graph_compile.add_argument("--variables-json", type=pathlib.Path)
        graph_compile.add_argument("--json", action="store_true")
        graph_compile.set_defaults(func=command_graph_compile)

        comfy = graph_sub.add_parser("comfy", help="Inspect or import ComfyUI workflows.")
        comfy_sub = comfy.add_subparsers(dest="comfy_command", required=True)

        comfy_inspect = comfy_sub.add_parser("inspect", help="Report ComfyUI workflow compatibility.")
        comfy_inspect.add_argument("workflow", type=pathlib.Path)
        comfy_inspect.add_argument("--json", action="store_true")
        comfy_inspect.set_defaults(func=command_comfy_inspect)

        comfy_import = comfy_sub.add_parser("import", help="Import a supported ComfyUI API prompt as a native graph.")
        comfy_import.add_argument("workflow", type=pathlib.Path)
        comfy_import.add_argument("--model", required=True, help="Managed mere.run model id replacing the Comfy checkpoint.")
        comfy_import.add_argument("--output", required=True, type=pathlib.Path)
        comfy_import.add_argument("--inputs-output", required=True, type=pathlib.Path)
        comfy_import.add_argument("--asset-root", type=pathlib.Path)
        comfy_import.add_argument("--json", action="store_true")
        comfy_import.set_defaults(func=command_comfy_import)

        templates = graph_sub.add_parser("templates", help="List or export reusable native graph templates.")
        template_sub = templates.add_subparsers(dest="template_command", required=True)

        template_list = template_sub.add_parser("list", help="List native graph templates.")
        template_list.add_argument("--json", action="store_true")
        template_list.set_defaults(func=command_graph_template_list)

        template_export = template_sub.add_parser("export", help="Export one native graph template.")
        template_export.add_argument("template_id")
        template_export.add_argument("--output", required=True, type=pathlib.Path)
        template_export.add_argument("--json", action="store_true")
        template_export.set_defaults(func=command_graph_template_export)

        template_publish = template_sub.add_parser("publish", help="Publish a confined reusable graph template package.")
        template_publish.add_argument("--graph", required=True, type=pathlib.Path)
        template_publish.add_argument("--inputs-json", type=pathlib.Path)
        template_publish.add_argument("--output-dir", required=True, type=pathlib.Path)
        template_publish.add_argument("--template-id", required=True)
        template_publish.add_argument("--title", required=True)
        template_publish.add_argument("--description", required=True)
        template_publish.add_argument("--tag", action="append", default=[])
        template_publish.add_argument("--json", action="store_true")
        template_publish.set_defaults(func=command_graph_template_publish)

    one_shot = sub.add_parser(spec.one_shot, help=f"Plan and run {spec.recipe_title}.")
    add_common_plan_args(one_shot, spec)
    add_kind_args(one_shot, spec)
    one_shot.add_argument("--dry-run", action="store_true")
    one_shot.set_defaults(func=command_one_shot)
    return parser


def main_for(kind: str, argv: list[str] | None = None) -> int:
    spec = TOOLS[kind]
    parser = build_parser(spec)
    args = parser.parse_args(argv)
    try:
        args = normalize_args(args)
        return int(args.func(spec, args))
    except PluginError as exc:
        eprint(f"Error: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        eprint("Interrupted.")
        return 130
    except Exception as exc:
        eprint(f"Unexpected error: {exc}")
        return 1

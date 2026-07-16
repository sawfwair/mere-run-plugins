from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
from typing import cast

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import __version__
from .database import connect, iter_face_embeddings, photo_needs_index, set_metadata, stats, store_error, store_result

PLUGIN_NAME = "mere-face-tools"
MODEL_ID = "vision-face-buffalo-l"
DEFAULT_MERE_RUN = "mere.run"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
JsonMap = dict[str, object]


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def default_run_id(prefix: str = "face-index") -> str:
    return prefix + "-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def print_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def eprint(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def write_json(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    raise PluginError(f"{label} is not an object")


def as_int(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise PluginError(f"{label} is not an integer")


def as_float(value: object, label: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise PluginError(f"{label} is not a number")


def split_command(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise PluginError(f"invalid mere.run command: {exc}", 2) from None
    if not parts:
        raise PluginError("mere.run command is empty", 2)
    return parts


def command_available(command: list[str]) -> bool:
    executable = pathlib.Path(command[0]).expanduser()
    return executable.is_file() or shutil.which(command[0]) is not None


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise PluginError("invalid --run-id; use letters, digits, '.', '_', and '-'", 2)


def scan_images(root: pathlib.Path, extensions: set[str], limit: int | None = None) -> list[pathlib.Path]:
    if not root.is_dir():
        raise PluginError(f"photo directory does not exist: {root}", 2)
    paths = [path.resolve() for path in root.rglob("*") if path.is_file() and path.suffix.lower() in extensions]
    paths.sort(key=lambda path: str(path).lower())
    return paths if limit is None else paths[:limit]


def plugin_manifest() -> JsonMap:
    commands = [
        ("manifest", "Print the plugin manifest."),
        ("doctor", "Check mere.run face-analysis and local SQLite readiness."),
        ("plan", "Create a durable photo-library index plan."),
        ("run", "Execute a planned face-library index."),
        ("resume", "Continue an interrupted face-library index."),
        ("cleanup", "Mark local cleanup as skipped without touching source photos."),
        ("index", "Plan and run resumable folder indexing into SQLite."),
        ("search", "Find and export photos similar to a reference face."),
    ]
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": PLUGIN_NAME,
        "description": "Local face-library indexing, similarity search, and review exports backed by mere.run.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-face-tools",
        "commands": [
            {"name": name, "description": description, "stdout": "json"}
            for name, description in commands
        ],
        "capabilities": [
            "face-analysis",
            "face-index",
            "face-search",
            "identity-embedding",
            "photo-library",
            "review-export",
            "sqlite",
        ],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": False,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def index_manifest(args: argparse.Namespace) -> JsonMap:
    images = scan_images(args.photos, set(args.extensions), args.limit)
    if not images:
        raise PluginError(f"no supported images found under {args.photos}", 2)
    validate_run_id(args.run_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "run.json"
    command = [
        PLUGIN_NAME,
        "index",
        "--photos",
        str(args.photos),
        "--database",
        str(args.database),
        "--output-dir",
        str(args.output_dir),
        "--model",
        args.model,
        "--execution-provider",
        args.execution_provider,
        "--batch-size",
        str(args.batch_size),
        "--run-id",
        args.run_id,
    ]
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    return {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {"id": "face-library-index", "family": "face-analysis"},
        "status": "planned",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "dataset": {"path": str(args.photos), "pairCount": len(images)},
        "command": command,
        "tool": {"name": "index", "backend": "mere.run/vision-face-batch"},
        "settings": {
            "model": args.model,
            "executionProvider": args.execution_provider,
            "scoreThreshold": args.score_threshold,
            "batchSize": args.batch_size,
            "extensions": sorted(args.extensions),
            "limit": args.limit,
            "mereRunCommand": args.mere_run_command,
        },
        "local": {
            "runManifest": str(manifest_path),
            "outputDirectory": str(args.output_dir),
            "database": str(args.database),
        },
        "artifacts": {"database": str(args.database)},
        "progress": {"discovered": len(images), "pending": len(images), "processed": 0, "errors": 0},
        "cleanup": {"default": "none", "status": "not-started"},
    }


def update_manifest(path: pathlib.Path, manifest: JsonMap, status: str | None = None) -> None:
    if status is not None:
        manifest["status"] = status
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def manifest_settings(manifest: JsonMap) -> tuple[JsonMap, JsonMap]:
    return as_map(manifest["settings"], "settings"), as_map(manifest["local"], "local")


def chunked(values: list[pathlib.Path], size: int) -> list[list[pathlib.Path]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def execute_index(manifest_path: pathlib.Path, manifest: JsonMap) -> JsonMap:
    settings, local = manifest_settings(manifest)
    photos = pathlib.Path(str(as_map(manifest["dataset"], "dataset")["path"]))
    database = pathlib.Path(str(local["database"]))
    output_dir = pathlib.Path(str(local["outputDirectory"]))
    extensions = set(str(item) for item in cast(list[object], settings["extensions"]))
    limit_value = settings.get("limit")
    limit = int(limit_value) if isinstance(limit_value, int) else None
    images = scan_images(photos, extensions, limit)
    connection = connect(database)
    pending = [path for path in images if photo_needs_index(connection, path)]
    set_metadata(connection, [
        ("model_id", str(settings["model"])),
        ("source_root", str(photos)),
        ("updated_at", now_iso()),
    ])
    progress = as_map(manifest["progress"], "progress")
    progress.update({"discovered": len(images), "pending": len(pending), "processed": 0, "errors": 0})
    update_manifest(manifest_path, manifest, "running")
    work_dir = output_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    mere_run = split_command(str(settings["mereRunCommand"]))
    batch_size = as_int(settings["batchSize"], "settings.batchSize")
    processed = 0
    errors = 0
    try:
        for chunk_index, paths in enumerate(chunked(pending, batch_size), start=1):
            input_list = work_dir / f"chunk-{chunk_index:06d}.txt"
            jsonl_output = work_dir / f"chunk-{chunk_index:06d}.jsonl"
            input_list.write_text("".join(str(path) + "\n" for path in paths))
            command = [
                *mere_run,
                "vision",
                "face",
                "batch",
                "--input-list",
                str(input_list),
                "--include-embeddings",
                "--model",
                str(settings["model"]),
                "--execution-provider",
                str(settings["executionProvider"]),
                "--score-threshold",
                str(settings["scoreThreshold"]),
                "--jsonl-output",
                str(jsonl_output),
            ]
            completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
                raise PluginError(f"mere.run face batch failed: {detail}", 1)
            records = [json.loads(line) for line in jsonl_output.read_text().splitlines() if line.strip()]
            seen: set[pathlib.Path] = set()
            for record in records:
                image_path = pathlib.Path(str(record.get("image", ""))).resolve()
                if image_path not in paths:
                    raise PluginError(f"batch returned an unexpected image path: {image_path}")
                seen.add(image_path)
                if record.get("ok") is True and isinstance(record.get("result"), dict):
                    store_result(connection, image_path, record["result"], now_iso())
                else:
                    store_error(connection, image_path, str(record.get("error") or "unknown inference error"), now_iso())
                    errors += 1
                processed += 1
            for missing in set(paths) - seen:
                store_error(connection, missing, "batch emitted no record", now_iso())
                processed += 1
                errors += 1
            progress.update({"processed": processed, "errors": errors, "pending": max(0, len(pending) - processed)})
            manifest["artifacts"] = {"database": str(database), "stats": stats(connection)}
            update_manifest(manifest_path, manifest)
            eprint(json.dumps({"event": "progress", **progress}, sort_keys=True))
        manifest["artifacts"] = {"database": str(database), "stats": stats(connection)}
        update_manifest(manifest_path, manifest, "succeeded")
    except Exception as exc:
        manifest["error"] = str(exc)
        manifest["artifacts"] = {"database": str(database), "stats": stats(connection)}
        update_manifest(manifest_path, manifest, "failed")
        raise
    finally:
        connection.close()
    return manifest


def cosine(lhs: list[float], rhs: tuple[float, ...]) -> float:
    return sum(left * right for left, right in zip(lhs, rhs))


def reference_embedding(args: argparse.Namespace) -> tuple[list[float], int]:
    command = [
        *split_command(args.mere_run_command),
        "vision",
        "face",
        "embed",
        str(args.reference),
        "--model",
        args.model,
        "--execution-provider",
        args.execution_provider,
        "--score-threshold",
        str(args.score_threshold),
        "--json",
    ]
    if args.reference_face_index is not None:
        command.extend(["--face-index", str(args.reference_face_index)])
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise PluginError(completed.stderr.strip() or "mere.run face embed failed", 1)
    payload = json.loads(completed.stdout)
    face = as_map(payload["face"], "reference face")
    embedding = face.get("embedding")
    if not isinstance(embedding, list) or len(embedding) != 512:
        raise PluginError("reference face did not produce a 512-dimensional embedding")
    return [float(value) for value in embedding], as_int(face["index"], "reference face index")


def classify(score: float, strong: float, likely: float, review: float) -> str | None:
    if score >= strong:
        return "strong"
    if score >= likely:
        return "likely"
    if score >= review:
        return "review"
    return None


def export_symlink(source: pathlib.Path, destination: pathlib.Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or destination.exists():
        destination.unlink()
    destination.symlink_to(source)


def render_contact_sheet(matches: list[dict[str, object]], output: pathlib.Path) -> None:
    if not matches:
        return
    columns = 4
    cell_width, cell_height = 280, 230
    rows = math.ceil(len(matches) / columns)
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, match in enumerate(matches):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        try:
            image = ImageOps.exif_transpose(Image.open(str(match["path"])).convert("RGB"))
            image = ImageOps.contain(image, (cell_width - 12, cell_height - 42))
            canvas.paste(image, (x + (cell_width - image.width) // 2, y + 4))
        except Exception:
            draw.rectangle((x + 4, y + 4, x + cell_width - 4, y + cell_height - 38), fill="#dddddd")
        score = as_float(match["score"], "match score")
        label = f"#{match['rank']} {score:.3f} {pathlib.Path(str(match['path'])).name}"
        draw.text((x + 6, y + cell_height - 31), label[:44], fill="black", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=90)


def command_search(args: argparse.Namespace) -> int:
    if not args.database.is_file():
        raise PluginError(f"face database does not exist: {args.database}", 2)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    embedding, reference_index = reference_embedding(args)
    connection = connect(args.database)
    best_by_photo: dict[str, dict[str, object]] = {}
    for face in iter_face_embeddings(connection):
        score = cosine(embedding, cast(tuple[float, ...], face["embedding"]))
        path = str(face["path"])
        current = best_by_photo.get(path)
        if current is None or score > as_float(current["score"], "stored match score"):
            best_by_photo[path] = {
                "path": path,
                "faceIndex": face["face_index"],
                "detectorScore": face["detector_score"],
                "boundingBox": face["bounding_box"],
                "score": score,
            }
    connection.close()
    ranked = sorted(best_by_photo.values(), key=lambda item: as_float(item["score"], "match score"), reverse=True)
    matches: list[dict[str, object]] = []
    for rank, item in enumerate(ranked[: args.top], start=1):
        category = classify(as_float(item["score"], "match score"), args.strong_threshold, args.likely_threshold, args.review_threshold)
        if category is None:
            continue
        item.update({"rank": rank, "category": category})
        matches.append(item)
        source = pathlib.Path(str(item["path"]))
        destination = args.output_dir / category / f"{rank:04d}-{source.name}"
        export_symlink(source, destination)
        item["exportPath"] = str(destination)

    payload = {
        "contractVersion": "mere.run/face-search.v1",
        "createdAt": now_iso(),
        "model": args.model,
        "database": str(args.database),
        "reference": str(args.reference),
        "referenceFaceIndex": reference_index,
        "thresholds": {
            "strong": args.strong_threshold,
            "likely": args.likely_threshold,
            "review": args.review_threshold,
        },
        "matches": matches,
        "counts": {
            category: sum(1 for item in matches if item["category"] == category)
            for category in ("strong", "likely", "review")
        },
    }
    json_path = args.output_dir / "matches.json"
    csv_path = args.output_dir / "matches.csv"
    write_json(json_path, payload)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "score", "category", "faceIndex", "path", "exportPath"])
        writer.writeheader()
        for match in matches:
            writer.writerow({key: match[key] for key in writer.fieldnames})
    contact_sheet = args.output_dir / "contact-sheet.jpg"
    render_contact_sheet(matches, contact_sheet)
    run_manifest = {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {"id": "face-library-search", "family": "face-analysis"},
        "status": "succeeded",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "dataset": {"path": str(args.database), "pairCount": max(1, len(best_by_photo))},
        "command": [PLUGIN_NAME, "search", "--database", str(args.database), "--reference", str(args.reference)],
        "tool": {"name": "search", "backend": "mere.run/vision-face-embed"},
        "artifacts": {
            "matchesJSON": str(json_path),
            "matchesCSV": str(csv_path),
            "contactSheet": str(contact_sheet) if contact_sheet.is_file() else None,
            "counts": payload["counts"],
        },
        "cleanup": {"default": "none", "status": "not-started"},
    }
    write_json(args.output_dir / "run.json", run_manifest)
    print_json(run_manifest)
    return 0


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    mere_run = split_command(args.mere_run_command)
    available = command_available(mere_run)
    face_help = False
    detail = shlex.join(mere_run)
    if available:
        completed = subprocess.run(
            [*mere_run, "vision", "face", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        face_help = completed.returncode == 0
        if not face_help:
            detail = completed.stderr.strip() or completed.stdout.strip() or detail
    checks = [
        {"name": "python", "ok": True, "detail": sys.version.split()[0]},
        {"name": "sqlite", "ok": sqlite3.sqlite_version_info >= (3, 24), "detail": sqlite3.sqlite_version},
        {"name": "mere.run vision face", "ok": available and face_help, "detail": detail},
    ]
    ok = all(bool(check["ok"]) for check in checks)
    print_json({"ok": ok, "checks": checks})
    return 0 if ok else 3


def command_plan(args: argparse.Namespace) -> int:
    manifest = index_manifest(args)
    write_json(args.output_dir / "run.json", manifest)
    print_json(manifest)
    return 0


def command_run(args: argparse.Namespace) -> int:
    manifest = as_map(json.loads(args.run_manifest.read_text()), "run manifest")
    if args.dry_run:
        print_json(manifest)
        return 0
    print_json(execute_index(args.run_manifest, manifest))
    return 0


def command_resume(args: argparse.Namespace) -> int:
    manifest = as_map(json.loads(args.run_manifest.read_text()), "run manifest")
    if args.inspect_only or manifest.get("status") == "succeeded":
        print_json(manifest)
        return 0
    print_json(execute_index(args.run_manifest, manifest))
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    manifest = as_map(json.loads(args.run_manifest.read_text()), "run manifest")
    cleanup = as_map(manifest.setdefault("cleanup", {"default": "none", "status": "not-started"}), "cleanup")
    cleanup.update({"status": "skipped", "reason": "local face runs create no remote resources; source photos remain untouched"})
    update_manifest(args.run_manifest, manifest)
    print_json(manifest)
    return 0


def command_index(args: argparse.Namespace) -> int:
    manifest = index_manifest(args)
    manifest_path = args.output_dir / "run.json"
    write_json(manifest_path, manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    print_json(execute_index(manifest_path, manifest))
    return 0


def add_index_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--photos", required=True, type=pathlib.Path, help="Photo-library directory to scan recursively.")
    parser.add_argument("--database", required=True, type=pathlib.Path, help="SQLite face-index path.")
    parser.add_argument("--output-dir", required=True, type=pathlib.Path, help="Durable run directory.")
    parser.add_argument("--model", default=MODEL_ID, help="Managed face model id or local model root.")
    parser.add_argument("--execution-provider", choices=["auto", "cpu", "coreml"], default="auto")
    parser.add_argument("--score-threshold", type=float, default=0.65)
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--extensions", nargs="+", default=sorted(IMAGE_EXTENSIONS))
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--mere-run-command", default="")


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if hasattr(args, "mere_run_command") and not args.mere_run_command:
        args.mere_run_command = os.environ.get("MERE_FACE_TOOLS_MERE_RUN") or DEFAULT_MERE_RUN
    for name in ("photos", "database", "output_dir", "reference", "run_manifest"):
        if hasattr(args, name) and getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).expanduser().resolve())
    if hasattr(args, "extensions"):
        args.extensions = [value.lower() if value.startswith(".") else "." + value.lower() for value in args.extensions]
    if hasattr(args, "batch_size") and args.batch_size <= 0:
        raise PluginError("--batch-size must be greater than zero", 2)
    if hasattr(args, "limit") and args.limit is not None and args.limit <= 0:
        raise PluginError("--limit must be greater than zero", 2)
    if hasattr(args, "score_threshold") and not 0 <= args.score_threshold <= 1:
        raise PluginError("--score-threshold must be between zero and one", 2)
    if hasattr(args, "top") and args.top <= 0:
        raise PluginError("--top must be greater than zero", 2)
    if hasattr(args, "reference") and not args.reference.is_file():
        raise PluginError(f"reference image does not exist: {args.reference}", 2)
    if hasattr(args, "strong_threshold"):
        thresholds = (args.strong_threshold, args.likely_threshold, args.review_threshold)
        if any(value < -1 or value > 1 for value in thresholds):
            raise PluginError("search thresholds must be between -1 and one", 2)
        if not args.strong_threshold >= args.likely_threshold >= args.review_threshold:
            raise PluginError("thresholds must satisfy strong >= likely >= review", 2)
    if hasattr(args, "run_id"):
        validate_run_id(args.run_id)
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME)
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check local face workflow readiness.")
    doctor.add_argument("--mere-run-command", default="")
    doctor.set_defaults(func=command_doctor)

    plan = sub.add_parser("plan", help="Create a face-library index plan.")
    add_index_args(plan)
    plan.set_defaults(func=command_plan)

    run = sub.add_parser("run", help="Execute a planned face-library index.")
    run.add_argument("run_manifest", type=pathlib.Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run)

    resume = sub.add_parser("resume", help="Continue an interrupted face-library index.")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.add_argument("--inspect-only", action="store_true")
    resume.set_defaults(func=command_resume)

    cleanup = sub.add_parser("cleanup", help="Mark local cleanup as skipped.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=command_cleanup)

    index = sub.add_parser("index", help="Plan and run a face-library index.")
    add_index_args(index)
    index.add_argument("--dry-run", action="store_true")
    index.set_defaults(func=command_index)

    search = sub.add_parser("search", help="Search a face database from a reference photo.")
    search.add_argument("--database", required=True, type=pathlib.Path)
    search.add_argument("--reference", required=True, type=pathlib.Path)
    search.add_argument("--output-dir", required=True, type=pathlib.Path)
    search.add_argument("--reference-face-index", type=int)
    search.add_argument("--top", type=int, default=300)
    search.add_argument("--strong-threshold", type=float, default=0.55)
    search.add_argument("--likely-threshold", type=float, default=0.45)
    search.add_argument("--review-threshold", type=float, default=0.35)
    search.add_argument("--model", default=MODEL_ID)
    search.add_argument("--execution-provider", choices=["auto", "cpu", "coreml"], default="auto")
    search.add_argument("--score-threshold", type=float, default=0.65)
    search.add_argument("--mere-run-command", default="")
    search.add_argument("--run-id", default=default_run_id("face-search"))
    search.set_defaults(func=command_search)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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

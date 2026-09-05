from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import re
import sqlite3
import sys
from collections import Counter
from typing import cast

from . import __version__, benchmark, database, extractors, pi_harness
from .runtime import InferenceError, MereRunClient, split_command

PLUGIN_NAME = "mere-archive-tools"
DEFAULT_MERE_RUN = "mere.run"
DEFAULT_EMBEDDING_MODEL = "vision-embed-qwen3-vl-2b"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
STORAGE_TIERS = ("full-content", "safe-content", "pointers")
IMAGE_INDEX_MODES = ("captions", "visual")
DEFAULT_CAPTION_PROMPT = (
    "Describe the visible people, objects, setting, activity, text, and distinguishing details "
    "for business archive search. Don't infer facts that aren't visible."
)
STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "because", "been", "before",
    "being", "between", "both", "but", "can", "could", "does", "each", "for", "from",
    "had", "has", "have", "into", "its", "more", "not", "only", "other", "our", "out",
    "over", "same", "should", "some", "such", "than", "that", "the", "their", "then",
    "there", "these", "they", "this", "through", "under", "was", "were", "what", "when",
    "where", "which", "while", "with", "would", "you", "your",
}
JsonMap = dict[str, object]


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def default_run_id() -> str:
    return "archive-index-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


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
    raise PluginError(f"{label} isn't an object")


def as_int(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise PluginError(f"{label} isn't an integer")


def as_float(value: object, label: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise PluginError(f"{label} isn't a number")


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise PluginError("invalid --run-id; use letters, digits, '.', '_', and '-'", 2)


def is_within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_output_boundary(source: pathlib.Path, database_path: pathlib.Path, output_dir: pathlib.Path) -> None:
    if is_within(database_path, source):
        raise PluginError("--database must be outside the read-only source tree", 2)
    if is_within(output_dir, source):
        raise PluginError("--output-dir must be outside the read-only source tree", 2)


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return "sha256:" + hasher.hexdigest()


def text_chunks(text: str, maximum_chars: int, overlap: int) -> list[str]:
    compact = text.strip()
    if not compact:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(compact):
        end = min(len(compact), start + maximum_chars)
        if end < len(compact):
            split = max(compact.rfind("\n", start, end), compact.rfind(" ", start, end))
            if split > start + maximum_chars // 2:
                end = split
        chunk = compact[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(compact):
            break
        start = max(start + 1, end - overlap)
    return chunks


def keywords(text: str, limit: int = 24) -> list[str]:
    terms = [
        value.lower()
        for value in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
        if value.lower() not in STOP_WORDS
    ]
    counts = Counter(terms)
    return [term for term, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def safe_summary(text: str, maximum_chars: int = 1_600) -> str:
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text) if part.strip()]
    selected: list[str] = []
    used = 0
    for paragraph in paragraphs:
        remaining = maximum_chars - used
        if remaining <= 0:
            break
        selected.append(paragraph[:remaining])
        used += len(selected[-1]) + 2
    return "\n\n".join(selected).strip()


def cosine(lhs: list[float], rhs: tuple[float, ...]) -> float:
    numerator = sum(left * right for left, right in zip(lhs, rhs))
    lhs_norm = math.sqrt(sum(value * value for value in lhs))
    rhs_norm = math.sqrt(sum(value * value for value in rhs))
    return numerator / (lhs_norm * rhs_norm) if lhs_norm and rhs_norm else 0.0


def snippet(text: str | None, maximum_chars: int = 360) -> str | None:
    if not text:
        return None
    compact = " ".join(text.split())
    return compact if len(compact) <= maximum_chars else compact[: maximum_chars - 1].rstrip() + "…"


def plugin_manifest() -> JsonMap:
    commands = [
        ("manifest", "Print the plugin manifest."),
        ("doctor", "Check local extraction, privacy, embedding, and SQLite readiness."),
        ("plan", "Create a durable shared-drive index plan."),
        ("run", "Execute a planned shared-drive index."),
        ("resume", "Continue an interrupted shared-drive index."),
        ("cleanup", "Record cleanup without changing the source or deleting the index."),
        ("index", "Plan and run a resumable shared-drive index."),
        ("search", "Search the archive with a PII-reduced text query."),
        ("investigate", "Answer a compound archive question with bounded, source-linked searches."),
        ("stats", "Report index coverage and retention settings."),
        ("benchmark", "Prepare, mutate, and evaluate archive benchmark datasets."),
    ]
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": PLUGIN_NAME,
        "description": "Build and search a local PII-reduced shared-drive index without modifying source files.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-archive-tools",
        "commands": [
            {"name": name, "description": description, "stdout": "json"}
            for name, description in commands
        ],
        "capabilities": [
            "archive-index",
            "shared-drive",
            "document-conversion",
            "captioning",
            "ocr",
            "pii-reduction",
            "multimodal-embeddings",
            "semantic-search",
            "full-text-search",
            "bounded-investigation",
            "pi-agent",
            "sqlite",
            "deduplication",
            "archive-benchmark",
        ],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": False,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def scan_source(source: pathlib.Path, limit: int | None) -> list[pathlib.Path]:
    try:
        files = extractors.scan_files(source, limit)
    except extractors.ExtractionError as exc:
        raise PluginError(str(exc), 2) from None
    if not files:
        raise PluginError(f"no supported files found under {source}", 2)
    return files


def index_manifest(args: argparse.Namespace) -> JsonMap:
    validate_output_boundary(args.source, args.database, args.output_dir)
    files = scan_source(args.source, args.limit)
    validate_run_id(args.run_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "run.json"
    command = [
        PLUGIN_NAME,
        "index",
        "--source",
        str(args.source),
        "--database",
        str(args.database),
        "--output-dir",
        str(args.output_dir),
        "--storage-tier",
        args.storage_tier,
        "--image-index",
        args.image_index,
        "--ocr-backend",
        args.ocr_backend,
        "--dimensions",
        str(args.dimensions),
        "--chunk-chars",
        str(args.chunk_chars),
        "--chunk-overlap",
        str(args.chunk_overlap),
        "--max-file-bytes",
        str(args.max_file_bytes),
        "--run-id",
        args.run_id,
    ]
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])
    command.append("--image-ocr" if args.image_ocr else "--no-image-ocr")
    command.append("--continue-on-error" if args.continue_on_error else "--no-continue-on-error")
    created = now_iso()
    return {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {"id": "shared-drive-index", "family": "local-archive-search"},
        "status": "planned",
        "createdAt": created,
        "updatedAt": created,
        "dataset": {"path": str(args.source), "pairCount": len(files)},
        "command": command,
        "tool": {
            "name": "index",
            "backend": "anydoc+mere.run+sqlite",
            "sourceAccess": "read-only",
        },
        "settings": {
            "storageTier": args.storage_tier,
            "imageIndex": args.image_index,
            "imageOcr": args.image_ocr,
            "ocrBackend": args.ocr_backend,
            "embeddingModel": DEFAULT_EMBEDDING_MODEL,
            "embeddingDimensions": args.dimensions,
            "chunkCharacters": args.chunk_chars,
            "chunkOverlap": args.chunk_overlap,
            "maxFileBytes": args.max_file_bytes,
            "replacement": args.replacement,
            "captionPrompt": args.caption_prompt,
            "continueOnError": args.continue_on_error,
            "limit": args.limit,
            "mereRunCommand": args.mere_run_command,
        },
        "privacy": {
            "piiReduction": "required-before-persistence",
            "rawDerivativeRetention": "none",
            "sourceMutation": "forbidden",
            "visualEmbedding": args.image_index == "visual",
        },
        "local": {
            "runManifest": str(manifest_path),
            "outputDirectory": str(args.output_dir),
            "database": str(args.database),
        },
        "artifacts": {"database": str(args.database)},
        "progress": {
            "discovered": len(files),
            "pending": len(files),
            "processed": 0,
            "skipped": 0,
            "deduplicated": 0,
            "errors": 0,
            "removed": 0,
        },
        "cleanup": {"default": "none", "status": "not-started"},
    }


def manifest_sections(manifest: JsonMap) -> tuple[JsonMap, JsonMap, JsonMap]:
    return (
        as_map(manifest["settings"], "settings"),
        as_map(manifest["local"], "local"),
        as_map(manifest["progress"], "progress"),
    )


def update_manifest(path: pathlib.Path, manifest: JsonMap, status: str | None = None) -> None:
    if status is not None:
        manifest["status"] = status
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def extract_file(
    path: pathlib.Path,
    client: MereRunClient,
    image_ocr: bool,
    ocr_backend: str,
    caption_prompt: str,
) -> tuple[str, str, str | None]:
    kind = extractors.file_kind(path)
    if kind != "image":
        return extractors.extract_text(path)
    caption = client.caption_image(path, caption_prompt).strip()
    ocr = client.ocr_image(path, ocr_backend).strip() if image_ocr else ""
    parts = []
    if caption:
        parts.append("Caption\n" + caption)
    if ocr:
        parts.append("Visible text\n" + ocr)
    if not parts:
        raise PluginError(f"image extraction returned no text for {path.name}")
    return "\n\n".join(parts), kind, None


def execute_index(manifest_path: pathlib.Path, manifest: JsonMap) -> JsonMap:
    settings, local, progress = manifest_sections(manifest)
    source = pathlib.Path(str(as_map(manifest["dataset"], "dataset")["path"])).expanduser().resolve()
    database_path = pathlib.Path(str(local["database"])).expanduser().resolve()
    output_dir = pathlib.Path(str(local["outputDirectory"])).expanduser().resolve()
    validate_output_boundary(source, database_path, output_dir)
    if is_within(manifest_path, source):
        raise PluginError("the run manifest must be outside the read-only source tree", 2)
    limit_value = settings.get("limit")
    limit = as_int(limit_value, "settings.limit") if limit_value is not None else None
    files = scan_source(source, limit)
    storage_tier = str(settings["storageTier"])
    image_index = str(settings["imageIndex"])
    dimensions = as_int(settings["embeddingDimensions"], "settings.embeddingDimensions")
    chunk_characters = as_int(settings["chunkCharacters"], "settings.chunkCharacters")
    chunk_overlap = as_int(settings["chunkOverlap"], "settings.chunkOverlap")
    max_file_bytes = as_int(settings["maxFileBytes"], "settings.maxFileBytes")
    connection = database.connect(database_path)
    try:
        database.configure(
            connection,
            [
                ("source_root", str(source)),
                ("storage_tier", storage_tier),
                ("image_index", image_index),
                ("embedding_model", str(settings["embeddingModel"])),
                ("embedding_dimensions", str(dimensions)),
                ("pii_policy", "required-before-persistence"),
            ],
        )
        pending = [path for path in files if database.file_needs_index(connection, path)]
        skipped = len(files) - len(pending)
        progress.update(
            {
                "discovered": len(files),
                "pending": len(pending),
                "processed": 0,
                "skipped": skipped,
                "deduplicated": 0,
                "errors": 0,
                "removed": 0,
            }
        )
        manifest.pop("error", None)
        update_manifest(manifest_path, manifest, "running")
        client = MereRunClient(
            str(settings["mereRunCommand"]),
            str(settings["replacement"]),
            str(settings["embeddingModel"]),
        )
        processed = 0
        errors = 0
        deduplicated = 0
        backend_versions: set[str] = set()
        continue_on_error = bool(settings["continueOnError"])
        for path in pending:
            kind = extractors.file_kind(path)
            relative_path = str(path.relative_to(source))
            initial_size = 0
            initial_mtime = 0
            try:
                initial_stat = path.stat()
                initial_size = initial_stat.st_size
                initial_mtime = initial_stat.st_mtime_ns
                if initial_stat.st_size > max_file_bytes:
                    raise PluginError(f"file exceeds --max-file-bytes: {path.name}")
                sha256 = file_sha256(path)
                hashed_stat = path.stat()
                if (
                    initial_stat.st_size != hashed_stat.st_size
                    or initial_stat.st_mtime_ns != hashed_stat.st_mtime_ns
                ):
                    raise PluginError(f"source file changed while it was hashed: {path.name}")
                content_id = database.content_id_for_sha(connection, sha256)
                if content_id is not None:
                    database.store_file_success(
                        connection,
                        path,
                        relative_path,
                        initial_size,
                        initial_mtime,
                        sha256,
                        kind,
                        content_id,
                        now_iso(),
                    )
                    deduplicated += 1
                else:
                    raw_text, extracted_kind, backend_version = extract_file(
                        path,
                        client,
                        bool(settings["imageOcr"]),
                        str(settings["ocrBackend"]),
                        str(settings["captionPrompt"]),
                    )
                    reduced_text = client.anonymize(raw_text)
                    del raw_text
                    if not reduced_text.strip():
                        raise PluginError(f"PII reduction returned no indexable text for {path.name}")
                    chunks = text_chunks(reduced_text, chunk_characters, chunk_overlap)
                    if not chunks:
                        raise PluginError(f"no indexable chunks were produced for {path.name}")
                    vectors = client.embed_texts(chunks, dimensions)
                    stored_chunks = [
                        (
                            index,
                            "text",
                            chunk if storage_tier == "full-content" else None,
                            vector,
                        )
                        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
                    ]
                    if extracted_kind == "image" and image_index == "visual":
                        stored_chunks.append((len(stored_chunks), "image", None, client.embed_image(path, dimensions)))
                    retained_keywords = keywords(reduced_text)
                    if storage_tier == "full-content":
                        display_text: str | None = reduced_text
                    elif storage_tier == "safe-content":
                        summary = safe_summary(reduced_text)
                        display_text = summary + (
                            "\n\nKeywords: " + ", ".join(retained_keywords)
                            if retained_keywords else ""
                        )
                    else:
                        display_text = None
                        retained_keywords = []
                    final_stat = path.stat()
                    if (
                        initial_stat.st_size != final_stat.st_size
                        or initial_stat.st_mtime_ns != final_stat.st_mtime_ns
                    ):
                        raise PluginError(f"source file changed during indexing: {path.name}")
                    content_id = database.store_content(
                        connection,
                        sha256,
                        extracted_kind,
                        storage_tier,
                        display_text,
                        retained_keywords if storage_tier != "pointers" else None,
                        stored_chunks,
                        now_iso(),
                    )
                    database.store_file_success(
                        connection,
                        path,
                        relative_path,
                        initial_size,
                        initial_mtime,
                        sha256,
                        kind,
                        content_id,
                        now_iso(),
                    )
                    if backend_version:
                        backend_versions.add(backend_version)
                processed += 1
            except Exception as exc:
                errors += 1
                processed += 1
                error_code = type(exc).__name__
                database.store_file_error(
                    connection,
                    path,
                    relative_path,
                    kind,
                    error_code,
                    now_iso(),
                    initial_size,
                    initial_mtime,
                )
                eprint(f"{relative_path}: {exc}")
                if not continue_on_error:
                    raise
            progress.update(
                {
                    "processed": processed,
                    "pending": max(0, len(pending) - processed),
                    "deduplicated": deduplicated,
                    "errors": errors,
                }
            )
            manifest["artifacts"] = {"database": str(database_path), "stats": database.stats(connection)}
            update_manifest(manifest_path, manifest)
            eprint(json.dumps({"event": "progress", **progress}, sort_keys=True))
        removed = (
            database.prune_missing_files(connection, {str(path) for path in files})
            if limit is None
            else 0
        )
        database.delete_orphan_contents(connection)
        progress["removed"] = removed
        manifest["artifacts"] = {
            "database": str(database_path),
            "stats": database.stats(connection),
            "anydocVersions": sorted(backend_versions),
        }
        update_manifest(manifest_path, manifest, "succeeded")
    except Exception as exc:
        manifest["error"] = type(exc).__name__
        manifest["artifacts"] = {"database": str(database_path), "stats": database.stats(connection)}
        update_manifest(manifest_path, manifest, "failed")
        raise
    finally:
        connection.close()
    return manifest


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def fts5_status() -> tuple[bool, str]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE archive_test USING fts5(body)")
        return True, sqlite3.sqlite_version
    except sqlite3.OperationalError as exc:
        return False, str(exc)
    finally:
        connection.close()


def command_doctor(args: argparse.Namespace) -> int:
    client = MereRunClient(args.mere_run_command, "[{label}]")
    fts_ok, fts_detail = fts5_status()
    anydoc_ok, anydoc_detail = extractors.anydoc_status()
    checks: list[dict[str, object]] = [
        {"name": "python", "ok": True, "detail": sys.version.split()[0]},
        {"name": "sqlite fts5", "ok": fts_ok, "detail": fts_detail},
        {"name": "anydoc", "ok": anydoc_ok, "detail": anydoc_detail},
    ]
    for name, arguments in (
        ("mere.run text anonymize", ["text", "anonymize"]),
        ("mere.run vision embed", ["vision", "embed"]),
        ("mere.run vision caption", ["vision", "caption"]),
        ("mere.run vision ocr", ["vision", "ocr"]),
    ):
        ok, detail = client.probe(arguments)
        checks.append({"name": name, "ok": ok, "detail": detail})
    ok = all(bool(check["ok"]) for check in checks)
    print_json({"ok": ok, "checks": checks})
    return 0 if ok else 3


def command_plan(args: argparse.Namespace) -> int:
    manifest = index_manifest(args)
    write_json(args.output_dir / "run.json", manifest)
    print_json(manifest)
    return 0


def load_manifest(path: pathlib.Path) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), "run manifest")
    except json.JSONDecodeError as exc:
        raise PluginError(f"invalid run manifest: {exc}", 2) from None


def command_run(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.run_manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    print_json(execute_index(args.run_manifest, manifest))
    return 0


def command_resume(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.run_manifest)
    if args.inspect_only or manifest.get("status") == "succeeded":
        print_json(manifest)
        return 0
    print_json(execute_index(args.run_manifest, manifest))
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.run_manifest)
    source = pathlib.Path(str(as_map(manifest["dataset"], "dataset")["path"])).expanduser().resolve()
    if is_within(args.run_manifest, source):
        raise PluginError("the run manifest must be outside the read-only source tree", 2)
    cleanup = as_map(manifest.setdefault("cleanup", {"default": "none", "status": "not-started"}), "cleanup")
    cleanup.update(
        {
            "status": "skipped",
            "reason": "the source is read-only and the local index requires an explicit deletion decision",
        }
    )
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


def search_database(
    database_path: pathlib.Path,
    query: str,
    top: int,
    replacement: str,
    mere_run_command: str,
) -> JsonMap:
    if not database_path.is_file():
        raise PluginError(f"archive database doesn't exist: {database_path}", 2)
    connection = database.connect(database_path)
    try:
        index_metadata = database.metadata(connection)
        dimensions = int(index_metadata["embedding_dimensions"])
        client = MereRunClient(
            mere_run_command,
            replacement,
            index_metadata["embedding_model"],
        )
        reduced_query = client.anonymize(query).strip()
        if not reduced_query:
            raise PluginError("PII reduction returned an empty query", 2)
        query_vector = client.embed_texts([reduced_query], dimensions)[0]
        lexical = database.lexical_content_ids(connection, reduced_query)
        best: dict[int, dict[str, object]] = {}
        for row in database.iter_embedding_rows(connection):
            content_id = as_int(row["content_id"], "content id")
            score = cosine(query_vector, cast(tuple[float, ...], row["embedding"]))
            combined = score + (0.15 if content_id in lexical else 0.0)
            current = best.get(content_id)
            if current is None or combined > as_float(current["score"], "search score"):
                best[content_id] = {
                    "contentId": content_id,
                    "score": combined,
                    "semanticScore": score,
                    "lexicalMatch": content_id in lexical,
                    "modality": row["modality"],
                    "kind": row["kind"],
                    "storageTier": row["storage_tier"],
                    "snippet": snippet(
                        str(row["chunk_text"])
                        if row["chunk_text"] is not None
                        else (str(row["display_text"]) if row["display_text"] is not None else None)
                    ),
                    "keywords": row["keywords"],
                }
        ranked = sorted(
            best.values(),
            key=lambda item: as_float(item["score"], "search score"),
            reverse=True,
        )[:top]
        for rank, item in enumerate(ranked, start=1):
            item["rank"] = rank
            item["paths"] = database.paths_for_content(connection, as_int(item["contentId"], "content id"))
        return {
            "contractVersion": "mere.run/archive-search.v1",
            "createdAt": now_iso(),
            "database": str(database_path),
            "query": reduced_query,
            "piiReductionApplied": True,
            "storageTier": index_metadata.get("storage_tier"),
            "results": ranked,
        }
    finally:
        connection.close()


def command_search(args: argparse.Namespace) -> int:
    if args.output is not None and args.database.is_file():
        connection = database.connect(args.database)
        try:
            source_root = database.metadata(connection).get("source_root")
        finally:
            connection.close()
        if source_root is not None and is_within(args.output, pathlib.Path(source_root).expanduser().resolve()):
            raise PluginError("--output must be outside the read-only source tree", 2)
    payload = search_database(
        args.database,
        args.query,
        args.top,
        args.replacement,
        args.mere_run_command,
    )
    if args.output is not None:
        write_json(args.output, payload)
    print_json(payload)
    return 0


def command_investigate(args: argparse.Namespace) -> int:
    if args.output is not None and args.database.is_file():
        connection = database.connect(args.database)
        try:
            source_root = database.metadata(connection).get("source_root")
        finally:
            connection.close()
        if source_root is not None and is_within(args.output, pathlib.Path(source_root).expanduser().resolve()):
            raise PluginError("--output must be outside the read-only source tree", 2)
    config = pi_harness.InvestigationConfig(
        database=args.database,
        question=args.question,
        model=args.model,
        engine=args.engine,
        max_searches=args.max_searches,
        top=args.top,
        context_size=args.context_size,
        server_timeout_seconds=args.server_timeout,
        pi_timeout_seconds=args.pi_timeout,
        mere_run_command=args.mere_run_command,
        pi_command=args.pi_command,
        replacement=args.replacement,
    )
    pi_harness.validate_config(config)
    eprint(f"Investigating with {args.model}; the agent can run up to {args.max_searches} archive searches.")
    payload = pi_harness.investigate(config)
    if args.output is not None:
        write_json(args.output, payload)
    print_json(payload)
    return 0


def command_stats(args: argparse.Namespace) -> int:
    if not args.database.is_file():
        raise PluginError(f"archive database doesn't exist: {args.database}", 2)
    connection = database.connect(args.database)
    try:
        print_json(database.stats(connection))
        return 0
    finally:
        connection.close()


def command_benchmark_sources(args: argparse.Namespace) -> int:
    del args
    print_json(benchmark.source_catalog())
    return 0


def command_benchmark_prepare(args: argparse.Namespace) -> int:
    manifest = benchmark.prepare(args.dataset, args.output_dir, args.limit)
    phases = as_map(manifest["phases"], "benchmark phases")
    baseline = as_map(phases["baseline"], "benchmark baseline phase")
    dataset = as_map(manifest["dataset"], "benchmark dataset")
    print_json(
        {
            "contractVersion": benchmark.BENCHMARK_CONTRACT,
            "dataset": dataset,
            "manifest": str(args.output_dir / "benchmark.json"),
            "source": str(args.output_dir / "source"),
            "sourceFiles": len(cast(list[object], baseline["sourceFiles"])),
            "queries": len(cast(list[object], baseline["queries"])),
        }
    )
    return 0


def command_benchmark_mutate(args: argparse.Namespace) -> int:
    print_json(benchmark.mutate(args.benchmark_manifest))
    return 0


def command_benchmark_evaluate(args: argparse.Namespace) -> int:
    if not args.database.is_file():
        raise PluginError(f"archive database doesn't exist: {args.database}", 2)
    manifest = benchmark.load_manifest(args.benchmark_manifest)
    source = benchmark.source_root(args.benchmark_manifest, manifest)
    if args.output is not None and is_within(args.output, source):
        raise PluginError("--output must be outside the benchmark source tree", 2)

    def search(query: str, top: int) -> JsonMap:
        return search_database(
            args.database,
            query,
            top,
            args.replacement,
            args.mere_run_command,
        )

    report = benchmark.evaluate(
        args.benchmark_manifest,
        args.database,
        search,
        args.top,
        args.minimum_recall_at_5,
        args.minimum_mrr_at_10,
    )
    if args.output is not None:
        write_json(args.output, report)
    print_json(report)
    return 0 if report["passed"] is True else 4


def add_index_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", required=True, type=pathlib.Path, help="Shared-drive directory to scan recursively.")
    parser.add_argument("--database", required=True, type=pathlib.Path, help="SQLite archive-index path.")
    parser.add_argument("--output-dir", required=True, type=pathlib.Path, help="Durable run directory.")
    parser.add_argument("--storage-tier", choices=STORAGE_TIERS, default="safe-content")
    parser.add_argument("--image-index", choices=IMAGE_INDEX_MODES, default="captions")
    parser.add_argument("--image-ocr", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--ocr-backend", choices=["lighton", "glm", "infinity"], default="lighton")
    parser.add_argument("--dimensions", type=int, default=1_024)
    parser.add_argument("--chunk-chars", type=int, default=1_600)
    parser.add_argument("--chunk-overlap", type=int, default=160)
    parser.add_argument("--max-file-bytes", type=int, default=50 * 1024 * 1024)
    parser.add_argument("--replacement", default="[{label}]")
    parser.add_argument("--caption-prompt", default=DEFAULT_CAPTION_PROMPT)
    parser.add_argument("--continue-on-error", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--mere-run-command", default="")


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if hasattr(args, "mere_run_command") and not args.mere_run_command:
        args.mere_run_command = os.environ.get("MERE_ARCHIVE_TOOLS_MERE_RUN") or DEFAULT_MERE_RUN
    for name in ("source", "database", "output_dir", "run_manifest", "benchmark_manifest", "output"):
        if hasattr(args, name) and getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).expanduser().resolve())
    if hasattr(args, "run_id"):
        validate_run_id(args.run_id)
    if hasattr(args, "source") and not args.source.is_dir():
        raise PluginError(f"source directory doesn't exist: {args.source}", 2)
    if hasattr(args, "dimensions") and not 1 <= args.dimensions <= 2_048:
        raise PluginError("--dimensions must be between 1 and 2048", 2)
    if hasattr(args, "chunk_chars") and args.chunk_chars <= 0:
        raise PluginError("--chunk-chars must be greater than zero", 2)
    if hasattr(args, "chunk_overlap") and not 0 <= args.chunk_overlap < args.chunk_chars:
        raise PluginError("--chunk-overlap must be nonnegative and smaller than --chunk-chars", 2)
    if hasattr(args, "max_file_bytes") and args.max_file_bytes <= 0:
        raise PluginError("--max-file-bytes must be greater than zero", 2)
    if hasattr(args, "limit") and args.limit is not None and args.limit <= 0:
        raise PluginError("--limit must be greater than zero", 2)
    if hasattr(args, "top") and args.top <= 0:
        raise PluginError("--top must be greater than zero", 2)
    for name in ("minimum_recall_at_5", "minimum_mrr_at_10"):
        value = getattr(args, name, None)
        if value is not None and not 0.0 <= value <= 1.0:
            raise PluginError(f"--{name.replace('_', '-')} must be between 0 and 1", 2)
    if hasattr(args, "mere_run_command"):
        split_command(args.mere_run_command)
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME)
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print the plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check local archive-index readiness.")
    doctor.add_argument("--mere-run-command", default="")
    doctor.set_defaults(func=command_doctor)

    plan = sub.add_parser("plan", help="Create a shared-drive index plan.")
    add_index_args(plan)
    plan.set_defaults(func=command_plan)

    run = sub.add_parser("run", help="Execute a planned shared-drive index.")
    run.add_argument("run_manifest", type=pathlib.Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run)

    resume = sub.add_parser("resume", help="Continue an interrupted shared-drive index.")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.add_argument("--inspect-only", action="store_true")
    resume.set_defaults(func=command_resume)

    cleanup = sub.add_parser("cleanup", help="Record local cleanup as skipped.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=command_cleanup)

    index = sub.add_parser("index", help="Plan and run a shared-drive index.")
    add_index_args(index)
    index.add_argument("--dry-run", action="store_true")
    index.set_defaults(func=command_index)

    search = sub.add_parser("search", help="Search an archive database.")
    search.add_argument("--database", required=True, type=pathlib.Path)
    search.add_argument("--query", required=True)
    search.add_argument("--top", type=int, default=20)
    search.add_argument("--output", type=pathlib.Path)
    search.add_argument("--replacement", default="[{label}]")
    search.add_argument("--mere-run-command", default="")
    search.set_defaults(func=command_search)

    investigate = sub.add_parser(
        "investigate",
        help="Answer a compound archive question with a bounded local Pi search loop.",
    )
    investigate.add_argument("--database", required=True, type=pathlib.Path)
    investigate.add_argument("--question", required=True)
    investigate.add_argument("--model", default=pi_harness.DEFAULT_MODEL)
    investigate.add_argument("--engine", default=pi_harness.DEFAULT_ENGINE)
    investigate.add_argument("--max-searches", type=int, default=4)
    investigate.add_argument("--top", type=int, default=5)
    investigate.add_argument("--context-size", type=int, default=8_192)
    investigate.add_argument("--server-timeout", type=int, default=180)
    investigate.add_argument("--pi-timeout", type=int, default=180)
    investigate.add_argument("--output", type=pathlib.Path)
    investigate.add_argument("--replacement", default="[{label}]")
    investigate.add_argument("--mere-run-command", default="")
    investigate.add_argument("--pi-command", default=os.environ.get("MERE_ARCHIVE_TOOLS_PI", ""))
    investigate.set_defaults(func=command_investigate)

    stats = sub.add_parser("stats", help="Report archive database statistics.")
    stats.add_argument("--database", required=True, type=pathlib.Path)
    stats.set_defaults(func=command_stats)

    benchmark_parser = sub.add_parser("benchmark", help="Prepare and evaluate archive benchmarks.")
    benchmark_sub = benchmark_parser.add_subparsers(dest="benchmark_command", required=True)

    benchmark_sources = benchmark_sub.add_parser("sources", help="List pinned benchmark datasets.")
    benchmark_sources.set_defaults(func=command_benchmark_sources)

    benchmark_prepare = benchmark_sub.add_parser("prepare", help="Prepare a benchmark dataset.")
    benchmark_prepare.add_argument("--dataset", choices=benchmark.DATASET_IDS, default=benchmark.SYNTHETIC_DATASET_ID)
    benchmark_prepare.add_argument("--output-dir", required=True, type=pathlib.Path)
    benchmark_prepare.add_argument("--limit", type=int, default=100, help="Maximum ViDoRe rows to download.")
    benchmark_prepare.set_defaults(func=command_benchmark_prepare)

    benchmark_mutate = benchmark_sub.add_parser("mutate", help="Apply the generated fixture's change scenario.")
    benchmark_mutate.add_argument("benchmark_manifest", type=pathlib.Path)
    benchmark_mutate.set_defaults(func=command_benchmark_mutate)

    benchmark_evaluate = benchmark_sub.add_parser("evaluate", help="Score an archive database.")
    benchmark_evaluate.add_argument("benchmark_manifest", type=pathlib.Path)
    benchmark_evaluate.add_argument("--database", required=True, type=pathlib.Path)
    benchmark_evaluate.add_argument("--top", type=int, default=10)
    benchmark_evaluate.add_argument("--minimum-recall-at-5", type=float)
    benchmark_evaluate.add_argument("--minimum-mrr-at-10", type=float)
    benchmark_evaluate.add_argument("--output", type=pathlib.Path)
    benchmark_evaluate.add_argument("--replacement", default="[{label}]")
    benchmark_evaluate.add_argument("--mere-run-command", default="")
    benchmark_evaluate.set_defaults(func=command_benchmark_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args = normalize_args(args)
        return int(args.func(args))
    except (
        PluginError,
        benchmark.BenchmarkError,
        InferenceError,
        extractors.ExtractionError,
        pi_harness.InvestigationError,
        ValueError,
    ) as exc:
        eprint(f"Error: {exc}")
        if isinstance(exc, (PluginError, pi_harness.InvestigationError)):
            return exc.exit_code
        return 1
    except KeyboardInterrupt:
        eprint("Interrupted.")
        return 130
    except Exception as exc:
        eprint(f"Unexpected error: {exc}")
        return 1

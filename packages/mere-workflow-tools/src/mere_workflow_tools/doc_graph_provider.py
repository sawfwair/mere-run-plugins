"""Portable AnyDoc conversion using the existing graph and run contracts."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import tempfile
import time
import uuid
from typing import cast

from . import __version__, anydoc_backend
from .graph_sdk import (
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
    now_iso,
    relative_path,
    validate_catalog,
)
from .graph_sdk import load_invocation as load_graph_invocation

NODE_KIND = "document.convert"
PROVIDER_ID = "mere-doc-tools"
OUTPUT_TYPES = {"markdown": "asset", "manifest": "asset", "text": "string", "stats": "json"}


def requirements() -> JsonMap:
    return {
        "model_ids": [],
        "accelerator_backends": ["cpu", "metal", "cuda", "rocm"],
        "minimum_accelerator_memory_bytes": None,
        "network_access": False,
    }


def graph_catalog(provider_id: str, provider_version: str) -> JsonMap:
    catalog: JsonMap = {
        "contract_version": PROVIDER_CONTRACT_VERSION,
        "provider_id": provider_id,
        "provider_version": provider_version,
        "nodes": [{
            "kind": NODE_KIND,
            "title": "Convert a document to Markdown",
            "description": "Convert a local office document, CSV, EPUB, RTF, or text PDF with AnyDoc. Hosted OCR is disabled.",
            "category": "documents",
            "inputs": [{
                "name": "input", "type": "asset", "required": True,
                "description": "Local document file. Scanned PDFs require a separate local OCR workflow.",
            }],
            "outputs": [
                {"name": "markdown", "type": "asset", "optional": False, "content_types": ["text/markdown"]},
                {"name": "manifest", "type": "asset", "optional": False, "content_types": ["application/json"]},
                {"name": "text", "type": "string", "optional": False, "description": "Unredacted Markdown for downstream text nodes."},
                {"name": "stats", "type": "json", "optional": False, "description": "Input/output hashes, sizes, and AnyDoc version."},
            ],
            "requirements": requirements(),
            "traits": {
                "deterministic": True,
                # The separately installed AnyDoc patch version can change;
                # provider version alone is not a sufficient conversion cache key.
                "cacheable": False,
                "side_effects": "none",
                "supports_progress": True,
                "supports_previews": False,
            },
        }],
    }
    validate_catalog(catalog)
    return catalog


def load_invocation(path: pathlib.Path) -> JsonMap:
    return load_graph_invocation(path, {NODE_KIND})


def source_path(invocation: JsonMap) -> pathlib.Path:
    if invocation.get("contract_version") != INVOCATION_CONTRACT_VERSION or invocation.get("kind") != NODE_KIND:
        raise GraphProviderError("unsupported document conversion invocation")
    job_id, node_id = invocation.get("job_id"), invocation.get("node_id")
    if not isinstance(job_id, str) or not isinstance(node_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", node_id):
        raise GraphProviderError("document conversion requires a UUID job_id and a valid node_id")
    try:
        if str(uuid.UUID(job_id)) != job_id.lower():
            raise ValueError("noncanonical UUID")
    except ValueError:
        raise GraphProviderError("job_id must be a canonical UUID") from None
    arguments = as_map(invocation.get("arguments"), "arguments")
    if set(arguments) != {"input"}:
        raise GraphProviderError("document.convert accepts only the input document; hosted OCR is not supported")
    value = arguments["input"]
    if not isinstance(value, str) or not value:
        raise GraphProviderError("input must be a local document path")
    source = pathlib.Path(value).expanduser().resolve()
    if not source.is_file():
        raise GraphProviderError(f"input document is not a file: {source}")
    return source


def output_locations(invocation: JsonMap, run_directory: pathlib.Path) -> dict[str, pathlib.Path]:
    outputs = as_map(invocation.get("outputs"), "outputs")
    if set(outputs) != set(OUTPUT_TYPES):
        raise GraphProviderError(f"document.convert requires exactly these outputs: {', '.join(OUTPUT_TYPES)}")
    locations: dict[str, pathlib.Path] = {}
    for name, expected_type in OUTPUT_TYPES.items():
        descriptor = as_map(outputs[name], f"outputs.{name}")
        if descriptor.get("type") != expected_type or descriptor.get("optional", False) is not False:
            raise GraphProviderError(f"outputs.{name} must be a required {expected_type}")
        raw_path = descriptor.get("path")
        if expected_type != "asset":
            if raw_path is not None:
                raise GraphProviderError(f"outputs.{name} is an inline value and must not declare a path")
            continue
        if not isinstance(raw_path, str) or "\\" in raw_path or pathlib.PurePosixPath(raw_path).as_posix() != raw_path:
            raise GraphProviderError(f"outputs.{name}.path must be a canonical relative path")
        path = confined_path(run_directory, raw_path)
        if path.exists() and not path.is_file():
            raise GraphProviderError(f"outputs.{name} is not a file path")
        locations[name] = path
    paths = list(locations.values())
    if paths[0] == paths[1] or paths[0] in paths[1].parents or paths[1] in paths[0].parents:
        raise GraphProviderError("document output paths must be distinct files")
    if all(path.exists() for path in paths) and paths[0].samefile(paths[1]):
        raise GraphProviderError("document outputs must not alias the same file")
    return locations


def validate_source_outputs(source: pathlib.Path, locations: dict[str, pathlib.Path]) -> None:
    for path in locations.values():
        if path == source or (path.exists() and path.samefile(source)):
            raise GraphProviderError("document outputs must not overwrite the input document")


def graph_preflight(invocation: JsonMap, run_directory: pathlib.Path) -> JsonMap:
    diagnostics: list[JsonMap] = []
    try:
        source = source_path(invocation)
        locations = output_locations(invocation, run_directory)
        validate_source_outputs(source, locations)
    except (GraphProviderError, OSError) as exc:
        diagnostics.append(diagnostic("document_invalid", "blocker", "Document invocation is invalid", str(exc)))
    try:
        anydoc_backend.load_backend()
    except anydoc_backend.AnyDocError as exc:
        diagnostics.append(diagnostic("anydoc_unavailable", "blocker", "AnyDoc is unavailable", str(exc)))
    return {
        "contract_version": PREFLIGHT_CONTRACT_VERSION,
        "status": "blocked" if diagnostics else "ok",
        "diagnostics": diagnostics,
        "requirements": requirements(),
    }


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def write_manifest(path: pathlib.Path, manifest: JsonMap) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["updatedAt"] = now_iso()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = pathlib.Path(handle.name)
        try:
            handle.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            handle.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def graph_execute(invocation: JsonMap, run_directory: pathlib.Path, write_event: EventWriter) -> None:
    preflight = graph_preflight(invocation, run_directory)
    if preflight["status"] != "ok":
        messages = [str(item["message"]) for item in cast(list[JsonMap], preflight["diagnostics"])]
        raise GraphProviderError(" ".join(messages))
    started = time.monotonic()
    source = source_path(invocation)
    locations = output_locations(invocation, run_directory)
    validate_source_outputs(source, locations)
    markdown_path, manifest_path = locations["markdown"], locations["manifest"]
    input_hash = file_sha256(source)
    manifest: JsonMap = {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": f"{invocation['job_id']}-{invocation['node_id']}",
        "plugin": {"name": PROVIDER_ID, "version": __version__},
        "recipe": {"id": "doc-anydoc-markdown", "family": "local-workflow"},
        "status": "running", "createdAt": now_iso(),
        "dataset": {"path": str(source.parent), "pairCount": 1, "sha256": input_hash},
        "command": [PROVIDER_ID, "run", str(manifest_path)],
        "local": {"input": str(source), "outputDirectory": str(run_directory.resolve()), "runManifest": str(manifest_path)},
        "tool": {"name": PROVIDER_ID, "backend": "anydoc", "workflow": "markdown-redact", "redact": False, "mereRunCommand": ["mere.run"]},
        "steps": [{"name": "convert-markdown", "python": "anydoc-markdown", "inputs": [str(source)], "outputs": {"markdown": str(markdown_path)}}],
        "artifacts": {"localDirectory": str(run_directory.resolve()), "files": [], "sha256": {}},
        "cleanup": {"default": "none", "status": "not-started"},
    }
    write_manifest(manifest_path, manifest)
    events = GraphEventStream(write_event)
    events.emit("progress", message="Converting document locally", progress={"phase": "convert", "current": 0, "total": 1})
    try:
        backend_version = anydoc_backend.convert(source, markdown_path)
        if file_sha256(source) != input_hash:
            raise GraphProviderError("input document changed during conversion; create a new run with a stable input")
        text = markdown_path.read_text(encoding="utf-8")
        markdown_hash = file_sha256(markdown_path)
        as_map(manifest["tool"], "tool")["backendVersion"] = backend_version
        manifest["artifacts"] = {
            "localDirectory": str(run_directory.resolve()), "files": [str(markdown_path)],
            "sha256": {str(markdown_path): markdown_hash},
        }
        manifest["status"] = "succeeded"
        write_manifest(manifest_path, manifest)
    except (anydoc_backend.AnyDocError, GraphProviderError, OSError) as exc:
        manifest.update({"status": "failed", "error": str(exc)})
        write_manifest(manifest_path, manifest)
        events.emit("diagnostic", diagnostic=diagnostic("document_conversion_failed", "blocker", "Document conversion failed", str(exc)))
        raise GraphProviderError(str(exc)) from None
    for name, content_type in (("markdown", "text/markdown"), ("manifest", "application/json")):
        events.emit("artifact_ready", artifact={"name": name, "path": relative_path(locations[name], run_directory), "content_type": content_type})
    events.emit("progress", progress={"phase": "convert", "current": 1, "total": 1})
    events.emit("metric", metric={"name": "duration", "value": time.monotonic() - started, "unit": "seconds"})
    events.emit("node_result", outputs={
        "markdown": relative_path(markdown_path, run_directory),
        "manifest": relative_path(manifest_path, run_directory),
        "text": text,
        "stats": {"input_sha256": input_hash, "markdown_sha256": markdown_hash, "byte_count": markdown_path.stat().st_size, "backend_version": backend_version},
    })

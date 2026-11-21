"""Local document extraction and optional review-only classification."""
from __future__ import annotations

import csv
import io
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from .graph_sdk import GraphProviderError, JsonMap, as_map

CLAIRIC_MODEL = "text-extract-clairic-flash-bf16"
CLASSIFIER_MODEL = "text-classify-gliner25-decide"
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp", ".heic", ".heif"}
TEXT_TYPES = {".txt", ".md", ".csv", ".json", ".jsonl"}
FIELD_TYPES = {"text", "number", "boolean", "enum", "object", "list"}


@dataclass(frozen=True)
class Extraction:
    source: pathlib.Path
    fields: JsonMap
    model: str
    tasks: list[JsonMap]
    classifier: str

    def request(self) -> JsonMap:
        if not self.source.is_file():
            raise GraphProviderError("The input document must be a local file.")
        if self.source.stat().st_size > 4 * 1024 * 1024:
            raise GraphProviderError("Structured extraction accepts input files up to 4 MiB.")
        if not self.fields or any(
            not name.strip() or name in {"mere.needs_review", "mere.classification"}
            or as_map(spec, name).get("type") not in FIELD_TYPES
            for name, spec in self.fields.items()
        ):
            raise GraphProviderError("Use a nonempty map of named Clairic field definitions.")
        task_names = [task.get("name") for task in self.tasks]
        if len(task_names) > 16 or any(not isinstance(name, str) or not name.strip() for name in task_names):
            raise GraphProviderError("Supply up to 16 named GLiNER classification tasks.")
        if len(set(task_names)) != len(task_names):
            raise GraphProviderError("GLiNER classification task names must be unique.")
        suffix = self.source.suffix.lower()
        if suffix == ".pdf":
            return {"fields": self.fields, "documents": [str(self.source)]}
        if suffix in IMAGE_TYPES:
            return {"fields": self.fields, "images": [str(self.source)]}
        if suffix in TEXT_TYPES:
            text = self.source.read_text(encoding="utf-8")
            if not text.strip():
                raise GraphProviderError("The input document is empty.")
            return {"fields": self.fields, "state": text}
        raise GraphProviderError("Choose a PDF, image, or UTF-8 text file for structured extraction.")


def runtime_command() -> list[str]:
    override = os.environ.get("MERE_WORKFLOW_TOOLS_MERE_RUN")
    if override:
        return shlex.split(override)
    executable = os.environ.get("MERE_RUN_EXECUTABLE") or shutil.which("mere.run")
    if executable:
        return [executable]
    mac_app = pathlib.Path("/Applications/MereRun.app/Contents/Helpers/mere.run")
    return [str(mac_app)] if mac_app.is_file() else ["mere.run"]


def read_tasks(value: object) -> list[JsonMap]:
    if not isinstance(value, list):
        raise GraphProviderError("GLiNER tasks must be a JSON array.")
    return [as_map(task, "classification task") for task in value]


def native_request(command: list[str], verb: str, model: str, request: JsonMap, *, preflight: bool = False) -> JsonMap:
    args = [*command, "text", verb, "--model", model, "--input", "-"]
    if preflight:
        args.append("--preflight")
    try:
        process = subprocess.run(args, input=json.dumps(request), text=True, capture_output=True, check=False)
    except OSError as exc:
        raise GraphProviderError(f"Could not launch mere.run for {verb}: {exc.strerror}") from exc
    if process.returncode:
        raise GraphProviderError(
            f"mere.run text {verb} exited with status {process.returncode}. "
            f"Check that the runtime supports {model} and that its model is installed."
        )
    try:
        return as_map(json.loads(process.stdout), f"{verb} response")
    except (ValueError, GraphProviderError) as exc:
        raise GraphProviderError(f"mere.run text {verb} did not return a JSON object.") from exc


def csv_cell(value: object) -> object:
    if isinstance(value, str):
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")) else value
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def extract(command: list[str], job: Extraction, review_path: pathlib.Path, csv_path: pathlib.Path) -> JsonMap:
    if review_path == csv_path or any(job.source == path.resolve() or (
        path.exists() and path.samefile(job.source)
    ) for path in (review_path, csv_path)):
        raise GraphProviderError("Document outputs must be separate files and preserve the input.")
    response = native_request(command, "extract", job.model, job.request())
    answers = as_map(response.get("answers"), "Clairic answers")
    values: JsonMap = {}
    needs_review: list[str] = []
    for name in job.fields:
        answer = as_map(answers.get(name, {}), f"answer {name}")
        if response.get("truncated") is False and answer.get("valid") is True and answer.get("complete") is True:
            values[name] = answer.get("value")
        else:
            values[name] = None
            needs_review.append(name)
    classification = None
    if job.tasks and not needs_review and any(value is not None for value in values.values()):
        classification = native_request(command, "classify", job.classifier, {
            "text": json.dumps(values, ensure_ascii=False), "tasks": job.tasks,
        })
        as_map(classification.get("heads"), "GLiNER heads")
    review: JsonMap = {
        "values": values, "needs_review": needs_review, "extraction": response,
        "classification": classification,
        "classification_status": "completed" if classification else "awaiting_review" if job.tasks else "not_requested",
    }
    csv_text = io.StringIO(newline="")
    writer = csv.writer(csv_text)
    writer.writerow([*(csv_cell(key) for key in values), "mere.needs_review", "mere.classification"])
    writer.writerow([*(csv_cell(value) for value in values.values()), csv_cell(needs_review),
                     csv_cell(classification.get("heads") if classification else None)])
    for path, contents in (
        (review_path, json.dumps(review, indent=2, ensure_ascii=False) + "\n"),
        (csv_path, csv_text.getvalue()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
            temporary = pathlib.Path(handle.name)
        try:
            with temporary.open("w", encoding="utf-8", newline="") as output:
                output.write(contents)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return review

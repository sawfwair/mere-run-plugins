"""Typed wrappers around the local mere.run command surfaces."""

from __future__ import annotations

import json
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import cast

JsonMap = dict[str, object]

EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])"
)
PHONE_PATTERN = re.compile(
    r"(?<![\w])(?:\+?1[\s.-]?)?(?:\([0-9]{3}\)|[0-9]{3})[\s.-][0-9]{3}[\s.-][0-9]{4}(?![\w])"
)


class InferenceError(RuntimeError):
    pass


def split_command(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise InferenceError(f"invalid mere.run command: {exc}") from None
    if not parts:
        raise InferenceError("mere.run command is empty")
    return parts


def command_available(command: list[str]) -> bool:
    executable = pathlib.Path(command[0]).expanduser()
    return executable.is_file() or shutil.which(command[0]) is not None


def privacy_chunks(text: str, maximum_chars: int = 3_000) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + maximum_chars)
        if end < len(text):
            split = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if split > start:
                end = split + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def reduce_common_identifiers(text: str, replacement: str) -> str:
    email_replacement = replacement.replace("{label}", "private_email").replace("{index}", "1")
    phone_replacement = replacement.replace("{label}", "private_phone").replace("{index}", "1")
    reduced = EMAIL_PATTERN.sub(email_replacement, text)
    return PHONE_PATTERN.sub(phone_replacement, reduced)


def as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    raise InferenceError(f"{label} isn't an object")


def as_list(value: object, label: str) -> list[object]:
    if isinstance(value, list):
        return value
    raise InferenceError(f"{label} isn't a list")


class MereRunClient:
    def __init__(self, command: str, replacement: str, embedding_model: str | None = None) -> None:
        self.command = split_command(command)
        self.replacement = replacement
        self.embedding_model = embedding_model

    def _run(self, arguments: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        if not command_available(self.command):
            raise InferenceError(
                f"mere.run command not found: {self.command[0]}. Install mere.run or pass --mere-run-command."
            )
        return subprocess.run(
            [*self.command, *arguments],
            input=stdin,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def probe(self, arguments: list[str]) -> tuple[bool, str]:
        if not command_available(self.command):
            return False, f"command not found: {self.command[0]}"
        completed = self._run([*arguments, "--help"])
        detail = shlex.join([*self.command, *arguments])
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or detail
        return completed.returncode == 0, detail

    def anonymize(self, text: str) -> str:
        reduced: list[str] = []
        for chunk in privacy_chunks(text):
            completed = self._run(
                ["text", "anonymize", "--replacement", self.replacement],
                stdin=chunk,
            )
            if completed.returncode != 0:
                raise InferenceError(f"PII reduction failed with exit {completed.returncode}")
            reduced.append(completed.stdout.rstrip("\n"))
        return reduce_common_identifiers("".join(reduced), self.replacement)

    def caption_image(self, path: pathlib.Path, prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="mere-archive-caption-") as temporary:
            output_dir = pathlib.Path(temporary)
            completed = self._run(
                [
                    "vision",
                    "caption",
                    "--output-dir",
                    str(output_dir),
                    "--prompt",
                    prompt,
                    str(path),
                ]
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or f"exit {completed.returncode}"
                raise InferenceError(f"image captioning failed: {detail}")
            caption_path = output_dir / f"{path.stem}.txt"
            if not caption_path.is_file():
                raise InferenceError("image captioning didn't produce a caption file")
            return caption_path.read_text(encoding="utf-8")

    def ocr_image(self, path: pathlib.Path, backend: str) -> str:
        completed = self._run(
            ["vision", "ocr", "--backend", backend, "--quiet", str(path)]
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit {completed.returncode}"
            raise InferenceError(f"image OCR failed: {detail}")
        return completed.stdout.rstrip("\n")

    def embed_texts(self, texts: list[str], dimensions: int) -> list[list[float]]:
        records: list[JsonMap] = [
            {
                "id": f"text-{index}",
                "text": text,
                "instruction": "Retrieve shared-drive material relevant to the search query.",
            }
            for index, text in enumerate(texts)
        ]
        return self._embed(records, dimensions)

    def embed_image(self, path: pathlib.Path, dimensions: int) -> list[float]:
        records: list[JsonMap] = [{"id": "image-0", "image": str(path)}]
        vectors = self._embed(records, dimensions)
        if len(vectors) != 1:
            raise InferenceError("visual embedding returned an unexpected vector count")
        return vectors[0]

    def _embed(self, records: list[JsonMap], dimensions: int) -> list[list[float]]:
        arguments = ["vision", "embed", "--input-json", "-", "--dimensions", str(dimensions)]
        if self.embedding_model is not None:
            arguments.extend(["--model", self.embedding_model])
        completed = self._run(
            arguments,
            stdin=json.dumps({"inputs": records}),
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or f"exit {completed.returncode}"
            raise InferenceError(f"embedding failed: {detail}")
        try:
            payload = as_map(json.loads(completed.stdout), "embedding response")
            data = as_list(payload["data"], "embedding response data")
        except (json.JSONDecodeError, KeyError) as exc:
            raise InferenceError("embedding returned invalid JSON") from exc
        vectors: list[list[float]] = []
        for raw_item in data:
            item = as_map(raw_item, "embedding item")
            vector = item.get("embedding")
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise InferenceError(f"embedding item doesn't contain {dimensions} values")
            vectors.append([float(value) for value in vector])
        if len(vectors) != len(records):
            raise InferenceError("embedding returned an unexpected vector count")
        return vectors

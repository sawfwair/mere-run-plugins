from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import tempfile
from typing import NoReturn, cast

JsonMap = dict[str, object]
JsonList = list[object]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def fail(message: str) -> NoReturn:
    raise PluginError(message, 2)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    fail(f"{label}: expected object")


def as_list(value: object, label: str) -> JsonList:
    if isinstance(value, list):
        return value
    fail(f"{label}: expected array")


def as_string(value: object, label: str) -> str:
    if isinstance(value, str) and value:
        return value
    fail(f"{label}: expected non-empty string")


def as_int(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    fail(f"{label}: expected integer")


def as_number(value: object, label: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    fail(f"{label}: expected number")


def optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def load_json(path: pathlib.Path) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), f"JSON file {path}")
    except FileNotFoundError:
        raise PluginError(f"missing JSON file: {path}", 2) from None
    except json.JSONDecodeError as exc:
        raise PluginError(f"invalid JSON in {path}: {exc}", 2) from None


def write_json(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def object_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def slug(value: str, fallback: str = "film") -> str:
    normalized = SLUG_PATTERN.sub("-", value.lower()).strip("-")
    return normalized[:64] or fallback


def validate_run_id(value: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(value):
        raise PluginError(
            "--run-id must start with a letter or digit and contain only letters, digits, '.', '_', or '-'",
            2,
        )


def relative_or_absolute(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())

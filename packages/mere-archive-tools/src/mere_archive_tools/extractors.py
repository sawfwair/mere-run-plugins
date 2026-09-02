"""Read source files without writing derived content beside them."""

from __future__ import annotations

import importlib
import pathlib
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Literal, Protocol, cast

TEXT_EXTENSIONS = {
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".rst",
    ".text",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
DOCUMENT_EXTENSIONS = {".csv", ".docx", ".epub", ".pdf", ".pptx", ".rtf", ".xlsx"}
IMAGE_EXTENSIONS = {".bmp", ".heic", ".heif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS
ANYDOC_DISTRIBUTION = "firecrawl-anydoc"


class ExtractionError(RuntimeError):
    pass


class AnyDocAPI(Protocol):
    ConvertError: type[Exception]
    NeedsOcrError: type[Exception]

    def to_markdown(self, path: str, *, ocr: Literal["reject"]) -> str: ...


def scan_files(root: pathlib.Path, limit: int | None = None) -> list[pathlib.Path]:
    if not root.is_dir():
        raise ExtractionError(f"source directory doesn't exist: {root}")
    paths = [
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    paths.sort(key=lambda path: str(path).lower())
    return paths if limit is None else paths[:limit]


def file_kind(path: pathlib.Path) -> str:
    extension = path.suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in TEXT_EXTENSIONS:
        return "text"
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    raise ExtractionError(f"unsupported file extension: {extension or '(none)'}")


def anydoc_status() -> tuple[bool, str]:
    runtime_version = sys.version_info[:2]
    if runtime_version < (3, 10):
        return False, "Python 3.10 or later is required for AnyDoc document conversion"
    try:
        installed_version = version(ANYDOC_DISTRIBUTION)
        module = importlib.import_module("anydoc")
    except (ImportError, OSError, PackageNotFoundError) as exc:
        return False, f"AnyDoc is unavailable: {exc}"
    if not callable(getattr(module, "to_markdown", None)):
        return False, "the installed AnyDoc module doesn't provide to_markdown"
    return True, f"firecrawl-anydoc {installed_version}; hosted OCR is disabled"


def load_anydoc() -> tuple[AnyDocAPI, str]:
    ok, detail = anydoc_status()
    if not ok:
        raise ExtractionError(detail)
    module = importlib.import_module("anydoc")
    if not all(
        isinstance(getattr(module, name, None), type)
        and issubclass(getattr(module, name), Exception)
        for name in ("ConvertError", "NeedsOcrError")
    ):
        raise ExtractionError("the installed AnyDoc module has incompatible error types")
    return cast(AnyDocAPI, module), version(ANYDOC_DISTRIBUTION)


def extract_text(path: pathlib.Path) -> tuple[str, str, str | None]:
    kind = file_kind(path)
    if kind == "image":
        raise ExtractionError("image extraction requires the mere.run runtime")
    if kind == "text":
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise ExtractionError(f"text file isn't valid UTF-8: {path}") from exc
        if not text.strip():
            raise ExtractionError(f"text file is empty: {path}")
        return text, kind, None

    backend, installed_version = load_anydoc()
    try:
        markdown = backend.to_markdown(str(path), ocr="reject")
    except backend.NeedsOcrError as exc:
        raise ExtractionError(
            f"AnyDoc requires OCR for {path.name}. Hosted OCR is disabled; render the pages to images for local OCR."
        ) from exc
    except (backend.ConvertError, OSError, ValueError) as exc:
        raise ExtractionError(f"AnyDoc couldn't convert {path.name}: {type(exc).__name__}") from exc
    if not isinstance(markdown, str) or not markdown.strip():
        raise ExtractionError(f"AnyDoc returned no text for {path.name}")
    return markdown, kind, installed_version

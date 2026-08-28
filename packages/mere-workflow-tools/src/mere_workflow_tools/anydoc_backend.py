"""Local document conversion on Python 3.10+; hosted OCR is never enabled."""

from __future__ import annotations

import importlib
import pathlib
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Literal, Protocol, cast

DISTRIBUTION = "firecrawl-anydoc"
INSTALL_HELP = (
    "AnyDoc requires Python 3.10+ and is included with mere-workflow-tools on supported Python versions. "
    "Reinstall or upgrade Document Tools in a Python 3.10+ environment. "
    "For an older pipx installation already using Python 3.10+, run: "
    "pipx inject mere-workflow-tools 'firecrawl-anydoc>=0.2.4,<0.3'."
)


class AnyDocError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class AnyDocAPI(Protocol):
    ConvertError: type[Exception]
    NeedsOcrError: type[Exception]

    def to_markdown(self, path: str, *, ocr: Literal["reject"]) -> str: ...


def load_backend() -> tuple[AnyDocAPI, str]:
    runtime_version = sys.version_info[:2]
    if runtime_version < (3, 10):
        raise AnyDocError(INSTALL_HELP, 3)
    try:
        installed_version = version(DISTRIBUTION)
        module = importlib.import_module("anydoc")
    except (ImportError, OSError, PackageNotFoundError) as exc:
        raise AnyDocError(f"AnyDoc is unavailable: {exc}. {INSTALL_HELP}", 3) from None
    if not callable(getattr(module, "to_markdown", None)) or not all(
        isinstance(getattr(module, name, None), type)
        and issubclass(getattr(module, name), Exception)
        for name in ("ConvertError", "NeedsOcrError")
    ):
        raise AnyDocError(f"The installed anydoc module is incompatible. {INSTALL_HELP}", 3)
    return cast(AnyDocAPI, module), installed_version


def convert(input_path: pathlib.Path, output_path: pathlib.Path) -> str:
    """Write UTF-8 Markdown and return the backend version used for this run."""
    if input_path.resolve() == output_path.resolve() or (output_path.exists() and output_path.samefile(input_path)):
        raise AnyDocError("AnyDoc output must not overwrite the input document.", 2)
    backend, installed_version = load_backend()
    try:
        # Do not pass through credentials, environment policy, or manifest OCR
        # options. Scanned PDFs must fail locally, even when a key is present.
        markdown = backend.to_markdown(str(input_path), ocr="reject")
    except backend.NeedsOcrError as exc:
        raise AnyDocError(
            f"AnyDoc needs OCR: {exc}. Hosted OCR is disabled. "
            "Render scanned pages to images and process them with --extractor ocr."
        ) from None
    except (backend.ConvertError, OSError, ValueError) as exc:
        raise AnyDocError(f"AnyDoc conversion failed ({type(exc).__name__}): {exc}") from None
    if not isinstance(markdown, str) or not markdown.strip():
        raise AnyDocError("AnyDoc returned no Markdown; no output was written.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return installed_version

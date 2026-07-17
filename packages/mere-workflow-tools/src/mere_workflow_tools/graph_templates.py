from __future__ import annotations

import json
import pathlib
import shutil
from typing import cast

from .graph_sdk import GraphProviderError, JsonMap, as_list, as_map

TEMPLATE_ROOT = pathlib.Path(__file__).resolve().parent / "templates"


def catalog() -> JsonMap:
    return as_map(json.loads((TEMPLATE_ROOT / "catalog.v1.json").read_text()), "template catalog")


def template_path(template_id: str) -> pathlib.Path:
    entries = as_list(catalog().get("templates"), "template catalog.templates")
    matches = [as_map(item, "template") for item in entries if as_map(item, "template").get("id") == template_id]
    if len(matches) != 1:
        raise GraphProviderError(f"unknown graph template: {template_id}")
    relative = pathlib.PurePosixPath(cast(str, matches[0]["path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise GraphProviderError(f"graph template path is not confined: {relative}")
    path = (TEMPLATE_ROOT / pathlib.Path(*relative.parts)).resolve()
    if TEMPLATE_ROOT.resolve() not in path.parents or not path.is_file():
        raise GraphProviderError(f"graph template is missing: {template_id}")
    return path


def load_template(template_id: str) -> JsonMap:
    return as_map(json.loads(template_path(template_id).read_text()), f"graph template {template_id}")


def export_template(template_id: str, output: pathlib.Path) -> None:
    source = template_path(template_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(output)

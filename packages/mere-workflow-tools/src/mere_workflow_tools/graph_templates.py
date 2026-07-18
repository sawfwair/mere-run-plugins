from __future__ import annotations

import json
import pathlib
import re
import shutil
from typing import cast

from .graph_sdk import GraphProviderError, JsonMap, as_list, as_map

TEMPLATE_ROOT = pathlib.Path(__file__).resolve().parent / "templates"
TEMPLATE_PACKAGE_VERSION = "mere.run/graph-template-package.v1"
TEMPLATE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


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


def publish_template(
    graph: JsonMap,
    inputs: JsonMap,
    output_directory: pathlib.Path,
    template_id: str,
    title: str,
    description: str,
    tags: list[str],
) -> JsonMap:
    if TEMPLATE_ID_PATTERN.fullmatch(template_id) is None:
        raise GraphProviderError(f"invalid graph template id: {template_id}")
    if not title.strip() or not description.strip():
        raise GraphProviderError("graph template title and description are required")
    if graph.get("schema_version") != 1 or graph.get("kind") != "mere.run/workflow-graph":
        raise GraphProviderError("graph template must be a workflow graph v1")
    if any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        raise GraphProviderError("graph template tags must be non-empty strings")
    output_directory.mkdir(parents=True, exist_ok=True)
    graph_name = f"{template_id}.workflow.json"
    inputs_name = f"{template_id}.inputs.json"
    descriptor_name = f"{template_id}.template.json"
    graph_document = json.loads(json.dumps(graph))
    metadata = as_map(graph_document.setdefault("metadata", {}), "graph metadata")
    metadata["template_id"] = template_id
    write_json_atomic(output_directory / graph_name, graph_document)
    write_json_atomic(output_directory / inputs_name, inputs)
    descriptor: JsonMap = {
        "contract_version": TEMPLATE_PACKAGE_VERSION,
        "id": template_id,
        "title": title.strip(),
        "description": description.strip(),
        "tags": list(dict.fromkeys(tag.strip() for tag in tags)),
        "graph": graph_name,
        "inputs": inputs_name,
    }
    write_json_atomic(output_directory / descriptor_name, descriptor)
    return descriptor


def write_json_atomic(path: pathlib.Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)

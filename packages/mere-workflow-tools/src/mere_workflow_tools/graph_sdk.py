from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
from collections.abc import Callable, Mapping
from typing import cast

JsonMap = dict[str, object]
EventWriter = Callable[[JsonMap], None]

PROVIDER_CONTRACT_VERSION = "mere.run/plugin-graph-provider.v1"
INVOCATION_CONTRACT_VERSION = "mere.run/plugin-graph-invocation.v1"
PREFLIGHT_CONTRACT_VERSION = "mere.run/plugin-graph-preflight.v1"
EVENT_CONTRACT_VERSION = "mere.run/plugin-graph-event.v1"

PROVIDER_ID_PATTERN = re.compile(r"^mere-[a-z0-9-]+$")
NODE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}(\.[a-z][a-z0-9-]{0,63})+$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.-]+)?$")
SECRET_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
PORT_TYPES = {
    "string",
    "integer",
    "number",
    "boolean",
    "enum",
    "json",
    "asset",
    "asset_directory",
    "asset_collection",
}
VALUE_SCHEMA_TYPES = {"object", "array", "string", "integer", "number", "boolean", "enum", "json"}
VALUE_SCHEMA_KEYS = {
    "type",
    "title",
    "description",
    "default",
    "values",
    "properties",
    "required",
    "items",
    "additional_properties",
    "minimum",
    "maximum",
    "step",
    "multiline",
}


class GraphProviderError(RuntimeError):
    pass


def as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    raise GraphProviderError(f"{label} must be an object")


def as_list(value: object, label: str) -> list[object]:
    if isinstance(value, list):
        return value
    raise GraphProviderError(f"{label} must be an array")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_invocation(path: pathlib.Path, supported_kinds: set[str]) -> JsonMap:
    try:
        invocation = as_map(json.loads(path.read_text()), "invocation")
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"invalid invocation JSON: {exc}") from None
    if invocation.get("contract_version") != INVOCATION_CONTRACT_VERSION:
        raise GraphProviderError(f"unsupported invocation contract: {invocation.get('contract_version')}")
    kind = invocation.get("kind")
    if not isinstance(kind, str) or kind not in supported_kinds:
        raise GraphProviderError(f"unsupported graph node kind: {kind}")
    arguments = as_map(invocation.get("arguments"), "arguments")
    invocation["arguments"] = as_map(resolve_secret_references(arguments), "arguments")
    as_map(invocation.get("outputs"), "outputs")
    return invocation


def secret_environment_key(name: str) -> str:
    if SECRET_NAME_PATTERN.fullmatch(name) is None:
        raise GraphProviderError(f"invalid secret name: {name}")
    return f"MERERUN_SECRET_{name.upper().replace('-', '_')}"


def resolve_secret_references(value: object, environment: Mapping[str, str] | None = None) -> object:
    active_environment = os.environ if environment is None else environment
    if isinstance(value, list):
        return [resolve_secret_references(item, active_environment) for item in value]
    if not isinstance(value, dict):
        return value
    mapped = cast(JsonMap, value)
    if set(mapped) == {"$secret"}:
        name = mapped["$secret"]
        if not isinstance(name, str):
            raise GraphProviderError("secret reference name must be a string")
        key = secret_environment_key(name)
        resolved = active_environment.get(key)
        if not resolved:
            raise GraphProviderError(f"configured secret is unavailable: {name}")
        return resolved
    return {key: resolve_secret_references(item, active_environment) for key, item in mapped.items()}


def confined_path(root: pathlib.Path, relative: str) -> pathlib.Path:
    raw = pathlib.PurePosixPath(relative)
    if raw.is_absolute() or not raw.parts or any(part in {"", ".", ".."} for part in raw.parts):
        raise GraphProviderError(f"output path is not confined: {relative}")
    resolved_root = root.resolve()
    candidate = (resolved_root / pathlib.Path(*raw.parts)).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise GraphProviderError(f"output path escapes the run directory: {relative}")
    return candidate


def relative_path(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise GraphProviderError(f"artifact path escapes the run directory: {path}") from None


def diagnostic(identifier: str, severity: str, title: str, message: str) -> JsonMap:
    if severity not in {"info", "warning", "blocker"}:
        raise GraphProviderError(f"unsupported diagnostic severity: {severity}")
    return {"id": identifier, "severity": severity, "title": title, "message": message}


def event(sequence: int, event_type: str, **values: object) -> JsonMap:
    if sequence < 0:
        raise GraphProviderError("event sequence must be non-negative")
    payload: JsonMap = {
        "contract_version": EVENT_CONTRACT_VERSION,
        "sequence": sequence,
        "created_at": now_iso(),
        "type": event_type,
    }
    payload.update(values)
    return payload


class GraphEventStream:
    def __init__(self, writer: EventWriter) -> None:
        self._writer = writer
        self._sequence = 0
        self._finished = False

    @property
    def sequence(self) -> int:
        return self._sequence

    def emit(self, event_type: str, **values: object) -> None:
        if self._finished:
            raise GraphProviderError("node_result must be the final provider event")
        self._writer(event(self._sequence, event_type, **values))
        self._sequence += 1
        if event_type == "node_result":
            self._finished = True


def validate_catalog(catalog: JsonMap) -> None:
    if catalog.get("contract_version") != PROVIDER_CONTRACT_VERSION:
        raise GraphProviderError(f"unsupported provider contract: {catalog.get('contract_version')}")
    provider_id = catalog.get("provider_id")
    provider_version = catalog.get("provider_version")
    if not isinstance(provider_id, str) or PROVIDER_ID_PATTERN.fullmatch(provider_id) is None:
        raise GraphProviderError(f"invalid provider id: {provider_id}")
    if not isinstance(provider_version, str) or SEMVER_PATTERN.fullmatch(provider_version) is None:
        raise GraphProviderError(f"invalid provider version: {provider_version}")
    kinds: set[str] = set()
    for raw_node in as_list(catalog.get("nodes"), "nodes"):
        node = as_map(raw_node, "node")
        kind = node.get("kind")
        if not isinstance(kind, str) or NODE_KIND_PATTERN.fullmatch(kind) is None:
            raise GraphProviderError(f"invalid graph node kind: {kind}")
        if kind in kinds:
            raise GraphProviderError(f"duplicate graph node kind: {kind}")
        kinds.add(kind)
        validate_ports(as_list(node.get("inputs"), f"{kind}.inputs"), f"{kind}.inputs", "required")
        validate_ports(as_list(node.get("outputs"), f"{kind}.outputs"), f"{kind}.outputs", "optional")
        requirements = as_map(node.get("requirements"), f"{kind}.requirements")
        as_list(requirements.get("model_ids"), f"{kind}.requirements.model_ids")
        as_list(requirements.get("accelerator_backends"), f"{kind}.requirements.accelerator_backends")
        for field in [
            "minimum_accelerator_memory_bytes",
            "minimum_system_memory_bytes",
            "minimum_disk_bytes",
            "minimum_cpu_cores",
        ]:
            value = requirements.get(field)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
                raise GraphProviderError(f"{kind}.requirements.{field} must be a positive integer or null")
        network_access = requirements.get("network_access")
        if network_access is not None and not isinstance(network_access, bool):
            raise GraphProviderError(f"{kind}.requirements.network_access must be a boolean or null")
        traits = as_map(node.get("traits"), f"{kind}.traits")
        for trait in ["deterministic", "cacheable", "supports_progress", "supports_previews"]:
            if not isinstance(traits.get(trait), bool):
                raise GraphProviderError(f"{kind}.traits.{trait} must be a boolean")
        if traits.get("side_effects") not in {"none", "local", "external"}:
            raise GraphProviderError(f"{kind}.traits.side_effects is invalid")
        presentation_value = node.get("presentation")
        if presentation_value is not None:
            presentation = as_map(presentation_value, f"{kind}.presentation")
            if presentation.get("style") != "material":
                raise GraphProviderError(f"{kind}.presentation.style must be material")
            primary_argument = presentation.get("primary_argument")
            input_names = {
                cast(str, as_map(item, f"{kind}.inputs").get("name"))
                for item in as_list(node.get("inputs"), f"{kind}.inputs")
            }
            if primary_argument is not None and primary_argument not in input_names:
                raise GraphProviderError(f"{kind}.presentation.primary_argument must name an input")
    if not kinds:
        raise GraphProviderError("provider catalog must expose at least one node")


def validate_ports(raw_ports: list[object], label: str, required_flag: str) -> None:
    names: set[str] = set()
    for raw_port in raw_ports:
        port = as_map(raw_port, label)
        name = port.get("name")
        port_type = port.get("type")
        if not isinstance(name, str) or not name:
            raise GraphProviderError(f"{label} contains an invalid name")
        if name in names:
            raise GraphProviderError(f"{label} contains duplicate port: {name}")
        names.add(name)
        if port_type not in PORT_TYPES:
            raise GraphProviderError(f"{label}.{name} has unsupported type: {port_type}")
        if not isinstance(port.get(required_flag), bool):
            raise GraphProviderError(f"{label}.{name}.{required_flag} must be a boolean")
        secret = port.get("secret")
        if secret is not None and not isinstance(secret, bool):
            raise GraphProviderError(f"{label}.{name}.secret must be a boolean")
        if secret is True and port_type != "string":
            raise GraphProviderError(f"{label}.{name} secret ports must use type string")
        value_schema = port.get("value_schema")
        if value_schema is not None:
            if port_type not in {"json", "asset_collection"}:
                raise GraphProviderError(f"{label}.{name}.value_schema requires a structured port type")
            validate_value_schema(value_schema, f"{label}.{name}.value_schema")


def validate_value_schema(value: object, label: str, depth: int = 0) -> None:
    if depth > 16:
        raise GraphProviderError(f"{label} exceeds the maximum nesting depth")
    schema = as_map(value, label)
    unknown = set(schema) - VALUE_SCHEMA_KEYS
    if unknown:
        raise GraphProviderError(f"{label} contains unsupported fields: {sorted(unknown)}")
    schema_type = schema.get("type")
    if schema_type not in VALUE_SCHEMA_TYPES:
        raise GraphProviderError(f"{label}.type is invalid: {schema_type}")
    for text_field in ["title", "description"]:
        text_value = schema.get(text_field)
        if text_value is not None and not isinstance(text_value, str):
            raise GraphProviderError(f"{label}.{text_field} must be a string")
    for numeric_field in ["minimum", "maximum", "step"]:
        numeric_value = schema.get(numeric_field)
        if numeric_value is not None and (not isinstance(numeric_value, (int, float)) or isinstance(numeric_value, bool)):
            raise GraphProviderError(f"{label}.{numeric_field} must be a number")
    step = schema.get("step")
    if isinstance(step, (int, float)) and not isinstance(step, bool) and step <= 0:
        raise GraphProviderError(f"{label}.step must be positive")
    multiline = schema.get("multiline")
    if multiline is not None and not isinstance(multiline, bool):
        raise GraphProviderError(f"{label}.multiline must be a boolean")
    if schema_type == "enum":
        values = as_list(schema.get("values"), f"{label}.values")
        if not values or any(not isinstance(item, str) for item in values) or len(set(values)) != len(values):
            raise GraphProviderError(f"{label}.values must contain unique strings")
    if schema_type == "object":
        properties = as_map(schema.get("properties", {}), f"{label}.properties")
        for name, child in properties.items():
            if not isinstance(name, str) or not name:
                raise GraphProviderError(f"{label}.properties contains an invalid name")
            validate_value_schema(child, f"{label}.properties.{name}", depth + 1)
        required = as_list(schema.get("required", []), f"{label}.required")
        if any(not isinstance(item, str) or item not in properties for item in required):
            raise GraphProviderError(f"{label}.required must name declared properties")
        if len(set(cast(list[str], required))) != len(required):
            raise GraphProviderError(f"{label}.required contains duplicates")
        additional_properties = schema.get("additional_properties")
        if additional_properties is not None:
            validate_value_schema(
                additional_properties,
                f"{label}.additional_properties",
                depth + 1,
            )
    if schema_type == "array":
        if "items" not in schema:
            raise GraphProviderError(f"{label}.items is required for arrays")
        validate_value_schema(schema["items"], f"{label}.items", depth + 1)


def validate_preflight(document: JsonMap) -> None:
    if document.get("contract_version") != PREFLIGHT_CONTRACT_VERSION:
        raise GraphProviderError(f"unsupported preflight contract: {document.get('contract_version')}")
    if document.get("status") not in {"ok", "blocked"}:
        raise GraphProviderError("preflight status must be ok or blocked")
    diagnostics = as_list(document.get("diagnostics"), "preflight.diagnostics")
    for raw_diagnostic in diagnostics:
        item = as_map(raw_diagnostic, "preflight diagnostic")
        if item.get("severity") not in {"info", "warning", "blocker"}:
            raise GraphProviderError("preflight diagnostic severity is invalid")
        for field in ["id", "title", "message"]:
            if not isinstance(item.get(field), str) or not item[field]:
                raise GraphProviderError(f"preflight diagnostic {field} must be a non-empty string")
    if document.get("status") == "blocked" and not any(
        as_map(item, "preflight diagnostic").get("severity") == "blocker" for item in diagnostics
    ):
        raise GraphProviderError("blocked preflight must include a blocker diagnostic")
    requirements = as_map(document.get("requirements"), "preflight.requirements")
    for field in ["model_ids", "accelerator_backends"]:
        values = as_list(requirements.get(field), f"preflight.requirements.{field}")
        if any(not isinstance(item, str) or not item for item in values):
            raise GraphProviderError(f"preflight.requirements.{field} must contain non-empty strings")
    actions = document.get("actions", [])
    if not isinstance(actions, list) or any(not isinstance(item, dict) for item in actions):
        raise GraphProviderError("preflight.actions must be an array of objects")


def validate_event_stream(events: list[JsonMap], invocation: JsonMap, run_directory: pathlib.Path) -> None:
    if not events:
        raise GraphProviderError("provider execution emitted no events")
    for sequence, item in enumerate(events):
        if item.get("contract_version") != EVENT_CONTRACT_VERSION:
            raise GraphProviderError(f"event {sequence} uses an unsupported contract")
        if item.get("sequence") != sequence:
            raise GraphProviderError(f"event sequence is not contiguous at index {sequence}")
        if not isinstance(item.get("created_at"), str) or not item["created_at"]:
            raise GraphProviderError(f"event {sequence} has no timestamp")
        if not isinstance(item.get("type"), str) or not item["type"]:
            raise GraphProviderError(f"event {sequence} has no type")
    result_events = [item for item in events if item.get("type") == "node_result"]
    if len(result_events) != 1 or events[-1].get("type") != "node_result":
        raise GraphProviderError("provider execution must finish with exactly one node_result event")
    outputs = as_map(result_events[0].get("outputs"), "node_result.outputs")
    declarations = as_map(invocation.get("outputs"), "invocation.outputs")
    missing = sorted(set(declarations) - set(outputs))
    unknown = sorted(set(outputs) - set(declarations))
    if missing:
        raise GraphProviderError(f"node_result is missing declared outputs: {missing}")
    if unknown:
        raise GraphProviderError(f"node_result contains undeclared outputs: {unknown}")
    for name, raw_declaration in declarations.items():
        declaration = as_map(raw_declaration, f"invocation.outputs.{name}")
        output_type = declaration.get("type")
        output_value = outputs[name]
        if output_value is None and declaration.get("optional") is True:
            continue
        if output_type in {"asset", "asset_directory", "asset_collection"}:
            expected_path = declaration.get("path")
            if not isinstance(expected_path, str) or output_value != expected_path:
                raise GraphProviderError(f"node_result output {name} must equal its declared relative path")
            path = confined_path(run_directory, expected_path)
            if output_type == "asset_directory" and not path.is_dir():
                raise GraphProviderError(f"declared output directory is missing: {name}")
            if output_type != "asset_directory" and not path.is_file():
                raise GraphProviderError(f"declared output artifact is missing: {name}")

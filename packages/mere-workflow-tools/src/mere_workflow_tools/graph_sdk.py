from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
from typing import Callable, cast

JsonMap = dict[str, object]
EventWriter = Callable[[JsonMap], None]

PROVIDER_CONTRACT_VERSION = "mere.run/plugin-graph-provider.v1"
INVOCATION_CONTRACT_VERSION = "mere.run/plugin-graph-invocation.v1"
PREFLIGHT_CONTRACT_VERSION = "mere.run/plugin-graph-preflight.v1"
EVENT_CONTRACT_VERSION = "mere.run/plugin-graph-event.v1"

PROVIDER_ID_PATTERN = re.compile(r"^mere-[a-z0-9-]+$")
NODE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}(\.[a-z][a-z0-9-]{0,63})+$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.-]+)?$")
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
    as_map(invocation.get("arguments"), "arguments")
    as_map(invocation.get("outputs"), "outputs")
    return invocation


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
        traits = as_map(node.get("traits"), f"{kind}.traits")
        for trait in ["deterministic", "cacheable", "supports_progress", "supports_previews"]:
            if not isinstance(traits.get(trait), bool):
                raise GraphProviderError(f"{kind}.traits.{trait} must be a boolean")
        if traits.get("side_effects") not in {"none", "local", "external"}:
            raise GraphProviderError(f"{kind}.traits.side_effects is invalid")
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

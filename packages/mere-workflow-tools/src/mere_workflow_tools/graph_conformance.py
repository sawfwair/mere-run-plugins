from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

from .graph_sdk import (
    GraphProviderError,
    JsonMap,
    as_list,
    as_map,
    validate_catalog,
    validate_event_stream,
    validate_preflight,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Validate a mere.run graph node provider catalog.")
    source = value.add_mutually_exclusive_group(required=True)
    source.add_argument("--catalog", type=pathlib.Path, help="Provider catalog JSON file.")
    source.add_argument("--provider", help="Provider executable exposing `graph catalog --json`.")
    value.add_argument("--invocation", type=pathlib.Path, help="Fixture invocation used to validate preflight.")
    value.add_argument("--run-dir", type=pathlib.Path, help="Confined scratch run directory for the fixture.")
    value.add_argument("--execute", action="store_true", help="Execute the fixture and validate its NDJSON and outputs.")
    value.add_argument("--json", action="store_true")
    return value


def load_catalog(args: argparse.Namespace) -> dict[str, object]:
    if args.catalog is not None:
        try:
            return as_map(json.loads(args.catalog.read_text()), "catalog")
        except json.JSONDecodeError as exc:
            raise GraphProviderError(f"invalid catalog JSON: {exc}") from None
    result = subprocess.run(
        [args.provider, "graph", "catalog", "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise GraphProviderError(result.stderr.strip() or f"provider exited with status {result.returncode}")
    try:
        return as_map(json.loads(result.stdout), "catalog")
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"provider emitted invalid catalog JSON: {exc}") from None


def run_provider(provider: str, arguments: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [provider, *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise GraphProviderError(result.stderr.strip() or f"provider {label} exited with status {result.returncode}")
    return result


def load_json_document(raw: str, label: str) -> JsonMap:
    try:
        return as_map(json.loads(raw), label)
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"provider emitted invalid {label} JSON: {exc}") from None


def validate_fixture(args: argparse.Namespace) -> JsonMap | None:
    if args.invocation is None:
        if args.execute or args.run_dir is not None:
            raise GraphProviderError("--execute and --run-dir require --invocation")
        return None
    if args.provider is None or args.run_dir is None:
        raise GraphProviderError("fixture conformance requires --provider and --run-dir")
    try:
        invocation = as_map(json.loads(args.invocation.read_text()), "invocation")
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"invalid invocation JSON: {exc}") from None
    args.run_dir.mkdir(parents=True, exist_ok=True)
    preflight_result = run_provider(
        args.provider,
        ["graph", "preflight", "--request", str(args.invocation), "--run-dir", str(args.run_dir), "--json"],
        "preflight",
    )
    preflight = load_json_document(preflight_result.stdout, "preflight")
    validate_preflight(preflight)
    result: JsonMap = {"preflight_status": preflight["status"], "event_count": 0, "executed": False}
    if not args.execute:
        return result
    if preflight["status"] != "ok":
        raise GraphProviderError("fixture preflight is blocked; execution conformance cannot continue")
    execution = run_provider(
        args.provider,
        ["graph", "execute", "--request", str(args.invocation), "--run-dir", str(args.run_dir), "--json-stream"],
        "execution",
    )
    events: list[JsonMap] = []
    for line_number, line in enumerate(execution.stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(as_map(json.loads(line), f"event line {line_number}"))
        except json.JSONDecodeError as exc:
            raise GraphProviderError(f"provider emitted invalid event JSON on line {line_number}: {exc}") from None
    validate_event_stream(events, invocation, args.run_dir)
    result["event_count"] = len(events)
    result["executed"] = True
    result["output_names"] = sorted(as_map(events[-1]["outputs"], "node_result.outputs"))
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        catalog = load_catalog(args)
        validate_catalog(catalog)
        fixture = validate_fixture(args)
    except (GraphProviderError, OSError) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    nodes = as_list(catalog["nodes"], "catalog.nodes")
    node_kinds = sorted(str(as_map(node, "catalog node")["kind"]) for node in nodes)
    result: JsonMap = {
        "contract_version": "mere.run/graph-provider-conformance.v1",
        "status": "passed",
        "provider_id": catalog["provider_id"],
        "provider_version": catalog["provider_version"],
        "node_kinds": node_kinds,
        "checks": ["catalog"] + (["preflight"] if fixture is not None else [])
        + (["execution"] if fixture is not None and fixture["executed"] is True else []),
    }
    if fixture is not None:
        result["fixture"] = fixture
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(f"passed: {result['provider_id']} ({len(node_kinds)} node kinds)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

from .graph_sdk import GraphProviderError, JsonMap, as_list, as_map, validate_catalog


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Validate a mere.run graph node provider catalog.")
    source = value.add_mutually_exclusive_group(required=True)
    source.add_argument("--catalog", type=pathlib.Path, help="Provider catalog JSON file.")
    source.add_argument("--provider", help="Provider executable exposing `graph catalog --json`.")
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


def main() -> int:
    args = parser().parse_args()
    try:
        catalog = load_catalog(args)
        validate_catalog(catalog)
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
    }
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(f"passed: {result['provider_id']} ({len(node_kinds)} node kinds)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

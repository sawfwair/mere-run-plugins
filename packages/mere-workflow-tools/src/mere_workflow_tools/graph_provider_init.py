from __future__ import annotations

import argparse
import pathlib
import sys

from .graph_sdk import (
    NODE_KIND_PATTERN,
    PROVIDER_ID_PATTERN,
    GraphProviderError,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Create a typed mere.run graph provider project.")
    value.add_argument("destination", type=pathlib.Path)
    value.add_argument("--provider-id", required=True)
    value.add_argument("--node-kind", required=True)
    return value


def create_provider(destination: pathlib.Path, provider_id: str, node_kind: str) -> pathlib.Path:
    if PROVIDER_ID_PATTERN.fullmatch(provider_id) is None:
        raise GraphProviderError(f"invalid provider id: {provider_id}")
    if NODE_KIND_PATTERN.fullmatch(node_kind) is None:
        raise GraphProviderError(f"invalid graph node kind: {node_kind}")
    if destination.exists() and any(destination.iterdir()):
        raise GraphProviderError(f"provider destination is not empty: {destination}")
    module = provider_id.replace("-", "_")
    if not module.isidentifier():
        raise GraphProviderError(f"provider id does not produce a valid Python module: {provider_id}")
    source = destination / "src" / module
    tests = destination / "tests"
    source.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    write_text(destination / "pyproject.toml", pyproject(provider_id, module))
    write_text(destination / "README.md", readme(provider_id, node_kind))
    write_text(source / "__init__.py", '__version__ = "0.1.0"\n')
    write_text(source / "py.typed", "")
    write_text(source / "cli.py", provider_cli(provider_id, node_kind))
    write_text(tests / "test_provider.py", provider_test(module, node_kind))
    return destination


def write_text(path: pathlib.Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value)
    temporary.replace(path)


def pyproject(provider_id: str, module: str) -> str:
    return f'''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{provider_id}"
version = "0.1.0"
description = "Typed mere.run graph node provider"
requires-python = ">=3.9"
dependencies = ["mere-workflow-tools>=0.2.0"]

[project.scripts]
{provider_id} = "{module}.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
{module} = ["py.typed"]
'''


def readme(provider_id: str, node_kind: str) -> str:
    return f'''# {provider_id}

Typed provider for `{node_kind}`. The generated node is deterministic and
local-only; replace its text artifact implementation while preserving the
catalog, preflight, NDJSON event, and confined output contracts.

```bash
uv run {provider_id} graph catalog --json
uv run mere-graph-conformance --provider {provider_id} --json
```
'''


def provider_cli(provider_id: str, node_kind: str) -> str:
    return f'''from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

from mere_workflow_tools.graph_sdk import (
    GraphEventStream,
    GraphProviderError,
    PREFLIGHT_CONTRACT_VERSION,
    PROVIDER_CONTRACT_VERSION,
    confined_path,
    load_invocation,
    validate_catalog,
)

from . import __version__

PROVIDER_ID = "{provider_id}"
NODE_KIND = "{node_kind}"


def catalog() -> dict[str, object]:
    value: dict[str, object] = {{
        "contract_version": PROVIDER_CONTRACT_VERSION,
        "provider_id": PROVIDER_ID,
        "provider_version": __version__,
        "nodes": [{{
            "kind": NODE_KIND,
            "title": "Example deterministic node",
            "description": "Writes one confined text artifact.",
            "inputs": [{{"name": "text", "type": "string", "required": True}}],
            "outputs": [{{"name": "artifact", "type": "asset", "optional": False}}],
            "requirements": {{
                "model_ids": [],
                "accelerator_backends": ["cpu", "metal", "cuda", "rocm"],
                "minimum_accelerator_memory_bytes": None,
            }},
            "traits": {{
                "deterministic": True,
                "cacheable": True,
                "side_effects": "none",
                "supports_progress": True,
                "supports_previews": False,
            }},
        }}],
    }}
    validate_catalog(value)
    return value


def output_path(invocation: dict[str, object], run_directory: pathlib.Path) -> pathlib.Path:
    outputs = invocation.get("outputs")
    if not isinstance(outputs, dict) or not isinstance(outputs.get("artifact"), dict):
        raise GraphProviderError("artifact output declaration is required")
    relative = outputs["artifact"].get("path")
    if not isinstance(relative, str):
        raise GraphProviderError("artifact output path is required")
    return confined_path(run_directory, relative)


def preflight(invocation: dict[str, object], run_directory: pathlib.Path) -> dict[str, object]:
    diagnostics: list[dict[str, object]] = []
    arguments = invocation.get("arguments")
    if not isinstance(arguments, dict) or not isinstance(arguments.get("text"), str):
        diagnostics.append({{
            "id": "text_missing",
            "severity": "blocker",
            "title": "Text is required",
            "message": "Provide the text input.",
        }})
    try:
        output_path(invocation, run_directory)
    except GraphProviderError as exc:
        diagnostics.append({{
            "id": "output_invalid",
            "severity": "blocker",
            "title": "Output is invalid",
            "message": str(exc),
        }})
    return {{
        "contract_version": PREFLIGHT_CONTRACT_VERSION,
        "status": "blocked" if diagnostics else "ok",
        "diagnostics": diagnostics,
        "actions": [],
        "requirements": {{"model_ids": [], "accelerator_backends": ["cpu", "metal", "cuda", "rocm"]}},
    }}


def execute(invocation: dict[str, object], run_directory: pathlib.Path) -> list[dict[str, object]]:
    report = preflight(invocation, run_directory)
    if report["status"] != "ok":
        raise GraphProviderError("provider preflight is blocked")
    arguments = invocation["arguments"]
    assert isinstance(arguments, dict)
    text = arguments["text"]
    assert isinstance(text, str)
    output = output_path(invocation, run_directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\\n")
    relative = output.relative_to(run_directory.resolve()).as_posix()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    events: list[dict[str, object]] = []
    stream = GraphEventStream(events.append)
    stream.emit("progress", message="Writing artifact", progress={{"current": 1, "total": 1, "fraction": 1.0}})
    stream.emit("artifact_ready", artifact={{
        "name": "artifact",
        "kind": "graph.output",
        "path": relative,
        "content_type": "text/plain",
        "size_bytes": output.stat().st_size,
        "sha256": digest,
    }})
    stream.emit("node_result", outputs={{"artifact": relative}})
    return events


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    graph = value.add_subparsers(dest="command", required=True).add_parser("graph")
    commands = graph.add_subparsers(dest="graph_command", required=True)
    commands.add_parser("catalog").add_argument("--json", action="store_true")
    for name in ["preflight", "execute"]:
        command = commands.add_parser(name)
        command.add_argument("--request", required=True, type=pathlib.Path)
        command.add_argument("--run-dir", required=True, type=pathlib.Path)
        command.add_argument("--json" if name == "preflight" else "--json-stream", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        if args.graph_command == "catalog":
            print(json.dumps(catalog(), sort_keys=True))
            return 0
        invocation = load_invocation(args.request, {{NODE_KIND}})
        if args.graph_command == "preflight":
            print(json.dumps(preflight(invocation, args.run_dir), sort_keys=True))
            return 0
        for item in execute(invocation, args.run_dir):
            print(json.dumps(item, sort_keys=True))
        return 0
    except (GraphProviderError, OSError) as exc:
        sys.stderr.write(str(exc) + "\\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def provider_test(module: str, node_kind: str) -> str:
    return f'''import unittest

from mere_workflow_tools.graph_sdk import validate_catalog
from {module}.cli import catalog


class ProviderTests(unittest.TestCase):
    def test_catalog_conforms(self) -> None:
        value = catalog()
        validate_catalog(value)
        self.assertEqual(value["nodes"][0]["kind"], "{node_kind}")


if __name__ == "__main__":
    unittest.main()
'''


def main() -> int:
    args = parser().parse_args()
    try:
        destination = create_provider(args.destination, args.provider_id, args.node_kind)
    except (GraphProviderError, OSError) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    sys.stdout.write(str(destination.resolve()) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

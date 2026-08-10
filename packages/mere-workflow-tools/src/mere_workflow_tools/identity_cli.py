from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys

from . import __version__

PROVIDER_ID = "mere-identity-tools"
BACKEND_ENV = "MERE_IDENTITY_BACKEND"
DEFAULT_BACKEND = "identity-tools-backend"
NODE_KINDS = [
    "identity.curriculum.generate",
    "identity.dossier.compile",
    "identity.evaluate.four-arm",
    "identity.text-lora.train",
]


class IdentityToolsError(RuntimeError):
    pass


def print_json(value: object) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")
    sys.stdout.flush()


def backend_command() -> list[str]:
    raw = os.environ.get(BACKEND_ENV, DEFAULT_BACKEND)
    try:
        command = shlex.split(raw)
    except ValueError as exc:
        raise IdentityToolsError(f"{BACKEND_ENV} is invalid: {exc}") from None
    if not command:
        raise IdentityToolsError(f"{BACKEND_ENV} must name an executable")
    return command


def backend_available(command: list[str]) -> bool:
    return resolved_backend(command) is not None


def plugin_manifest() -> dict[str, object]:
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PROVIDER_ID,
        "version": __version__,
        "executable": PROVIDER_ID,
        "description": "Local identity curricula, text adapters, evaluation, and sanitized reports.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins",
        "graphProvider": {"contractVersion": "mere.run/plugin-graph-provider.v1"},
        "commands": [
            {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
            {"name": "doctor", "description": "Check the configured local identity backend.", "stdout": "json"},
            {"name": "stage", "description": "Stage a source with a configured identity registry.", "stdout": "json"},
            {"name": "graph", "description": "Expose identity graph nodes.", "stdout": "json"},
        ],
        "capabilities": [
            "identity-curriculum",
            "text-lora-training",
            "four-arm-evaluation",
            "sanitized-report",
            "graph-node-provider-v1",
            "local-artifact-custody",
        ],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": True,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def catalog_node(
    kind: str,
    title: str,
    description: str,
    accelerators: list[str],
    network_access: bool,
) -> dict[str, object]:
    return {
        "kind": kind,
        "title": title,
        "description": description,
        "category": "identity",
        "inputs": [{"name": "payload", "type": "json", "required": True}],
        "outputs": [
            {
                "name": "receipt",
                "type": "asset",
                "optional": False,
                "content_types": ["application/vnd.mere.identity-receipt+json"],
            }
        ],
        "requirements": {
            "model_ids": [],
            "accelerator_backends": accelerators,
            "minimum_system_memory_bytes": 8_000_000_000 if accelerators == ["metal"] else None,
            "network_access": network_access,
        },
        "traits": {
            "deterministic": kind == "identity.dossier.compile",
            "cacheable": False,
            "side_effects": "local",
            "supports_progress": True,
            "supports_previews": False,
        },
    }


def graph_catalog() -> dict[str, object]:
    universal = ["cpu", "metal", "cuda", "rocm"]
    return {
        "contract_version": "mere.run/plugin-graph-provider.v1",
        "provider_id": PROVIDER_ID,
        "provider_version": __version__,
        "nodes": [
            catalog_node(
                "identity.curriculum.generate",
                "Generate identity curriculum",
                "Generate and materialize a locally retained synthetic curriculum.",
                universal,
                True,
            ),
            catalog_node(
                "identity.text-lora.train",
                "Train a text identity adapter",
                "Train and verify a content-addressed text LoRA on Apple Silicon.",
                ["metal"],
                False,
            ),
            catalog_node(
                "identity.evaluate.four-arm",
                "Evaluate an identity adapter",
                "Compare base-neutral, base-prompt, adapter-neutral, and adapter-prompt arms.",
                ["metal"],
                False,
            ),
            catalog_node(
                "identity.dossier.compile",
                "Compile a sanitized identity report",
                "Compile digest-linked source aggregates without private examples or paths.",
                universal,
                False,
            ),
        ],
    }


def run_backend(arguments: list[str]) -> int:
    command = backend_command()
    executable = resolved_backend(command)
    if executable is None:
        raise IdentityToolsError(
            f"identity backend is unavailable; install one and set {BACKEND_ENV}"
        )
    return subprocess.run([executable, *command[1:], *arguments], check=False).returncode


def resolved_backend(command: list[str]) -> str | None:
    executable = pathlib.Path(command[0]).expanduser()
    if executable.is_file():
        return str(executable)
    discovered = shutil.which(command[0])
    if discovered:
        return discovered
    if len(executable.parts) == 1:
        for directory in (
            pathlib.Path.home() / ".local" / "bin",
            pathlib.Path.home() / "bin",
            pathlib.Path("/opt/homebrew/bin"),
            pathlib.Path("/usr/local/bin"),
        ):
            candidate = directory / executable
            if candidate.is_file():
                return str(candidate)
    return None


def doctor() -> int:
    command = backend_command()
    if not backend_available(command):
        print_json(
            {
                "status": "blocked",
                "provider_id": PROVIDER_ID,
                "provider_version": __version__,
                "backend_configured": False,
                "diagnostics": [
                    {
                        "code": "identity_backend_missing",
                        "message": f"Install a local identity backend and set {BACKEND_ENV}.",
                    }
                ],
            }
        )
        return 3
    return run_backend(["doctor", "--json"])


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog=PROVIDER_ID)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("manifest").add_argument("--json", action="store_true")
    commands.add_parser("doctor").add_argument("--json", action="store_true")
    stage = commands.add_parser("stage")
    stage.add_argument("source")
    stage.add_argument("--pairing-code", required=True)
    stage.add_argument("--registry-url", required=True)
    stage.add_argument("--device-id", required=True)
    stage.add_argument("--json", action="store_true")
    graph = commands.add_parser("graph")
    graph_commands = graph.add_subparsers(dest="graph_command", required=True)
    graph_commands.add_parser("catalog").add_argument("--json", action="store_true")
    for name in ("preflight", "execute"):
        command = graph_commands.add_parser(name)
        command.add_argument("--request", required=True, type=pathlib.Path)
        command.add_argument("--run-dir", required=True, type=pathlib.Path)
        command.add_argument("--json" if name == "preflight" else "--json-stream", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "manifest":
            print_json(plugin_manifest())
            return 0
        if args.command == "doctor":
            return doctor()
        if args.command == "stage":
            return run_backend(
                [
                    "stage",
                    args.source,
                    "--pairing-code",
                    args.pairing_code,
                    "--api-url",
                    args.registry_url,
                    "--device-id",
                    args.device_id,
                    "--json",
                ]
            )
        if args.graph_command == "catalog":
            # The public facade owns the provider identity and version that
            # mere.run validates and Relay uses for placement. Private
            # backends may version independently, so their catalog identity
            # must never leak through or invalidate the installed facade.
            print_json(graph_catalog())
            return 0
        flag = "--json" if args.graph_command == "preflight" else "--json-stream"
        return run_backend(
            [
                "graph",
                args.graph_command,
                "--request",
                str(args.request),
                "--run-dir",
                str(args.run_dir),
                flag,
            ]
        )
    except (IdentityToolsError, OSError) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

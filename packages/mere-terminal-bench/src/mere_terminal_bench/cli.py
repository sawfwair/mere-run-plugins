from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import importlib
import importlib.metadata
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from typing import TextIO, cast

from . import __version__

JsonMap = dict[str, object]
JsonList = list[object]

PLUGIN_NAME = "mere-terminal-bench"
HARBOR_VERSION = "0.22.0"
DATASET_NAME = "terminal-bench/terminal-bench-2-1"
DATASET_REF = "sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a"
DATASET_SOURCE_COMMIT = "7131e4375048a0e408a8fb404b5f499d726b695b"
EXPECTED_TASK_COUNT = 89
DEFAULT_MODELS = (
    "text-agent-ornith-35b-mlx-4bit",
    "text-agent-ornith-35b-mlx-8bit",
)
DEFAULT_ENGINE = "text-chat-q36"
DEFAULT_MEMORY_GUARD = "balanced"
DEFAULT_CONTEXT_SIZE = 131_072
DEFAULT_MAX_OUTPUT_TOKENS = 32_768
DEFAULT_PORT = 18_080
DEFAULT_STORAGE_GIB = 64.0
HARBOR_LOCAL_API_KEY = "mere-terminal-bench-local"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SIZE_PATTERN = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*([kmgtpe]?i?b)$", re.IGNORECASE)
TASK_GLOB_PATTERN = re.compile(r"[*?[]")


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def eprint(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def log(message: str) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%SZ")
    eprint(f"[{stamp}] {message}")


def print_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_json(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def load_json(path: pathlib.Path, context: str) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), context)
    except (OSError, json.JSONDecodeError) as error:
        raise PluginError(f"could not read {context}: {error}", 2) from error


def as_map(value: object, context: str) -> JsonMap:
    if not isinstance(value, dict):
        raise PluginError(f"{context} must be a JSON object", 2)
    return cast(JsonMap, value)


def as_list(value: object, context: str) -> JsonList:
    if not isinstance(value, list):
        raise PluginError(f"{context} must be a JSON array", 2)
    return cast(JsonList, value)


def string_field(mapping: JsonMap, key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise PluginError(f"{context}.{key} must be a string", 2)
    return value


def int_field(mapping: JsonMap, key: str, context: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PluginError(f"{context}.{key} must be an integer", 2)
    return value


def float_field(mapping: JsonMap, key: str, context: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginError(f"{context}.{key} must be numeric", 2)
    return float(value)


def string_list(value: object, context: str) -> list[str]:
    items = as_list(value, context)
    if not all(isinstance(item, str) for item in items):
        raise PluginError(f"{context} must contain only strings", 2)
    return cast(list[str], items)


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "model"


def terminal_bench_task_name(value: str) -> str:
    return value if "/" in value else f"terminal-bench/{value}"


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise PluginError(
            "--run-id must start with a letter or digit and contain only letters, digits, '.', '_', or '-'",
            2,
        )


def executable_path(requested: str) -> str | None:
    expanded = pathlib.Path(requested).expanduser()
    if expanded.parent != pathlib.Path(".") or "/" in requested:
        return str(expanded.resolve()) if expanded.is_file() and os.access(expanded, os.X_OK) else None
    return shutil.which(requested)


def internal_harbor_command() -> list[str] | None:
    try:
        version = importlib.metadata.version("harbor")
    except importlib.metadata.PackageNotFoundError:
        return None
    if version != HARBOR_VERSION:
        return None
    if getattr(sys, "frozen", False):
        return [sys.executable, "mere_terminal_bench.cli", "_harbor"]
    return [sys.executable, "-m", "mere_terminal_bench", "_harbor"]


def harbor_command(requested: str) -> list[str] | None:
    path = executable_path(requested)
    if path is not None:
        return [path]
    return internal_harbor_command() if requested == "harbor" else None


def capture(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PluginError(f"could not run {shlex.join(argv)}: {error}", 3) from error


def docker_environment(context: str | None) -> dict[str, str]:
    environment = os.environ.copy()
    if context:
        environment["DOCKER_CONTEXT"] = context
    return environment


def harbor_environment(context: str | None) -> dict[str, str]:
    environment = docker_environment(context)
    environment["OPENAI_API_KEY"] = HARBOR_LOCAL_API_KEY
    for name in ("OPENAI_ORG_ID", "OPENAI_ORGANIZATION", "OPENAI_PROJECT"):
        environment.pop(name, None)
    return environment


def parse_size_bytes(value: str) -> int:
    match = SIZE_PATTERN.fullmatch(value.strip())
    if match is None:
        raise PluginError(f"unsupported Docker size value: {value}", 3)
    number = float(match.group(1))
    unit = match.group(2).lower()
    factors = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": 1024**3,
        "tb": 1000**4,
        "tib": 1024**4,
        "pb": 1000**5,
        "pib": 1024**5,
        "eb": 1000**6,
        "eib": 1024**6,
    }
    return int(number * factors[unit])


def docker_usage_bytes(docker: str, context: str | None) -> int:
    completed = capture(
        [docker, "system", "df", "--format", "{{json .}}"],
        env=docker_environment(context),
        timeout=60.0,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise PluginError(f"Docker storage inspection failed: {detail}", 3)
    total = 0
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            row = as_map(json.loads(line), "docker system df row")
        except json.JSONDecodeError as error:
            raise PluginError(f"Docker returned invalid storage JSON: {error}", 3) from error
        size = row.get("Size")
        if isinstance(size, str):
            total += parse_size_bytes(size)
    return total


def docker_usage_bytes_with_retry(
    docker: str,
    context: str | None,
    *,
    attempts: int = 3,
    retry_delay: float = 1.0,
) -> int:
    last_error: PluginError | None = None
    for attempt in range(attempts):
        try:
            return docker_usage_bytes(docker, context)
        except PluginError as error:
            last_error = error
            if attempt + 1 < attempts:
                log(f"Docker storage inspection failed; retrying ({attempt + 1}/{attempts})")
                time.sleep(retry_delay)
    if last_error is None:
        raise PluginError("Docker storage inspection did not run", 3)
    raise PluginError(f"Docker storage inspection failed after {attempts} attempts: {last_error}", 3) from last_error


def record_docker_usage(runtime: JsonMap, current: int) -> int:
    baseline = runtime.get("baselineDockerUsageBytes")
    if isinstance(baseline, bool) or not isinstance(baseline, int):
        baseline = current
        runtime["baselineDockerUsageBytes"] = baseline
    runtime["currentDockerUsageBytes"] = current
    runtime["additionalDockerUsageBytes"] = max(0, current - baseline)
    return baseline


def docker_inspection(docker: str, context: str | None) -> JsonMap:
    path = executable_path(docker)
    if path is None:
        return {"ready": False, "requested": docker, "error": "Docker executable not found"}
    environment = docker_environment(context)
    current = capture([path, "context", "show"], env=environment)
    info = capture(
        [
            path,
            "info",
            "--format",
            "{{json .}}",
        ],
        env=environment,
        timeout=60.0,
    )
    if info.returncode != 0:
        detail = info.stderr.strip() or info.stdout.strip()
        return {
            "ready": False,
            "path": path,
            "requestedContext": context,
            "currentContext": current.stdout.strip() or None,
            "error": detail,
        }
    try:
        payload = as_map(json.loads(info.stdout), "docker info")
        usage = docker_usage_bytes_with_retry(path, context)
    except (json.JSONDecodeError, PluginError) as error:
        return {"ready": False, "path": path, "error": str(error)}
    return {
        "ready": True,
        "path": path,
        "requestedContext": context,
        "currentContext": current.stdout.strip() or None,
        "serverVersion": payload.get("ServerVersion"),
        "architecture": payload.get("Architecture"),
        "operatingSystem": payload.get("OperatingSystem"),
        "cpus": payload.get("NCPU"),
        "memoryBytes": payload.get("MemTotal"),
        "dockerRootDir": payload.get("DockerRootDir"),
        "reportedUsageBytes": usage,
    }


def docker_quick_inspection(docker: str, context: str | None) -> JsonMap:
    path = executable_path(docker)
    if path is None:
        return {"ready": False, "requested": docker, "error": "Docker executable not found"}
    environment = docker_environment(context)
    try:
        current = capture([path, "context", "show"], env=environment, timeout=3.0)
        info = capture(
            [path, "info", "--format", "{{json .}}"],
            env=environment,
            timeout=5.0,
        )
    except PluginError as error:
        return {
            "ready": False,
            "path": path,
            "requestedContext": context,
            "error": str(error),
        }
    if info.returncode != 0:
        detail = info.stderr.strip() or info.stdout.strip()
        return {
            "ready": False,
            "path": path,
            "requestedContext": context,
            "currentContext": current.stdout.strip() or None,
            "error": detail,
        }
    try:
        payload = as_map(json.loads(info.stdout), "docker info")
    except json.JSONDecodeError as error:
        return {"ready": False, "path": path, "error": str(error)}
    return {
        "ready": True,
        "path": path,
        "requestedContext": context,
        "currentContext": current.stdout.strip() or None,
        "serverVersion": payload.get("ServerVersion"),
        "architecture": payload.get("Architecture"),
        "operatingSystem": payload.get("OperatingSystem"),
        "cpus": payload.get("NCPU"),
        "memoryBytes": payload.get("MemTotal"),
        "storageInspected": False,
    }


def validate_docker_bind_mount(
    docker: str,
    context: str | None,
    host_directory: pathlib.Path,
) -> None:
    directory = host_directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(f"{directory}:{os.getpid()}:{time.time_ns()}".encode()).hexdigest()
    host_marker = directory / f".mere-terminal-bench-host-probe-{os.getpid()}"
    docker_marker = directory / f".mere-terminal-bench-docker-probe-{os.getpid()}"
    host_marker.write_text(token)
    try:
        completed = capture(
            [
                docker,
                "run",
                "--rm",
                "--volume",
                f"{directory}:/mere-run-probe:rw",
                "busybox:1.37.0",
                "sh",
                "-c",
                'test "$(cat /mere-run-probe/$1)" = "$3" && printf %s "$3" > "/mere-run-probe/$2"',
                "probe",
                host_marker.name,
                docker_marker.name,
                token,
            ],
            env=docker_environment(context),
            timeout=180.0,
        )
        observed = docker_marker.read_text() if docker_marker.is_file() else None
        if completed.returncode != 0 or observed != token:
            detail = completed.stderr.strip() or completed.stdout.strip() or "round-trip marker was not returned"
            raise PluginError(
                f"Docker context cannot read and write benchmark output directory {directory}: {detail}. "
                "Mount that host path into the Docker runtime at the same path before running Harbor.",
                3,
            )
    finally:
        host_marker.unlink(missing_ok=True)
        docker_marker.unlink(missing_ok=True)


def harbor_inspection(harbor: str, *, timeout: float = 30.0) -> JsonMap:
    command = harbor_command(harbor)
    install_command = "mere.run plugin install mere-terminal-bench --source --yes"
    if command is None:
        return {
            "ready": False,
            "requested": harbor,
            "requiredVersion": HARBOR_VERSION,
            "installCommand": install_command,
            "error": "Harbor executable not found",
        }
    completed = capture([*command, "--version"], timeout=timeout)
    version = completed.stdout.strip() or completed.stderr.strip()
    ready = completed.returncode == 0 and version == HARBOR_VERSION
    return {
        "ready": ready,
        "command": command,
        "version": version,
        "requiredVersion": HARBOR_VERSION,
        "installCommand": install_command,
        **({} if ready else {"error": "Harbor version does not match the pinned benchmark version"}),
    }


def mere_run_inspection(mere_run: str) -> JsonMap:
    path = executable_path(mere_run)
    if path is None:
        return {"ready": False, "requested": mere_run, "error": "mere.run executable not found"}
    try:
        completed = capture([path, "--version"], timeout=5.0)
    except PluginError as error:
        return {"ready": False, "path": path, "error": str(error)}
    version = completed.stdout.strip() or completed.stderr.strip()
    ready = completed.returncode == 0
    return {
        "ready": ready,
        "path": path,
        "version": version or None,
        **({} if ready else {"error": "mere.run version check failed"}),
    }


def mere_run_preflight(
    mere_run: str,
    *,
    engine: str,
    model: str,
    port: int,
    context_size: int,
) -> JsonMap:
    path = executable_path(mere_run)
    if path is None:
        return {"ready": False, "requested": mere_run, "model": model, "error": "mere.run executable not found"}
    completed = capture(
        [
            path,
            "api",
            "serve",
            "--engine",
            engine,
            "--model",
            model,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--context-size",
            str(context_size),
            "--memory-guard",
            DEFAULT_MEMORY_GUARD,
            "--max-active-requests",
            "1",
            "--preflight",
            "--json",
        ],
        timeout=120.0,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return {"ready": False, "path": path, "model": model, "error": detail}
    try:
        report = as_map(json.loads(completed.stdout), "mere.run preflight")
    except json.JSONDecodeError as error:
        return {"ready": False, "path": path, "model": model, "error": str(error)}
    return {
        "ready": report.get("status") == "ok",
        "path": path,
        "model": model,
        "report": report,
    }


def plugin_manifest() -> JsonMap:
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": PLUGIN_NAME,
        "description": "Run pinned Terminal-Bench evaluations against local mere.run text models.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-terminal-bench",
        "commands": [
            {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
            {
                "name": "doctor",
                "description": "Check dependencies quickly or run explicit deep model preflights.",
                "stdout": "json",
            },
            {"name": "plan", "description": "Write a pinned, resource-bounded run manifest.", "stdout": "json"},
            {"name": "run", "description": "Execute the pending model arms in a run manifest.", "stdout": "json"},
            {"name": "resume", "description": "Resume incomplete model arms from a run manifest.", "stdout": "json"},
            {"name": "report", "description": "Rebuild the matched model comparison report.", "stdout": "json"},
            {"name": "cleanup", "description": "Stop only the local server recorded by a run manifest.", "stdout": "json"},
        ],
        "capabilities": [
            "local-evaluation",
            "terminal-bench",
            "harbor",
            "docker",
            "matched-model-comparison",
            "durable-run-manifest",
        ],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": False,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "stop",
        },
    }


def default_run_id() -> str:
    return "terminal-bench-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def planned_manifest(args: argparse.Namespace) -> JsonMap:
    validate_run_id(args.run_id)
    if args.attempts < 1 or args.concurrency < 1:
        raise PluginError("--attempts and --concurrency must be positive", 2)
    if args.max_additional_storage_gb <= 0:
        raise PluginError("--max-additional-storage-gb must be positive", 2)
    if args.context_size < 1 or args.max_output_tokens < 1:
        raise PluginError("context and output token limits must be positive", 2)
    models = args.models or list(DEFAULT_MODELS)
    if len(set(models)) != len(models):
        raise PluginError("--model values must be unique", 2)
    output = args.output.expanduser().resolve()
    run_manifest = output / "run.json"
    jobs_dir = output / "harbor-jobs"
    endpoint = f"http://127.0.0.1:{args.port}"
    include_tasks = [terminal_bench_task_name(value) for value in (args.include_tasks or [])]
    if len(set(include_tasks)) != len(include_tasks):
        raise PluginError("--include-task values must be unique", 2)
    includes_glob = any(TASK_GLOB_PATTERN.search(value) for value in include_tasks)
    if includes_glob and args.n_tasks is None:
        raise PluginError("--n-tasks is required when --include-task contains a glob", 2)
    if include_tasks and not includes_glob and args.n_tasks is not None and args.n_tasks != len(include_tasks):
        raise PluginError("--n-tasks must match the number of exact --include-task values", 2)
    selected_task_count = args.n_tasks if args.n_tasks is not None else (len(include_tasks) or EXPECTED_TASK_COUNT)
    if selected_task_count < 1 or selected_task_count > EXPECTED_TASK_COUNT:
        raise PluginError(f"--n-tasks must be between 1 and {EXPECTED_TASK_COUNT}", 2)
    arms: list[JsonMap] = []
    for model in models:
        arm_slug = slug(model)
        job_name = f"{args.run_id}-{arm_slug}"
        arms.append(
            {
                "id": arm_slug,
                "model": model,
                "status": "planned",
                "jobName": job_name,
                "jobDirectory": str(jobs_dir / job_name),
                "configPath": str(output / "configs" / f"{arm_slug}.json"),
                "serverLogPath": str(output / "server-logs" / f"{arm_slug}.log"),
                "serverPid": None,
                "startedAt": None,
                "finishedAt": None,
                "error": None,
                "summary": None,
            }
        )
    storage_bytes = int(args.max_additional_storage_gb * 1024**3)
    manifest: JsonMap = {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {"id": "terminal-bench-2-1", "family": "terminal-bench"},
        "status": "planned",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "dataset": {
            "path": f"{DATASET_NAME}@{DATASET_REF}",
            "pairCount": selected_task_count,
            "sha256": DATASET_REF,
            "name": DATASET_NAME,
            "ref": DATASET_REF,
            "sourceCommit": DATASET_SOURCE_COMMIT,
            "expectedFullTaskCount": EXPECTED_TASK_COUNT,
            "includeTasks": include_tasks,
            "nTasks": args.n_tasks,
        },
        "command": [PLUGIN_NAME, "run", str(run_manifest)],
        "pins": {
            "harborVersion": HARBOR_VERSION,
            "datasetRef": DATASET_REF,
            "datasetSourceCommit": DATASET_SOURCE_COMMIT,
        },
        "comparison": {
            "agent": "terminus-2",
            "temperature": args.temperature,
            "attemptsPerTask": args.attempts,
            "concurrency": args.concurrency,
            "timeoutMultiplier": args.timeout_multiplier,
            "contextSize": args.context_size,
            "maxOutputTokens": args.max_output_tokens,
        },
        "runtime": {
            "createsDockerRuntime": False,
            "dockerExecutable": args.docker,
            "dockerContext": args.docker_context,
            "baselineDockerUsageBytes": None,
            "maximumAdditionalStorageBytes": storage_bytes,
            "storageLimitAction": "stop-harbor-without-pruning",
            "environmentDelete": True,
        },
        "server": {
            "managedByPlugin": True,
            "mereRunExecutable": args.mere_run,
            "engine": args.engine,
            "memoryGuard": DEFAULT_MEMORY_GUARD,
            "host": "127.0.0.1",
            "port": args.port,
            "endpoint": endpoint,
            "apiBase": endpoint + "/v1",
            "contextSize": args.context_size,
            "maxActiveRequests": 1,
        },
        "harbor": {"executable": args.harbor, "version": HARBOR_VERSION},
        "models": models,
        "arms": arms,
        "artifacts": {
            "runManifest": str(run_manifest),
            "jobsDirectory": str(jobs_dir),
            "report": str(output / "report.json"),
            "bundle": str(output / "artifact-bundle.json"),
        },
        "cleanup": {"default": "stop", "status": "not-started"},
    }
    return manifest


def update_manifest(path: pathlib.Path, manifest: JsonMap) -> None:
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    harbor = harbor_inspection(args.harbor, timeout=30.0 if args.deep else 5.0)
    mere_run = mere_run_inspection(args.mere_run)
    selected_models = args.models or list(DEFAULT_MODELS)
    if args.deep:
        docker = docker_inspection(args.docker, args.docker_context)
        model_reports = [
            {
                **mere_run_preflight(
                    args.mere_run,
                    engine=args.engine,
                    model=model,
                    port=args.port,
                    context_size=args.context_size,
                ),
                "preflighted": True,
            }
            for model in selected_models
        ]
    else:
        docker = docker_quick_inspection(args.docker, args.docker_context)
        model_reports = [{"model": model, "preflighted": False} for model in selected_models]
    ready = (
        harbor.get("ready") is True
        and docker.get("ready") is True
        and mere_run.get("ready") is True
        and (not args.deep or all(report.get("ready") is True for report in model_reports))
    )
    report: JsonMap = {
        "plugin": PLUGIN_NAME,
        "version": __version__,
        "mode": "deep" if args.deep else "quick",
        "readinessScope": "dependencies-and-models" if args.deep else "dependencies",
        "ready": ready,
        "mutated": False,
        "harbor": harbor,
        "docker": docker,
        "mereRun": mere_run,
        "models": model_reports,
        "dataset": {
            "name": DATASET_NAME,
            "ref": DATASET_REF,
            "sourceCommit": DATASET_SOURCE_COMMIT,
            "taskCount": EXPECTED_TASK_COUNT,
        },
    }
    print_json(report)
    return 0 if ready else 3


def command_plan(args: argparse.Namespace) -> int:
    manifest = planned_manifest(args)
    artifacts = as_map(manifest["artifacts"], "manifest.artifacts")
    path = pathlib.Path(string_field(artifacts, "runManifest", "manifest.artifacts"))
    if path.exists() and not args.force:
        raise PluginError(f"run manifest already exists: {path}; pass --force to replace the plan", 2)
    update_manifest(path, manifest)
    print_json(manifest)
    return 0


def harbor_job_config(manifest: JsonMap, arm: JsonMap) -> JsonMap:
    dataset = as_map(manifest.get("dataset"), "manifest.dataset")
    comparison = as_map(manifest.get("comparison"), "manifest.comparison")
    server = as_map(manifest.get("server"), "manifest.server")
    dataset_config: JsonMap = {
        "name": string_field(dataset, "name", "manifest.dataset"),
        "ref": string_field(dataset, "ref", "manifest.dataset"),
    }
    include_tasks = string_list(dataset.get("includeTasks", []), "manifest.dataset.includeTasks")
    if include_tasks:
        dataset_config["task_names"] = include_tasks
    n_tasks = dataset.get("nTasks")
    if isinstance(n_tasks, int) and not isinstance(n_tasks, bool):
        dataset_config["n_tasks"] = n_tasks
    model = string_field(arm, "model", "manifest.arm")
    return {
        "job_name": string_field(arm, "jobName", "manifest.arm"),
        "jobs_dir": str(pathlib.Path(string_field(arm, "jobDirectory", "manifest.arm")).parent),
        "n_attempts": int_field(comparison, "attemptsPerTask", "manifest.comparison"),
        "n_concurrent_trials": int_field(comparison, "concurrency", "manifest.comparison"),
        "timeout_multiplier": float_field(comparison, "timeoutMultiplier", "manifest.comparison"),
        "agents": [
            {
                "name": "terminus-2",
                "model_name": f"openai/{model}",
                "kwargs": {
                    "api_base": string_field(server, "apiBase", "manifest.server"),
                    "temperature": float_field(comparison, "temperature", "manifest.comparison"),
                    "enable_summarize": True,
                    "model_info": {
                        "max_input_tokens": int_field(comparison, "contextSize", "manifest.comparison"),
                        "max_output_tokens": int_field(comparison, "maxOutputTokens", "manifest.comparison"),
                        "input_cost_per_token": 0,
                        "output_cost_per_token": 0,
                    },
                },
            }
        ],
        "datasets": [dataset_config],
        "environment": {"type": "docker", "delete": True},
    }


def endpoint_json(url: str, timeout: float = 5.0) -> JsonMap:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return as_map(json.loads(response.read()), f"endpoint {url}")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise PluginError(f"endpoint unavailable at {url}: {error}", 3) from error


def wait_for_server(process: subprocess.Popen[str], endpoint: str, model: str, timeout: float = 600.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "server has not responded"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise PluginError(f"mere.run server for {model} exited before becoming healthy", 4)
        try:
            endpoint_json(endpoint + "/health")
            models = endpoint_json(endpoint + "/v1/models")
            entries = as_list(models.get("data", []), "models.data")
            identifiers = {
                item.get("id")
                for item in entries
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if model in identifiers:
                return
            last_error = f"server model list did not include {model}"
        except PluginError as error:
            last_error = str(error)
        time.sleep(1.0)
    raise PluginError(f"mere.run server for {model} did not become ready: {last_error}", 4)


def start_server(manifest: JsonMap, arm: JsonMap, log_stream: TextIO) -> subprocess.Popen[str]:
    server = as_map(manifest.get("server"), "manifest.server")
    model = string_field(arm, "model", "manifest.arm")
    mere_run = string_field(server, "mereRunExecutable", "manifest.server")
    path = executable_path(mere_run)
    if path is None:
        raise PluginError(f"mere.run executable not found: {mere_run}", 3)
    argv = [
        path,
        "api",
        "serve",
        "--engine",
        string_field(server, "engine", "manifest.server"),
        "--model",
        model,
        "--host",
        string_field(server, "host", "manifest.server"),
        "--port",
        str(int_field(server, "port", "manifest.server")),
        "--context-size",
        str(int_field(server, "contextSize", "manifest.server")),
        "--memory-guard",
        string_field(server, "memoryGuard", "manifest.server"),
        "--max-active-requests",
        "1",
    ]
    log(f"Starting mere.run server for {model}")
    try:
        return subprocess.Popen(
            argv,
            text=True,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        raise PluginError(f"could not start mere.run server: {error}", 4) from error


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30.0)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10.0)


def process_command(pid: int) -> str | None:
    completed = capture(["/bin/ps", "-p", str(pid), "-o", "command="], timeout=10.0)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def stop_recorded_server(arm: JsonMap) -> bool:
    pid = arm.get("serverPid")
    if isinstance(pid, bool) or not isinstance(pid, int):
        return False
    command = process_command(pid)
    model = string_field(arm, "model", "manifest.arm")
    if command is None:
        arm["serverPid"] = None
        return False
    if "mere.run" not in command or "api serve" not in command or model not in command:
        raise PluginError(f"refusing to stop PID {pid}; it does not match the recorded mere.run server", 4)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    arm["serverPid"] = None
    return True


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30.0)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10.0)


def run_harbor(
    manifest_path: pathlib.Path,
    manifest: JsonMap,
    arm: JsonMap,
    *,
    log_stream: TextIO,
    check_interval: float = 15.0,
) -> int:
    harbor = as_map(manifest.get("harbor"), "manifest.harbor")
    runtime = as_map(manifest.get("runtime"), "manifest.runtime")
    executable = string_field(harbor, "executable", "manifest.harbor")
    harbor_argv = harbor_command(executable)
    if harbor_argv is None:
        raise PluginError(f"Harbor executable not found: {executable}", 3)
    config_path = pathlib.Path(string_field(arm, "configPath", "manifest.arm"))
    argv = [*harbor_argv, "run", "--config", str(config_path), "--yes"]
    context_value = runtime.get("dockerContext")
    context = context_value if isinstance(context_value, str) else None
    environment = harbor_environment(context)
    log(f"Starting Harbor job {string_field(arm, 'jobName', 'manifest.arm')}")
    try:
        process = subprocess.Popen(
            argv,
            env=environment,
            text=True,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        raise PluginError(f"could not start Harbor: {error}", 4) from error
    try:
        docker_requested = string_field(runtime, "dockerExecutable", "manifest.runtime")
        docker = executable_path(docker_requested)
        if docker is None:
            raise PluginError(f"Docker executable not found: {docker_requested}", 3)
        baseline = runtime.get("baselineDockerUsageBytes")
        if isinstance(baseline, bool) or not isinstance(baseline, int):
            raise PluginError("run manifest is missing the Docker storage baseline", 3)
        ceiling = int_field(runtime, "maximumAdditionalStorageBytes", "manifest.runtime")
        while process.poll() is None:
            time.sleep(check_interval)
            current = docker_usage_bytes_with_retry(docker, context)
            additional = max(0, current - baseline)
            runtime["currentDockerUsageBytes"] = current
            runtime["additionalDockerUsageBytes"] = additional
            update_manifest(manifest_path, manifest)
            if additional > ceiling:
                raise PluginError(
                    f"Docker storage increased by {additional} bytes, exceeding the planned {ceiling}-byte ceiling; "
                    "Harbor was stopped and no images were pruned",
                    5,
                )
        return process.returncode or 0
    finally:
        terminate_process(process)


def iso_duration_seconds(started: object, finished: object) -> float | None:
    if not isinstance(started, str) or not isinstance(finished, str):
        return None
    try:
        start = dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
        end = dt.datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (end - start).total_seconds())


def timing_duration_seconds(value: object) -> float | None:
    if not isinstance(value, dict):
        return None
    timing = cast(JsonMap, value)
    return iso_duration_seconds(timing.get("started_at"), timing.get("finished_at"))


def trial_summaries(job_dir: pathlib.Path) -> list[JsonMap]:
    summaries: list[JsonMap] = []
    if not job_dir.is_dir():
        return summaries
    for result_path in sorted(job_dir.glob("*/result.json")):
        try:
            result = load_json(result_path, f"trial result {result_path}")
        except PluginError:
            continue
        verifier = result.get("verifier_result")
        rewards: JsonMap = {}
        if isinstance(verifier, dict) and isinstance(verifier.get("rewards"), dict):
            rewards = cast(JsonMap, verifier["rewards"])
        reward = rewards.get("reward")
        numeric_reward = float(reward) if isinstance(reward, (int, float)) and not isinstance(reward, bool) else None
        exception = result.get("exception_info")
        exception_type = exception.get("exception_type") if isinstance(exception, dict) else None
        agent = result.get("agent_result")
        agent_map = cast(JsonMap, agent) if isinstance(agent, dict) else {}
        summaries.append(
            {
                "task": result.get("task_name"),
                "trial": result.get("trial_name"),
                "reward": numeric_reward,
                "exception": exception_type,
                "inputTokens": agent_map.get("n_input_tokens"),
                "cacheTokens": agent_map.get("n_cache_tokens"),
                "outputTokens": agent_map.get("n_output_tokens"),
                "durationSeconds": iso_duration_seconds(result.get("started_at"), result.get("finished_at")),
                "environmentSetupSeconds": timing_duration_seconds(result.get("environment_setup")),
                "agentSetupSeconds": timing_duration_seconds(result.get("agent_setup")),
                "agentExecutionSeconds": timing_duration_seconds(result.get("agent_execution")),
                "verifierSeconds": timing_duration_seconds(result.get("verifier")),
                "resultPath": str(result_path),
            }
        )
    return summaries


def summarize_job(job_dir: pathlib.Path) -> JsonMap:
    result_path = job_dir / "result.json"
    result = load_json(result_path, f"Harbor job result {result_path}")
    stats = as_map(result.get("stats", {}), "job.stats")
    trials = trial_summaries(job_dir)
    scored = [trial for trial in trials if isinstance(trial.get("reward"), (int, float))]
    passed = sum(1 for trial in scored if float(cast(float, trial["reward"])) > 0)
    agent_durations = [
        float(cast(float, trial["agentExecutionSeconds"]))
        for trial in trials
        if isinstance(trial.get("agentExecutionSeconds"), (int, float))
    ]
    total_agent_seconds = sum(agent_durations) if agent_durations else None
    output_tokens = stats.get("n_output_tokens")
    output_tokens_per_agent_second = None
    if isinstance(output_tokens, int) and total_agent_seconds:
        output_tokens_per_agent_second = output_tokens / total_agent_seconds
    return {
        "jobId": result.get("id"),
        "resultPath": str(result_path),
        "totalTrials": result.get("n_total_trials"),
        "completedTrials": stats.get("n_completed_trials"),
        "erroredTrials": stats.get("n_errored_trials"),
        "cancelledTrials": stats.get("n_cancelled_trials"),
        "scoredTrials": len(scored),
        "passedTrials": passed,
        "accuracy": passed / len(scored) if scored else None,
        "inputTokens": stats.get("n_input_tokens"),
        "cacheTokens": stats.get("n_cache_tokens"),
        "outputTokens": stats.get("n_output_tokens"),
        "durationSeconds": iso_duration_seconds(result.get("started_at"), result.get("finished_at")),
        "agentExecutionSeconds": total_agent_seconds,
        "meanAgentExecutionSeconds": statistics.fmean(agent_durations) if agent_durations else None,
        "medianAgentExecutionSeconds": statistics.median(agent_durations) if agent_durations else None,
        "outputTokensPerAgentSecond": output_tokens_per_agent_second,
        "trials": trials,
    }


def incomplete_job_error(
    summary: JsonMap,
    *,
    expected_task_count: int | None = None,
    attempts_per_task: int | None = None,
) -> str | None:
    total = summary.get("totalTrials")
    completed = summary.get("completedTrials")
    errored = summary.get("erroredTrials")
    cancelled = summary.get("cancelledTrials")
    scored = summary.get("scoredTrials")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or isinstance(completed, bool)
        or not isinstance(completed, int)
        or isinstance(errored, bool)
        or not isinstance(errored, int)
        or isinstance(cancelled, bool)
        or not isinstance(cancelled, int)
        or isinstance(scored, bool)
        or not isinstance(scored, int)
    ):
        return "Harbor result did not contain complete integer trial counts"
    if total < 1:
        return "Harbor result contained no trials"
    if expected_task_count is not None and attempts_per_task is not None:
        expected_trials = expected_task_count * attempts_per_task
        if total != expected_trials:
            return f"Harbor planned {expected_trials} trials but reported {total}"
    if completed != total or cancelled != 0 or scored != total:
        return (
            "Harbor did not produce a valid score for every trial "
            f"(total={total}, completed={completed}, scored={scored}, errored={errored}, cancelled={cancelled})"
        )
    if expected_task_count is not None and attempts_per_task is not None:
        trials = as_list(summary.get("trials", []), "summary.trials")
        task_counts: Counter[str] = Counter()
        for value in trials:
            trial = as_map(value, "summary.trial")
            task = trial.get("task")
            if not isinstance(task, str) or not task:
                return "Harbor produced a scored trial without a task name"
            task_counts[task] += 1
        if len(task_counts) != expected_task_count:
            return f"Harbor planned {expected_task_count} tasks but produced {len(task_counts)} unique tasks"
        wrong_attempts = sorted(task for task, count in task_counts.items() if count != attempts_per_task)
        if wrong_attempts:
            return (
                f"Harbor did not produce exactly {attempts_per_task} attempts for every task "
                f"({len(wrong_attempts)} tasks had a different count)"
            )
    return None


def planned_trial_counts(manifest: JsonMap) -> tuple[int, int]:
    dataset = as_map(manifest.get("dataset"), "manifest.dataset")
    comparison = as_map(manifest.get("comparison"), "manifest.comparison")
    return (
        int_field(dataset, "pairCount", "manifest.dataset"),
        int_field(comparison, "attemptsPerTask", "manifest.comparison"),
    )


def model_task_rewards(summary: JsonMap) -> dict[str, float]:
    trials = as_list(summary.get("trials", []), "summary.trials")
    rewards: dict[str, list[float]] = defaultdict(list)
    for value in trials:
        trial = as_map(value, "summary.trial")
        task = trial.get("task")
        reward = trial.get("reward")
        if isinstance(task, str) and isinstance(reward, (int, float)) and not isinstance(reward, bool):
            rewards[task].append(float(reward))
    return {task: sum(values) / len(values) for task, values in rewards.items()}


def model_task_agent_seconds(summary: JsonMap) -> dict[str, float]:
    trials = as_list(summary.get("trials", []), "summary.trials")
    durations: dict[str, list[float]] = defaultdict(list)
    for value in trials:
        trial = as_map(value, "summary.trial")
        task = trial.get("task")
        duration = trial.get("agentExecutionSeconds")
        if isinstance(task, str) and isinstance(duration, (int, float)) and not isinstance(duration, bool):
            durations[task].append(float(duration))
    return {task: statistics.fmean(values) for task, values in durations.items()}


def comparison_report(manifest: JsonMap) -> JsonMap:
    arms = [as_map(value, "manifest.arm") for value in as_list(manifest.get("arms", []), "manifest.arms")]
    completed = [arm for arm in arms if arm.get("status") == "succeeded" and isinstance(arm.get("summary"), dict)]
    arm_reports = [
        {"model": arm.get("model"), "status": arm.get("status"), "summary": arm.get("summary")} for arm in arms
    ]
    pairwise: JsonMap | None = None
    if len(completed) >= 2:
        left = completed[0]
        right = completed[1]
        left_summary = as_map(left.get("summary"), "left.summary")
        right_summary = as_map(right.get("summary"), "right.summary")
        left_rewards = model_task_rewards(left_summary)
        right_rewards = model_task_rewards(right_summary)
        common = sorted(set(left_rewards) & set(right_rewards))
        left_seconds = model_task_agent_seconds(left_summary)
        right_seconds = model_task_agent_seconds(right_summary)
        common_timings = sorted(set(left_seconds) & set(right_seconds))
        left_wins = sum(left_rewards[task] > right_rewards[task] for task in common)
        right_wins = sum(right_rewards[task] > left_rewards[task] for task in common)
        pairwise = {
            "leftModel": left.get("model"),
            "rightModel": right.get("model"),
            "matchedTasks": len(common),
            "leftWins": left_wins,
            "rightWins": right_wins,
            "ties": len(common) - left_wins - right_wins,
            "leftOnlyPassed": [task for task in common if left_rewards[task] > 0 and right_rewards[task] <= 0],
            "rightOnlyPassed": [task for task in common if right_rewards[task] > 0 and left_rewards[task] <= 0],
            "matchedTimedTasks": len(common_timings),
            "leftFasterTasks": sum(left_seconds[task] < right_seconds[task] for task in common_timings),
            "rightFasterTasks": sum(right_seconds[task] < left_seconds[task] for task in common_timings),
            "timingTies": sum(left_seconds[task] == right_seconds[task] for task in common_timings),
            "leftAgentExecutionSeconds": sum(left_seconds[task] for task in common_timings),
            "rightAgentExecutionSeconds": sum(right_seconds[task] for task in common_timings),
        }
    return {
        "contractVersion": "mere.run/terminal-bench-report.v1",
        "runId": manifest.get("runId"),
        "createdAt": now_iso(),
        "pins": manifest.get("pins"),
        "dataset": manifest.get("dataset"),
        "comparisonSettings": manifest.get("comparison"),
        "arms": arm_reports,
        "pairwise": pairwise,
    }


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_artifact_bundle(manifest_path: pathlib.Path, manifest: JsonMap) -> JsonMap:
    artifacts = as_map(manifest.get("artifacts"), "manifest.artifacts")
    report_path = pathlib.Path(string_field(artifacts, "report", "manifest.artifacts"))
    bundle_path = pathlib.Path(string_field(artifacts, "bundle", "manifest.artifacts"))
    candidates = [manifest_path, report_path]
    for arm_value in as_list(manifest.get("arms", []), "manifest.arms"):
        arm = as_map(arm_value, "manifest.arm")
        server_log = pathlib.Path(string_field(arm, "serverLogPath", "manifest.arm"))
        job_directory = pathlib.Path(string_field(arm, "jobDirectory", "manifest.arm"))
        candidates.extend(
            [
                pathlib.Path(string_field(arm, "configPath", "manifest.arm")),
                server_log,
                server_log.with_name(server_log.stem + "-harbor.log"),
                job_directory / "job.log",
                job_directory / "result.json",
            ]
        )
        for pattern in (
            "*/result.json",
            "*/exception.txt",
            "*/agent/trajectory.json",
            "*/verifier/reward.txt",
            "*/verifier/reward.json",
            "*/verifier/ctrf.json",
            "*/verifier/test-stdout.txt",
        ):
            candidates.extend(sorted(job_directory.glob(pattern)))
    unique_candidates = sorted(set(candidates), key=str)
    files = [
        {"path": str(path), "sha256": sha256_file(path), "kind": path.name}
        for path in unique_candidates
        if path.is_file()
    ]
    bundle: JsonMap = {
        "contractVersion": "mere.run/artifact-bundle.v1",
        "createdAt": now_iso(),
        "runManifest": str(manifest_path),
        "files": files,
    }
    write_json(bundle_path, bundle)
    return bundle


def validate_execution_preflight(
    manifest: JsonMap,
    run_directory: pathlib.Path,
) -> tuple[str, str, int]:
    harbor_config = as_map(manifest.get("harbor"), "manifest.harbor")
    runtime = as_map(manifest.get("runtime"), "manifest.runtime")
    server = as_map(manifest.get("server"), "manifest.server")
    harbor_report = harbor_inspection(string_field(harbor_config, "executable", "manifest.harbor"))
    if harbor_report.get("ready") is not True:
        raise PluginError(str(harbor_report.get("error", "Harbor is not ready")), 3)
    context_value = runtime.get("dockerContext")
    context = context_value if isinstance(context_value, str) else None
    docker_report = docker_inspection(
        string_field(runtime, "dockerExecutable", "manifest.runtime"),
        context,
    )
    if docker_report.get("ready") is not True:
        raise PluginError(str(docker_report.get("error", "Docker is not ready")), 3)
    docker = string_field(runtime, "dockerExecutable", "manifest.runtime")
    docker_path = executable_path(docker)
    if docker_path is None:
        raise PluginError(f"Docker executable not found: {docker}", 3)
    validate_docker_bind_mount(docker_path, context, run_directory)
    usage = docker_usage_bytes_with_retry(docker_path, context)
    record_docker_usage(runtime, usage)
    mere_run = string_field(server, "mereRunExecutable", "manifest.server")
    mere_path = executable_path(mere_run)
    if mere_path is None:
        raise PluginError(f"mere.run executable not found: {mere_run}", 3)
    return docker_path, mere_path, usage


def execute_arm(manifest_path: pathlib.Path, manifest: JsonMap, arm: JsonMap) -> None:
    model = string_field(arm, "model", "manifest.arm")
    server = as_map(manifest.get("server"), "manifest.server")
    config_path = pathlib.Path(string_field(arm, "configPath", "manifest.arm"))
    server_log_path = pathlib.Path(string_field(arm, "serverLogPath", "manifest.arm"))
    job_dir = pathlib.Path(string_field(arm, "jobDirectory", "manifest.arm"))
    write_json(config_path, harbor_job_config(manifest, arm))
    arm["status"] = "starting-server"
    arm["startedAt"] = now_iso()
    arm["finishedAt"] = None
    arm["error"] = None
    update_manifest(manifest_path, manifest)
    server_log_path.parent.mkdir(parents=True, exist_ok=True)
    with server_log_path.open("a", encoding="utf-8") as server_log:
        process = start_server(manifest, arm, server_log)
        arm["serverPid"] = process.pid
        update_manifest(manifest_path, manifest)
        try:
            endpoint = string_field(server, "endpoint", "manifest.server")
            wait_for_server(process, endpoint, model)
            arm["status"] = "running"
            update_manifest(manifest_path, manifest)
            harbor_log_path = server_log_path.with_name(server_log_path.stem + "-harbor.log")
            with harbor_log_path.open("a", encoding="utf-8") as harbor_log:
                return_code = run_harbor(manifest_path, manifest, arm, log_stream=harbor_log)
            if return_code != 0:
                raise PluginError(f"Harbor exited with status {return_code}; see {harbor_log_path}", 4)
            summary = summarize_job(job_dir)
            arm["summary"] = summary
            expected_task_count, attempts_per_task = planned_trial_counts(manifest)
            incomplete = incomplete_job_error(
                summary,
                expected_task_count=expected_task_count,
                attempts_per_task=attempts_per_task,
            )
            if incomplete is not None:
                raise PluginError(f"{incomplete}; see {job_dir / 'result.json'}", 4)
            arm["status"] = "succeeded"
            arm["finishedAt"] = now_iso()
        finally:
            stop_process(process)
            arm["serverPid"] = None
            update_manifest(manifest_path, manifest)


def execute_manifest(path: pathlib.Path, *, resume: bool) -> JsonMap:
    manifest = load_json(path, "run manifest")
    plugin = as_map(manifest.get("plugin"), "manifest.plugin")
    if string_field(plugin, "name", "manifest.plugin") != PLUGIN_NAME:
        raise PluginError(f"run manifest does not belong to {PLUGIN_NAME}", 2)
    status = manifest.get("status")
    if status == "succeeded" and not resume:
        raise PluginError("run already succeeded; use report to inspect it", 2)
    arms = [as_map(value, "manifest.arm") for value in as_list(manifest.get("arms", []), "manifest.arms")]
    try:
        validate_execution_preflight(manifest, path.parent)
        manifest["status"] = "running"
        manifest.pop("error", None)
        update_manifest(path, manifest)
        for arm in arms:
            if arm.get("status") == "succeeded":
                continue
            try:
                execute_arm(path, manifest, arm)
            except PluginError as error:
                arm["status"] = "failed"
                arm["finishedAt"] = now_iso()
                arm["error"] = str(error)
                raise
        manifest["status"] = "succeeded"
    except PluginError as error:
        manifest["status"] = "failed"
        manifest["error"] = str(error)
        update_manifest(path, manifest)
        report = comparison_report(manifest)
        report_path = pathlib.Path(string_field(as_map(manifest["artifacts"], "manifest.artifacts"), "report", "manifest.artifacts"))
        write_json(report_path, report)
        write_artifact_bundle(path, manifest)
        raise
    manifest.pop("error", None)
    update_manifest(path, manifest)
    report = comparison_report(manifest)
    report_path = pathlib.Path(string_field(as_map(manifest["artifacts"], "manifest.artifacts"), "report", "manifest.artifacts"))
    write_json(report_path, report)
    write_artifact_bundle(path, manifest)
    return manifest


def command_run(args: argparse.Namespace) -> int:
    result = execute_manifest(args.run_manifest.expanduser().resolve(), resume=False)
    print_json(result)
    return 0


def command_resume(args: argparse.Namespace) -> int:
    result = execute_manifest(args.run_manifest.expanduser().resolve(), resume=True)
    print_json(result)
    return 0


def command_report(args: argparse.Namespace) -> int:
    path = args.run_manifest.expanduser().resolve()
    manifest = load_json(path, "run manifest")
    expected_task_count, attempts_per_task = planned_trial_counts(manifest)
    for value in as_list(manifest.get("arms", []), "manifest.arms"):
        arm = as_map(value, "manifest.arm")
        job_dir = pathlib.Path(string_field(arm, "jobDirectory", "manifest.arm"))
        if (job_dir / "result.json").is_file():
            summary = summarize_job(job_dir)
            arm["summary"] = summary
            incomplete = incomplete_job_error(
                summary,
                expected_task_count=expected_task_count,
                attempts_per_task=attempts_per_task,
            )
            if arm.get("status") == "succeeded" and incomplete is not None:
                arm["status"] = "failed"
                arm["error"] = incomplete
                manifest["status"] = "failed"
                manifest["error"] = incomplete
    report = comparison_report(manifest)
    artifacts = as_map(manifest.get("artifacts"), "manifest.artifacts")
    report_path = pathlib.Path(string_field(artifacts, "report", "manifest.artifacts"))
    write_json(report_path, report)
    update_manifest(path, manifest)
    write_artifact_bundle(path, manifest)
    print_json(report)
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    path = args.run_manifest.expanduser().resolve()
    manifest = load_json(path, "run manifest")
    stopped: list[str] = []
    for value in as_list(manifest.get("arms", []), "manifest.arms"):
        arm = as_map(value, "manifest.arm")
        if stop_recorded_server(arm):
            stopped.append(string_field(arm, "model", "manifest.arm"))
    cleanup = as_map(manifest.get("cleanup"), "manifest.cleanup")
    cleanup["status"] = "succeeded"
    manifest["cleanupReceipt"] = {
        "stoppedServers": stopped,
        "dockerImagesPruned": False,
        "dockerRuntimeDeleted": False,
        "artifactsDeleted": False,
    }
    if manifest.get("status") in {"planned", "running"}:
        manifest["status"] = "cleanup-only"
    update_manifest(path, manifest)
    print_json(manifest)
    return 0


def command_internal_harbor(args: argparse.Namespace) -> int:
    try:
        import harbor.cli.main as harbor_cli
    except ImportError as error:
        raise PluginError(f"the pinned Harbor runtime is unavailable: {error}; reinstall the plugin", 3) from error
    app = cast(object, getattr(harbor_cli, "app", None))
    if not callable(app):
        raise PluginError("the pinned Harbor runtime has no CLI entrypoint", 3)
    result = app(args=args.harbor_args, prog_name="harbor", standalone_mode=False)
    return result if isinstance(result, int) else 0


def add_shared_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--harbor", default="harbor", help=f"Harbor executable; must report {HARBOR_VERSION}.")
    parser.add_argument("--docker", default="docker", help="Docker executable.")
    parser.add_argument("--docker-context", help="Existing Docker context to use. The plugin never creates one.")
    parser.add_argument("--mere-run", default="mere.run", help="mere.run executable.")
    parser.add_argument("--engine", default=DEFAULT_ENGINE, help="mere.run API serving engine.")
    parser.add_argument("--model", dest="models", action="append", help="Managed model id. Repeat to compare models.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Loopback port for the managed mere.run server.")
    parser.add_argument("--context-size", type=int, default=DEFAULT_CONTEXT_SIZE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME)
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print the plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check dependencies without changing local state.")
    add_shared_runtime_args(doctor)
    doctor.add_argument(
        "--deep",
        action="store_true",
        help="Also inspect Docker storage and preflight each selected model; this can take several minutes.",
    )
    doctor.set_defaults(func=command_doctor)

    plan = sub.add_parser("plan", help="Write a pinned benchmark run manifest.")
    add_shared_runtime_args(plan)
    plan.add_argument("--output", required=True, type=pathlib.Path, help="Run output directory.")
    plan.add_argument("--run-id", default=default_run_id())
    plan.add_argument("--attempts", type=int, default=1, help="Attempts per task. Leaderboard submissions require 5.")
    plan.add_argument("--concurrency", type=int, default=1, help="Concurrent Harbor trials.")
    plan.add_argument("--temperature", type=float, default=0.7)
    plan.add_argument("--timeout-multiplier", type=float, default=1.0)
    plan.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    plan.add_argument("--include-task", dest="include_tasks", action="append", help="Task name or glob to include.")
    plan.add_argument("--n-tasks", type=int, help="Maximum task count after filters.")
    plan.add_argument(
        "--max-additional-storage-gb",
        type=float,
        default=DEFAULT_STORAGE_GIB,
        help="Stop Harbor if Docker-reported storage grows past this many GiB.",
    )
    plan.add_argument("--force", action="store_true", help="Replace an existing plan at the exact output path.")
    plan.set_defaults(func=command_plan)

    run = sub.add_parser("run", help="Execute pending model arms.")
    run.add_argument("run_manifest", type=pathlib.Path)
    run.set_defaults(func=command_run)

    resume = sub.add_parser("resume", help="Resume incomplete model arms.")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.set_defaults(func=command_resume)

    report = sub.add_parser("report", help="Rebuild the matched comparison report.")
    report.add_argument("run_manifest", type=pathlib.Path)
    report.set_defaults(func=command_report)

    cleanup = sub.add_parser("cleanup", help="Stop only the server process recorded by the run.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=command_cleanup)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if arguments[:1] == ["_harbor"]:
            return command_internal_harbor(argparse.Namespace(harbor_args=arguments[1:]))
        args = parser.parse_args(arguments)
        func = cast(object, args.func)
        if not callable(func):
            raise PluginError("command handler is unavailable", 2)
        return int(func(args))
    except PluginError as error:
        eprint(f"error: {error}")
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

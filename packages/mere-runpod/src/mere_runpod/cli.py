from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.resources
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import __version__


PLUGIN_NAME = "mere-runpod"
DEFAULT_IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
DEFAULT_GPU = "NVIDIA H100 80GB HBM3"
DEFAULT_SSH_KEY = pathlib.Path.home() / ".runpod" / "ssh" / "runpodctl-ssh-key"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
HF_TOKEN_NAMES = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"
RUNPOD_REST_URL = "https://rest.runpod.io/v1"


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


class RunPodAPIError(PluginError):
    pass


@dataclass(frozen=True)
class DatasetInfo:
    path: pathlib.Path
    pair_count: int
    sha256: str
    missing_captions: tuple[str, ...]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def log(message: str) -> None:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%SZ")
    eprint(f"[{stamp}] {message}")


def write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def load_env_file(path: pathlib.Path | None) -> None:
    if path is None or not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def repo_root_candidates() -> list[pathlib.Path]:
    roots: list[pathlib.Path] = []
    here = pathlib.Path(__file__).resolve()
    roots.extend(here.parents)
    roots.extend(pathlib.Path.cwd().resolve().parents)
    roots.append(pathlib.Path.cwd().resolve())
    seen: set[pathlib.Path] = set()
    unique: list[pathlib.Path] = []
    for root in roots:
        if root not in seen:
            unique.append(root)
            seen.add(root)
    return unique


def find_repo_root() -> pathlib.Path:
    for root in repo_root_candidates():
        if (root / "contracts").is_dir() and (root / "recipes").is_dir():
            return root
    raise PluginError("could not locate mere-plugins repo root", 1)


def load_recipe(recipe: str) -> dict[str, Any]:
    path = pathlib.Path(recipe).expanduser()
    if path.is_file():
        return json.loads(path.read_text())
    for root in repo_root_candidates():
        candidate = root / "recipes" / f"{recipe}.json"
        if candidate.is_file():
            return json.loads(candidate.read_text())
    try:
        resource = importlib.resources.files("mere_runpod.recipes").joinpath(f"{recipe}.json")
        if resource.is_file():
            return json.loads(resource.read_text())
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    raise PluginError(f"recipe not found: {recipe}", 2)


def plugin_manifest() -> dict[str, Any]:
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": "mere-runpod",
        "description": "Run canonical mere.run recipes on user-owned ephemeral RunPod pods.",
        "homepage": "https://github.com/sawfwair/mere-plugins/tree/main/packages/mere-runpod",
        "commands": [
            {
                "name": "manifest",
                "description": "Print the plugin manifest.",
                "stdout": "json",
            },
            {
                "name": "doctor",
                "description": "Check local readiness and provider configuration.",
                "stdout": "json",
            },
            {
                "name": "plan",
                "description": "Create a dry-run run manifest without creating remote resources.",
                "stdout": "json",
            },
            {
                "name": "run",
                "description": "Create a RunPod pod, run the recipe, fetch artifacts, and clean up.",
                "stdout": "json",
            },
            {
                "name": "resume",
                "description": "Inspect or continue a recorded RunPod run.",
                "stdout": "json",
            },
            {
                "name": "cleanup",
                "description": "Terminate the RunPod resource referenced by a run manifest.",
                "stdout": "json",
            },
            {
                "name": "volume",
                "description": "List, create, or ensure RunPod network volumes for reusable model caches.",
                "stdout": "json",
            },
        ],
        "capabilities": [
            "remote-runner",
            "runpod",
            "train-lora",
            "artifact-fetch",
            "cleanup",
            "network-volume",
        ],
        "stdout": {
            "machineReadableByDefault": True,
            "diagnostics": "stderr",
        },
        "security": {
            "usesUserCredentials": True,
            "storesSecrets": False,
            "createsPaidResources": True,
            "cleanupDefault": "terminate",
        },
    }


def dataset_info(path: pathlib.Path) -> DatasetInfo:
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise PluginError(f"dataset directory does not exist: {path}", 2)
    image_files = sorted(
        p for p in path.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    missing = tuple(p.name for p in image_files if not p.with_suffix(".txt").is_file())
    if missing:
        raise PluginError(
            "dataset images missing same-stem .txt captions: " + ", ".join(missing[:10]),
            2,
        )
    if not image_files:
        raise PluginError(f"dataset has no image files: {path}", 2)
    hasher = hashlib.sha256()
    for file_path in sorted(path.iterdir()):
        if not file_path.is_file():
            continue
        rel = file_path.name.encode("utf-8")
        hasher.update(len(rel).to_bytes(4, "big"))
        hasher.update(rel)
        hasher.update(file_path.read_bytes())
    return DatasetInfo(
        path=path,
        pair_count=len(image_files),
        sha256="sha256:" + hasher.hexdigest(),
        missing_captions=missing,
    )


def validate_dataset_for_recipe(recipe: dict[str, Any], dataset: DatasetInfo) -> None:
    minimum = int(recipe.get("dataset", {}).get("minImages") or 1)
    if dataset.pair_count < minimum:
        raise PluginError(
            f"recipe {recipe['id']} requires at least {minimum} paired images; found {dataset.pair_count}",
            2,
        )


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def build_pack_tar_members(path: pathlib.Path) -> set[str]:
    try:
        with tarfile.open(path, "r:gz") as archive:
            return {member.name.lstrip("./") for member in archive.getmembers()}
    except (tarfile.TarError, OSError) as exc:
        raise PluginError(f"could not inspect build pack tarball {path}: {exc}", 2) from None


def is_bootstrap_build_pack(path: pathlib.Path) -> bool:
    members = build_pack_tar_members(path)
    return "source.tar.gz" in members and "bin/mere.run" in members


def recipe_requires_hf_token(recipe: dict[str, Any]) -> bool:
    model_values = recipe.get("models", {}).values()
    gated_aliases = {"image-klein-base-9b", "image-klein-9b"}
    return any(str(model) in gated_aliases for model in model_values)


def command_from_recipe(
    recipe: dict[str, Any],
    *,
    data_path: str,
    output_path: str,
    models_root: str | None = None,
) -> list[str]:
    args = recipe["training"]["arguments"]
    command: list[str] = ["mere.run"]
    if models_root:
        command.extend(["--models-root", models_root])
    command.extend(["image", "train-lora"])
    command.extend(["--data", data_path, "--output", output_path])

    for key, value in args.items():
        if key in {"--data", "--output"}:
            continue
        if isinstance(value, bool):
            if value:
                command.append(key)
            continue
        command.extend([key, str(value)])
    return command


def remote_model_pull_ids(manifest: dict[str, Any]) -> list[str]:
    pull_ids: list[str] = []

    def add_model(value: Any) -> None:
        model = str(value or "")
        if not model or "/" in model or model.startswith("."):
            return
        if model not in pull_ids:
            pull_ids.append(model)

    add_model(manifest.get("recipe", {}).get("trainModel"))

    command = manifest.get("command", [])
    for index, part in enumerate(command):
        if part == "--sample-model" and index + 1 < len(command):
            add_model(command[index + 1])

    return pull_ids


def cached_build_pack_name(path: pathlib.Path, sha256: str | None) -> str:
    stem = path.name
    digest = (sha256 or "unknown").split(":", 1)[-1]
    safe_digest = re.sub(r"[^A-Fa-f0-9]", "-", digest)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "-", stem)
    return f"{safe_digest}-{safe_name}"


def remote_paths(run_id: str) -> dict[str, str]:
    root = f"/workspace/mere-runpod/{run_id}"
    return {
        "root": root,
        "dataset": f"{root}/dataset",
        "build_pack": f"{root}/build-pack",
        "build_packs": "/workspace/mere-runpod/build-packs",
        "package": f"{root}/package",
        "artifacts": f"{root}/artifacts",
        "models": "/workspace/mere-runpod/models",
        "hub": "/workspace/mere-runpod/hub",
    }


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise PluginError(
            "--run-id must start with a letter or digit and contain only letters, digits, '.', '_', or '-'",
            2,
        )


def make_run_manifest(args: argparse.Namespace, recipe: dict[str, Any], dataset: DatasetInfo) -> dict[str, Any]:
    run_id = args.run_id
    output_dir = args.output.expanduser().resolve()
    paths = remote_paths(run_id)
    output_file = f"{paths['artifacts']}/{run_id}.safetensors"
    train_command = command_from_recipe(
        recipe,
        data_path=paths["dataset"],
        output_path=output_file,
        models_root=paths["models"],
    )
    build_pack = args.build_pack.expanduser().resolve() if args.build_pack else None
    build_pack_sha256 = file_sha256(build_pack) if build_pack and build_pack.is_file() else None
    build_pack_remote_path = (
        f"{paths['build_packs']}/{cached_build_pack_name(build_pack, build_pack_sha256)}"
        if build_pack
        else None
    )
    return {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": run_id,
        "plugin": {
            "name": PLUGIN_NAME,
            "version": __version__,
        },
        "recipe": {
            "id": recipe["id"],
            "family": recipe["family"],
            "title": recipe["title"],
            "trainModel": recipe["models"]["train"],
            "applyModel": recipe["models"]["apply"],
        },
        "status": "planned",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "dataset": {
            "path": str(dataset.path),
            "pairCount": dataset.pair_count,
            "sha256": dataset.sha256,
        },
        "buildPack": {
            "path": str(build_pack) if build_pack else None,
            "sha256": build_pack_sha256,
            "remotePath": build_pack_remote_path,
            "requiredForRun": True,
        },
        "command": train_command,
        "local": {
            "output": str(output_dir),
            "runManifest": str(output_dir / "run.json"),
        },
        "remote": {
            "provider": "runpod",
            "gpu": args.gpu,
            "gpuCount": args.gpu_count,
            "image": args.image,
            "cloudType": args.cloud_type,
            "podName": args.pod_name or f"mere-runpod-{run_id}",
            "podId": None,
            "networkVolumeId": args.network_volume_id,
            "dataCenterId": args.data_center_id,
            "paths": paths,
        },
        "artifacts": {
            "localDirectory": str(output_dir / "artifacts"),
            "remoteDirectory": paths["artifacts"],
            "lora": None,
            "sha256": None,
        },
        "cleanup": {
            "default": "terminate",
            "status": "not-started",
        },
    }


def run_process(argv: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    log("$ " + shlex.join(argv))
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if input_text is not None:
        assert process.stdin is not None
        process.stdin.write(input_text)
        process.stdin.close()

    output: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        output.append(line)
        eprint(line.rstrip("\n"))
    process.stdout.close()
    returncode = process.wait()
    completed = subprocess.CompletedProcess(argv, returncode, "".join(output), "")
    if check and completed.returncode != 0:
        raise PluginError(f"command failed with exit {completed.returncode}: {shlex.join(argv)}", 1)
    return completed


def summarize_runpod_errors(errors: Any) -> str:
    if not errors:
        return "unknown RunPod API error"
    if isinstance(errors, list):
        messages = []
        for item in errors:
            if isinstance(item, dict) and item.get("message"):
                messages.append(str(item["message"]))
            else:
                messages.append(str(item))
        return "; ".join(messages[:3])
    return str(errors)


def graphql(api_key: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(
        RUNPOD_GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "mere-runpod/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RunPodAPIError(f"RunPod API HTTP {exc.code}: {exc.reason}", 4) from None
    except urllib.error.URLError as exc:
        raise RunPodAPIError(f"RunPod API request failed: {exc.reason}", 4) from None
    except TimeoutError:
        raise RunPodAPIError("RunPod API request timed out", 4) from None
    except json.JSONDecodeError as exc:
        raise RunPodAPIError(f"RunPod API returned invalid JSON: {exc}", 4) from None
    if payload.get("errors"):
        raise RunPodAPIError(summarize_runpod_errors(payload["errors"]), 4)
    return payload["data"]


def runpod_rest(api_key: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{RUNPOD_REST_URL}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "mere-runpod/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw.strip()
        raise RunPodAPIError(f"RunPod REST {method} {path} failed: {payload}", 4) from None
    except urllib.error.URLError as exc:
        raise RunPodAPIError(f"RunPod REST request failed: {exc.reason}", 4) from None
    except TimeoutError:
        raise RunPodAPIError("RunPod REST request timed out", 4) from None
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RunPodAPIError(f"RunPod REST returned invalid JSON: {exc}", 4) from None


def list_network_volumes(api_key: str) -> list[dict[str, Any]]:
    payload = runpod_rest(api_key, "GET", "/networkvolumes")
    if not isinstance(payload, list):
        raise RunPodAPIError("RunPod REST /networkvolumes returned unexpected payload", 4)
    return payload


def create_network_volume(api_key: str, *, name: str, data_center_id: str, size_gb: int) -> dict[str, Any]:
    payload = runpod_rest(
        api_key,
        "POST",
        "/networkvolumes",
        {"name": name, "dataCenterId": data_center_id, "size": size_gb},
    )
    if not isinstance(payload, dict):
        raise RunPodAPIError("RunPod REST /networkvolumes create returned unexpected payload", 4)
    return payload


def find_network_volume(volumes: list[dict[str, Any]], *, name: str, data_center_id: str) -> dict[str, Any] | None:
    for volume in volumes:
        if volume.get("name") == name and volume.get("dataCenterId") == data_center_id:
            return volume
    return None


def create_pod(args: argparse.Namespace, api_key: str, public_key: str) -> dict[str, Any]:
    env = [{"key": "PUBLIC_KEY", "value": public_key}]
    for name in HF_TOKEN_NAMES:
        if token := os.environ.get(name):
            env.append({"key": name, "value": token})
    if endpoint := os.environ.get("HF_ENDPOINT"):
        env.append({"key": "HF_ENDPOINT", "value": endpoint})

    pod_input: dict[str, Any] = {
        "cloudType": args.cloud_type,
        "gpuCount": args.gpu_count,
        "containerDiskInGb": args.container_disk_gb,
        "minVcpuCount": args.min_vcpu,
        "minMemoryInGb": args.min_memory_gb,
        "gpuTypeId": args.gpu,
        "name": args.pod_name,
        "imageName": args.image,
        "dockerArgs": "",
        "ports": "8888/http,22/tcp",
        "volumeMountPath": "/workspace",
        "env": env,
        "startSsh": True,
    }
    if args.data_center_id:
        pod_input["dataCenterId"] = args.data_center_id
    if args.network_volume_id:
        pod_input["networkVolumeId"] = args.network_volume_id
    else:
        pod_input["volumeInGb"] = args.volume_gb
    if args.allowed_cuda_versions:
        pod_input["allowedCudaVersions"] = args.allowed_cuda_versions
    query = """
    mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
      podFindAndDeployOnDemand(input: $input) {
        id
        name
        desiredStatus
        imageName
        costPerHr
        machine { gpuDisplayName location podHostId }
      }
    }
    """
    return graphql(api_key, query, {"input": pod_input})["podFindAndDeployOnDemand"]


def terminate_pod(api_key: str, pod_id: str) -> None:
    query = """
    mutation TerminatePod($input: PodTerminateInput!) {
      podTerminate(input: $input)
    }
    """
    graphql(api_key, query, {"input": {"podId": pod_id}})


def runpod_resource_missing(error: Exception) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "not found",
            "does not exist",
            "no pod",
            "already terminated",
            "already deleted",
        )
    )


def query_pod(api_key: str, pod_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", pod_id):
        raise PluginError(f"unsafe pod id: {pod_id}", 2)
    query = f"""
    query {{
      pod(input: {{podId: "{pod_id}"}}) {{
        id
        name
        desiredStatus
        imageName
        costPerHr
        runtime {{
          uptimeInSeconds
          ports {{ ip isIpPublic privatePort publicPort type }}
        }}
        machine {{ gpuDisplayName location podHostId }}
      }}
    }}
    """
    return graphql(api_key, query)["pod"]


def ssh_target(pod: dict[str, Any]) -> tuple[str, int] | None:
    for port in (pod.get("runtime") or {}).get("ports") or []:
        if str(port.get("privatePort")) == "22" and port.get("ip") and port.get("publicPort"):
            return str(port["ip"]), int(port["publicPort"])
    return None


def ssh_base(args: argparse.Namespace, target: tuple[str, int]) -> list[str]:
    host, port = target
    return [
        "ssh",
        "-i",
        str(args.ssh_key),
        "-p",
        str(port),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        f"root@{host}",
    ]


def ssh_probe(args: argparse.Namespace, target: tuple[str, int]) -> bool:
    return run_process(ssh_base(args, target) + ["true"], check=False).returncode == 0


def wait_for_ssh(args: argparse.Namespace, api_key: str, pod_id: str) -> tuple[str, int]:
    deadline = time.monotonic() + args.ssh_timeout_seconds
    last_status = "unknown"
    while time.monotonic() < deadline:
        pod = query_pod(api_key, pod_id)
        if pod is None:
            raise PluginError(f"pod disappeared before SSH became ready: {pod_id}", 4)
        last_status = pod.get("desiredStatus") or last_status
        target = ssh_target(pod)
        if target and ssh_probe(args, target):
            return target
        log(f"waiting for SSH; pod status={last_status}")
        time.sleep(15)
    raise PluginError(f"timed out waiting for SSH on pod {pod_id}; last status={last_status}", 4)


def rsync_to_remote(args: argparse.Namespace, target: tuple[str, int], source: pathlib.Path, dest: str) -> None:
    host, port = target
    source_arg = str(source)
    if source.is_dir() and not source_arg.endswith("/"):
        source_arg += "/"
    ssh = shlex.join([
        "ssh",
        "-i",
        str(args.ssh_key),
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ])
    run_process([
        "rsync",
        "-az",
        "--delete",
        "--no-owner",
        "--no-group",
        "-e",
        ssh,
        source_arg,
        f"root@{host}:{dest}",
    ])


def rsync_from_remote(args: argparse.Namespace, target: tuple[str, int], source: str, dest: pathlib.Path) -> None:
    host, port = target
    dest.mkdir(parents=True, exist_ok=True)
    ssh = shlex.join([
        "ssh",
        "-i",
        str(args.ssh_key),
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ])
    run_process(["rsync", "-az", "--no-owner", "--no-group", "-e", ssh, f"root@{host}:{source}/", str(dest)])


def remote_file_exists(args: argparse.Namespace, target: tuple[str, int], source: str) -> bool:
    probe = run_process(
        ssh_base(args, target) + ["test", "-f", source],
        check=False,
    )
    return probe.returncode == 0


def rsync_remote_file_if_exists(
    args: argparse.Namespace,
    target: tuple[str, int],
    source: str,
    dest: pathlib.Path,
) -> bool:
    host, port = target
    if not remote_file_exists(args, target, source):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    ssh = shlex.join([
        "ssh",
        "-i",
        str(args.ssh_key),
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ])
    run_process(["rsync", "-az", "--no-owner", "--no-group", "-e", ssh, f"root@{host}:{source}", str(dest)])
    return True


def ensure_remote_build_pack(
    args: argparse.Namespace,
    target: tuple[str, int],
    manifest: dict[str, Any],
) -> str:
    remote_path = manifest["buildPack"].get("remotePath")
    if not remote_path:
        raise PluginError("run manifest is missing buildPack.remotePath", 2)
    if remote_file_exists(args, target, remote_path):
        log(f"reusing cached build pack at {remote_path}")
        return remote_path
    log(f"uploading build pack cache to {remote_path}")
    parent = str(pathlib.PurePosixPath(remote_path).parent)
    ssh_script(args, target, f"mkdir -p {shlex.quote(parent)}")
    rsync_to_remote(args, target, args.build_pack, remote_path)
    return remote_path


def fetch_remote_artifacts(
    args: argparse.Namespace,
    target: tuple[str, int],
    manifest: dict[str, Any],
    output: pathlib.Path,
) -> None:
    remote_artifacts = manifest["remote"]["paths"]["artifacts"]
    local_artifacts = output / "artifacts"
    run_id = manifest["runId"]
    final_name = f"{run_id}.safetensors"

    rsync_remote_file_if_exists(
        args,
        target,
        f"{remote_artifacts}/{final_name}",
        local_artifacts / final_name,
    )
    for filename in (
        f"{run_id}.zip",
        f"{run_id}.log",
        f"{run_id}.command.txt",
        f"{run_id}.loss.csv",
        f"{run_id}.loss.html",
        f"{run_id}.events.jsonl",
        f"{run_id}.manifest.json",
        f"{run_id}.checkpoint.json",
        "run.json",
        "checkpoint.json",
    ):
        rsync_remote_file_if_exists(
            args,
            target,
            f"{remote_artifacts}/{filename}",
            local_artifacts / filename,
        )

    if args.fetch_checkpoints:
        rsync_from_remote(args, target, remote_artifacts, local_artifacts)


def ssh_script(args: argparse.Namespace, target: tuple[str, int], script: str) -> None:
    run_process(ssh_base(args, target) + ["bash", "-s"], input_text=script)


def bootstrap_script() -> str:
    return r"""
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl rsync xz-utils unzip zip tar ffmpeg python3 \
  libcurl4 libedit2 libxml2 libncurses6 zlib1g uuid-runtime \
  libopenblas0-pthread liblapacke libssl3
apt-get install -y --allow-change-held-packages --no-install-recommends libcudnn9-cuda-12
if [[ ! -f /usr/local/cuda/include/cuda_bf16.h ]]; then
  echo "CUDA development headers were not found at /usr/local/cuda/include; use a CUDA devel image." >&2
  exit 42
fi
ldconfig
if ! ldconfig -p | grep -q "libcudnn.so.9" && ! find /usr -name "libcudnn.so.9*" -print -quit | grep -q .; then
  echo "libcudnn.so.9 was not found after installing libcudnn9-cuda-12." >&2
  exit 43
fi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
"""


def remote_train_script(manifest: dict[str, Any]) -> str:
    remote = manifest["remote"]
    paths = remote["paths"]
    run_id = manifest["runId"]
    command = manifest["command"]
    build_pack_file = manifest["buildPack"].get("remotePath")
    if not build_pack_file:
        build_pack_file = f"{paths['build_pack']}/{pathlib.Path(manifest['buildPack']['path']).name}"
    command_args = command[1:]
    array_lines = "\n".join(f"  {shlex.quote(part)}" for part in command_args)
    model_pull_lines = "\n".join(
        f'"$cli" --models-root {shlex.quote(paths["models"])} model pull {shlex.quote(model_id)} || true'
        for model_id in remote_model_pull_ids(manifest)
    )
    env_lines: list[str] = []
    for name in HF_TOKEN_NAMES:
        if value := os.environ.get(name):
            env_lines.append(f"export {name}={shlex.quote(value)}")
    if endpoint := os.environ.get("HF_ENDPOINT"):
        env_lines.append(f"export HF_ENDPOINT={shlex.quote(endpoint)}")
    env_block = "\n".join(env_lines)
    return f"""
set -euo pipefail
export MERERUN_LINUX_ACCEL=cuda
export MERERUN_MLX_SWIFT_LINKAGE=cuda-prebuilt
export MERERUN_HUB_CACHE={shlex.quote(paths["hub"])}
export MERERUN_MODEL_CACHE_HOME=/workspace/mere-runpod
export MERERUN_MODELS_DIR={shlex.quote(paths["models"])}
export MLX_CUDA_USE_CUDNN_SDPA="${{MLX_CUDA_USE_CUDNN_SDPA:-0}}"
export MLX_CUDA_GRAPH_CACHE_SIZE="${{MLX_CUDA_GRAPH_CACHE_SIZE:-4096}}"
export CUDA_HOME="${{CUDA_HOME:-/usr/local/cuda}}"
export CUDA_PATH="${{CUDA_PATH:-$CUDA_HOME}}"
torch_lib="$(python3 - <<'PY' 2>/dev/null || true
import pathlib

try:
    import torch
except Exception:
    raise SystemExit(0)

print(pathlib.Path(torch.__file__).resolve().parent / "lib")
PY
)"
export PATH="$CUDA_HOME/bin:/usr/local/cuda/bin:$PATH"
if [[ -n "$torch_lib" && -d "$torch_lib" ]]; then
  export LD_LIBRARY_PATH="$torch_lib:${{LD_LIBRARY_PATH:-}}"
fi
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:$CUDA_HOME/targets/x86_64-linux/lib:/usr/local/cuda/lib64:/usr/lib/x86_64-linux-gnu:${{LD_LIBRARY_PATH:-}}"
export CPATH="$CUDA_HOME/include:/usr/local/cuda/include:${{CPATH:-}}"
export CPLUS_INCLUDE_PATH="$CUDA_HOME/include:/usr/local/cuda/include:${{CPLUS_INCLUDE_PATH:-}}"
{env_block}
if [[ -z "${{HF_TOKEN:-}}" && -n "${{HUGGING_FACE_HUB_TOKEN:-}}" ]]; then
  export HF_TOKEN="$HUGGING_FACE_HUB_TOKEN"
fi
if [[ -z "${{HUGGING_FACE_HUB_TOKEN:-}}" && -n "${{HF_TOKEN:-}}" ]]; then
  export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
fi
mkdir -p {shlex.quote(paths["package"])} {shlex.quote(paths["models"])} {shlex.quote(paths["hub"])} {shlex.quote(paths["artifacts"])}
tar --no-same-owner -xzf {shlex.quote(build_pack_file)} -C {shlex.quote(paths["package"])}
cli="$(find {shlex.quote(paths["package"])} -type f -name mere.run -perm -111 | head -n 1)"
if [[ -z "$cli" ]]; then
  echo "could not find extracted mere.run CLI" >&2
  exit 1
fi
{model_pull_lines}
train_args=(
{array_lines}
)
printf '%q ' "$cli" "${{train_args[@]}}" > {shlex.quote(paths["artifacts"])}/{shlex.quote(run_id)}.command.txt
printf '\\n' >> {shlex.quote(paths["artifacts"])}/{shlex.quote(run_id)}.command.txt
"$cli" "${{train_args[@]}}" 2>&1 | tee {shlex.quote(paths["artifacts"])}/{shlex.quote(run_id)}.log
"""


def command_doctor(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("python", True, sys.version.split()[0])
    for exe in ("ssh", "rsync"):
        path = shutil.which(exe)
        add(exe, path is not None, path or "not found")
    add("RUNPOD_API_KEY", bool(os.environ.get("RUNPOD_API_KEY")), "configured" if os.environ.get("RUNPOD_API_KEY") else "missing")
    add("sshKey", args.ssh_key.exists(), str(args.ssh_key))
    add("sshPublicKey", args.public_key_file.exists(), str(args.public_key_file))
    if args.build_pack:
        add("buildPack", args.build_pack.is_file(), str(args.build_pack))
    ok = all(item["ok"] for item in checks)
    payload = {"ok": ok, "checks": checks}
    print_json(payload)
    return 0 if ok else 3


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def command_volume(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)

    if args.volume_command == "list":
        api_key = os.environ.get("RUNPOD_API_KEY")
        if not api_key:
            raise PluginError("missing RUNPOD_API_KEY", 3)
        print_json({"volumes": list_network_volumes(api_key)})
        return 0

    if args.size_gb < 10:
        raise PluginError("--size-gb must be at least 10 for RunPod network volumes", 2)

    if getattr(args, "dry_run", False):
        print_json({
            "dryRun": True,
            "provider": "runpod",
            "action": args.volume_command,
            "createsPaidResource": args.volume_command in {"create", "ensure"},
            "request": {
                "name": args.name,
                "dataCenterId": args.data_center_id,
                "sizeGb": args.size_gb,
            },
        })
        return 0

    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        raise PluginError("missing RUNPOD_API_KEY", 3)

    if args.volume_command == "create":
        volume = create_network_volume(
            api_key,
            name=args.name,
            data_center_id=args.data_center_id,
            size_gb=args.size_gb,
        )
        print_json({"created": True, "volume": volume})
        return 0

    if args.volume_command == "ensure":
        volumes = list_network_volumes(api_key)
        existing = find_network_volume(volumes, name=args.name, data_center_id=args.data_center_id)
        if existing:
            print_json({"created": False, "volume": existing})
            return 0
        volume = create_network_volume(
            api_key,
            name=args.name,
            data_center_id=args.data_center_id,
            size_gb=args.size_gb,
        )
        print_json({"created": True, "volume": volume})
        return 0

    raise PluginError(f"unsupported volume command: {args.volume_command}", 2)


def command_plan(args: argparse.Namespace) -> int:
    recipe = load_recipe(args.recipe)
    data = dataset_info(args.data)
    validate_dataset_for_recipe(recipe, data)
    manifest = make_run_manifest(args, recipe, data)
    output = args.output.expanduser().resolve()
    write_json(output / "run.json", manifest)
    print_json(manifest)
    return 0


def validate_run_inputs(args: argparse.Namespace, recipe: dict[str, Any]) -> None:
    if getattr(args, "network_volume_id", None) and args.cloud_type != "SECURE":
        raise PluginError("RunPod network volumes for pods require --cloud-type SECURE", 2)
    if not args.build_pack or not args.build_pack.is_file():
        raise PluginError("real RunPod execution requires --build-pack pointing at a Linux CUDA mere.run tarball", 2)
    if is_bootstrap_build_pack(args.build_pack) and not args.allow_bootstrap_build_pack:
        raise PluginError(
            "refusing bootstrap/source build pack because it compiles on paid RunPod time. "
            "Use a prebuilt Linux CUDA package tarball from scripts/package-linux.sh, or pass "
            "--allow-bootstrap-build-pack only for an intentional slow debug run.",
            2,
        )
    if not args.ssh_key.exists():
        raise PluginError(f"SSH private key not found: {args.ssh_key}", 3)
    if not args.public_key_file.exists():
        raise PluginError(f"SSH public key not found: {args.public_key_file}", 3)
    if not shutil.which("ssh") or not shutil.which("rsync"):
        raise PluginError("ssh and rsync are required for real RunPod execution", 3)
    if not os.environ.get("RUNPOD_API_KEY"):
        raise PluginError("missing RUNPOD_API_KEY", 3)
    if recipe_requires_hf_token(recipe) and not any(os.environ.get(name) for name in HF_TOKEN_NAMES):
        raise PluginError("recipe requires a Hugging Face token; set HF_TOKEN or HUGGING_FACE_HUB_TOKEN", 3)


def update_manifest(path: pathlib.Path, manifest: dict[str, Any], **updates: Any) -> None:
    manifest.update(updates)
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def mark_cleanup_only_if_active(manifest: dict[str, Any]) -> None:
    if manifest.get("status") in {"planned", "running"}:
        manifest["status"] = "cleanup-only"


def command_run(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    recipe = load_recipe(args.recipe)
    data = dataset_info(args.data)
    validate_dataset_for_recipe(recipe, data)
    manifest = make_run_manifest(args, recipe, data)
    output = args.output.expanduser().resolve()
    manifest_path = output / "run.json"
    write_json(manifest_path, manifest)
    if args.dry_run:
        print_json(manifest)
        return 0

    validate_run_inputs(args, recipe)
    api_key = os.environ["RUNPOD_API_KEY"]
    public_key = args.public_key_file.read_text().strip()
    pod_id: str | None = None
    target: tuple[str, int] | None = None
    try:
        update_manifest(manifest_path, manifest, status="running")
        pod = create_pod(args, api_key, public_key)
        pod_id = pod["id"]
        manifest["remote"]["podId"] = pod_id
        manifest["remote"]["costPerHr"] = pod.get("costPerHr")
        manifest["remote"]["machine"] = pod.get("machine")
        update_manifest(manifest_path, manifest)
        target = wait_for_ssh(args, api_key, pod_id)
        manifest["remote"]["ssh"] = {"host": target[0], "port": target[1]}
        update_manifest(manifest_path, manifest)

        ssh_script(args, target, bootstrap_script())
        paths = manifest["remote"]["paths"]
        ssh_script(
            args,
            target,
            "mkdir -p "
            f"{shlex.quote(paths['dataset'])} "
            f"{shlex.quote(paths['build_pack'])} "
            f"{shlex.quote(paths['build_packs'])}",
        )
        rsync_to_remote(args, target, data.path, paths["dataset"])
        ensure_remote_build_pack(args, target, manifest)
        ssh_script(args, target, remote_train_script(manifest))
        fetch_remote_artifacts(args, target, manifest, output)

        lora = output / "artifacts" / f"{manifest['runId']}.safetensors"
        manifest["artifacts"]["lora"] = str(lora) if lora.is_file() else None
        manifest["artifacts"]["sha256"] = file_sha256(lora) if lora.is_file() else None
        update_manifest(manifest_path, manifest, status="succeeded")
    except Exception as exc:
        manifest["error"] = str(exc)
        update_manifest(manifest_path, manifest, status="failed")
        raise
    finally:
        if pod_id and not args.keep_pod:
            manifest["cleanup"]["status"] = "attempted"
            write_json(manifest_path, manifest)
            try:
                terminate_pod(api_key, pod_id)
                manifest["cleanup"]["status"] = "succeeded"
            except Exception as cleanup_error:
                manifest["cleanup"]["status"] = "failed"
                manifest["cleanup"]["error"] = str(cleanup_error)
            write_json(manifest_path, manifest)
        elif pod_id:
            manifest["cleanup"]["status"] = "skipped"
            manifest["cleanup"]["reason"] = "--keep-pod"
            write_json(manifest_path, manifest)
    print_json(manifest)
    return 0


def command_resume(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    manifest = json.loads(args.run_manifest.expanduser().read_text())
    pod_id = (manifest.get("remote") or {}).get("podId")
    payload: dict[str, Any] = {
        "runId": manifest.get("runId"),
        "status": manifest.get("status"),
        "podId": pod_id,
        "cleanup": manifest.get("cleanup"),
    }
    if pod_id and os.environ.get("RUNPOD_API_KEY"):
        payload["pod"] = query_pod(os.environ["RUNPOD_API_KEY"], pod_id)
    print_json(payload)
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    load_env_file(args.env_file)
    manifest_path = args.run_manifest.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text())
    cleanup = manifest.setdefault("cleanup", {"default": "terminate", "status": "not-started"})
    if cleanup.get("status") == "succeeded":
        cleanup["reason"] = "already cleaned up"
        mark_cleanup_only_if_active(manifest)
        update_manifest(manifest_path, manifest)
        print_json(manifest)
        return 0
    pod_id = (manifest.get("remote") or {}).get("podId")
    if not pod_id:
        cleanup["status"] = "skipped"
        cleanup["reason"] = "no pod id in run manifest"
        write_json(manifest_path, manifest)
        print_json(manifest)
        return 0
    if not os.environ.get("RUNPOD_API_KEY"):
        raise PluginError("missing RUNPOD_API_KEY", 3)
    cleanup["status"] = "attempted"
    write_json(manifest_path, manifest)
    try:
        terminate_pod(os.environ["RUNPOD_API_KEY"], pod_id)
        cleanup["status"] = "succeeded"
        mark_cleanup_only_if_active(manifest)
    except RunPodAPIError as exc:
        if runpod_resource_missing(exc):
            cleanup["status"] = "succeeded"
            cleanup["reason"] = "remote resource already absent"
            mark_cleanup_only_if_active(manifest)
        else:
            cleanup["status"] = "failed"
            cleanup["error"] = str(exc)
            update_manifest(manifest_path, manifest)
            print_json(manifest)
            return 5
    update_manifest(manifest_path, manifest)
    print_json(manifest)
    return 0


def add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--recipe", required=True, help="Recipe id from recipes/ or path to recipe JSON.")
    parser.add_argument("--data", required=True, type=pathlib.Path, help="Paired image/caption dataset directory.")
    parser.add_argument("--output", required=True, type=pathlib.Path, help="Local run output directory.")
    parser.add_argument("--run-id", default="mere-runpod-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--gpu", default=DEFAULT_GPU)
    parser.add_argument("--gpu-count", type=int, default=1)
    parser.add_argument("--cloud-type", choices=["ALL", "SECURE", "COMMUNITY"], default="SECURE")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--pod-name")
    parser.add_argument("--volume-gb", type=int, default=160)
    parser.add_argument(
        "--network-volume-id",
        help="Attach an existing RunPod network volume at /workspace instead of creating an ephemeral pod volume.",
    )
    parser.add_argument(
        "--data-center-id",
        help="Pin pod creation to a RunPod data center, required when using --network-volume-id.",
    )
    parser.add_argument("--container-disk-gb", type=int, default=120)
    parser.add_argument("--min-vcpu", type=int, default=16)
    parser.add_argument("--min-memory-gb", type=int, default=120)
    parser.add_argument("--allowed-cuda-versions", nargs="*", default=["12.4"])
    parser.add_argument("--env-file", type=pathlib.Path, default=pathlib.Path.home() / ".env")
    parser.add_argument("--ssh-key", type=pathlib.Path, default=DEFAULT_SSH_KEY)
    parser.add_argument("--public-key-file", type=pathlib.Path)
    parser.add_argument("--build-pack", type=pathlib.Path)
    parser.add_argument("--ssh-timeout-seconds", type=int, default=900)


def normalize_common_args(args: argparse.Namespace) -> argparse.Namespace:
    if hasattr(args, "run_id"):
        validate_run_id(args.run_id)
    if hasattr(args, "ssh_key"):
        args.ssh_key = args.ssh_key.expanduser().resolve()
    if hasattr(args, "public_key_file"):
        args.public_key_file = (
            args.public_key_file.expanduser().resolve()
            if args.public_key_file
            else pathlib.Path(str(args.ssh_key) + ".pub")
        )
    if hasattr(args, "build_pack") and args.build_pack:
        args.build_pack = args.build_pack.expanduser().resolve()
    if hasattr(args, "env_file") and args.env_file:
        args.env_file = args.env_file.expanduser().resolve()
    if hasattr(args, "pod_name") and not args.pod_name:
        args.pod_name = f"mere-runpod-{args.run_id}"
    if (
        getattr(args, "command", None) == "run"
        and getattr(args, "network_volume_id", None)
        and not getattr(args, "data_center_id", None)
    ):
        raise PluginError("--data-center-id is required with --network-volume-id so RunPod schedules in the volume's data center", 2)
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mere-runpod")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check local readiness.")
    doctor.add_argument("--env-file", type=pathlib.Path, default=pathlib.Path.home() / ".env")
    doctor.add_argument("--ssh-key", type=pathlib.Path, default=DEFAULT_SSH_KEY)
    doctor.add_argument("--public-key-file", type=pathlib.Path)
    doctor.add_argument("--build-pack", type=pathlib.Path)
    doctor.set_defaults(func=command_doctor)

    volume = sub.add_parser("volume", help="Manage RunPod network volumes.")
    volume_sub = volume.add_subparsers(dest="volume_command", required=True)
    volume_list = volume_sub.add_parser("list", help="List RunPod network volumes.")
    volume_list.add_argument("--env-file", type=pathlib.Path, default=pathlib.Path.home() / ".env")
    volume_list.set_defaults(func=command_volume)
    for name in ("create", "ensure"):
        volume_action = volume_sub.add_parser(name, help=f"{name.capitalize()} a RunPod network volume.")
        volume_action.add_argument("--env-file", type=pathlib.Path, default=pathlib.Path.home() / ".env")
        volume_action.add_argument("--name", required=True)
        volume_action.add_argument("--data-center-id", required=True)
        volume_action.add_argument("--size-gb", type=int, default=512)
        volume_action.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the planned volume request without creating or modifying a RunPod network volume.",
        )
        volume_action.set_defaults(func=command_volume)

    plan = sub.add_parser("plan", help="Create a dry-run plan.")
    add_common_run_args(plan)
    plan.set_defaults(func=command_plan)

    run = sub.add_parser("run", help="Run the recipe on RunPod.")
    add_common_run_args(run)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--keep-pod", action="store_true")
    run.add_argument(
        "--fetch-checkpoints",
        action="store_true",
        help="Fetch the full remote artifact directory, including intermediate checkpoint safetensors.",
    )
    run.add_argument(
        "--allow-bootstrap-build-pack",
        action="store_true",
        help="Allow source/bootstrap build packs that compile on the paid pod. Intended only for debugging.",
    )
    run.set_defaults(func=command_run)

    resume = sub.add_parser("resume", help="Inspect or continue a run manifest.")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.add_argument("--env-file", type=pathlib.Path, default=pathlib.Path.home() / ".env")
    resume.set_defaults(func=command_resume)

    cleanup = sub.add_parser("cleanup", help="Terminate resources for a run manifest.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.add_argument("--env-file", type=pathlib.Path, default=pathlib.Path.home() / ".env")
    cleanup.set_defaults(func=command_cleanup)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args = normalize_common_args(args)
        return int(args.func(args))
    except PluginError as exc:
        eprint(f"Error: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        eprint("Interrupted.")
        return 130
    except Exception as exc:
        eprint(f"Unexpected error: {exc}")
        return 1

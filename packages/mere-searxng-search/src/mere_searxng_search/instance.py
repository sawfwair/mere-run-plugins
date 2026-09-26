"""Own a loopback-only SearXNG container and its local configuration."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import NoReturn, cast

JsonMap = dict[str, object]
DEFAULT_IMAGE = "docker.io/searxng/searxng:latest"
IMAGE_PATTERN = re.compile(r"^(docker\.io|ghcr\.io)/searxng/searxng:[A-Za-z0-9_.-]+$")
OWNER_LABEL = "org.mere-run.plugin"
STATE_LABEL = "org.mere-run.instance"


class InstanceError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise InstanceError(message)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def state_dir(value: str | None = None) -> pathlib.Path:
    chosen = value or os.environ.get("MERE_SEARXNG_HOME") or "~/.local/share/mere-searxng-search"
    return pathlib.Path(chosen).expanduser().resolve()


def state_path(directory: pathlib.Path) -> pathlib.Path:
    return directory / "instance.json"


def instance_id(directory: pathlib.Path) -> str:
    return hashlib.sha256(str(directory).encode()).hexdigest()[:12]


def instance_url(directory: pathlib.Path) -> str | None:
    path = state_path(directory)
    if not path.is_file():
        return None
    record = load_state(directory)
    if record.get("status") in ("removed", "failed"):
        return None
    port = record.get("port")
    if not isinstance(port, int):
        fail("local instance has an invalid port")
    return f"http://127.0.0.1:{port}"


def write_state(directory: pathlib.Path, record: JsonMap) -> None:
    record["updatedAt"] = now_iso()
    path = state_path(directory)
    data = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()
    temporary = directory / f".instance-{secrets.token_hex(8)}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_state(directory: pathlib.Path) -> JsonMap:
    try:
        value = json.loads(state_path(directory).read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("cannot read local instance state")
    if not isinstance(value, dict):
        fail("local instance state must be an object")
    record = cast(JsonMap, value)
    if record.get("contractVersion") != "mere.run/searxng-instance.v1":
        fail("unsupported local instance state")
    if record.get("instanceId") != instance_id(directory):
        fail("local instance state belongs to another directory")
    return record


def configure(directory: pathlib.Path) -> None:
    config = directory / "config"
    cache = directory / "cache"
    config.mkdir(mode=0o700)
    cache.mkdir(mode=0o700)
    settings = config / "settings.yml"
    secret = secrets.token_hex(32)
    content = (
        "use_default_settings: true\n"
        "general:\n  instance_name: Mere SearXNG\n"
        "search:\n  formats:\n    - html\n    - json\n"
        "server:\n"
        f"  secret_key: \"{secret}\"\n"
        "  limiter: false\n  image_proxy: true\n  public_instance: false\n"
    )
    descriptor = os.open(settings, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(content)


def plan(directory: pathlib.Path, port: int, context: str | None, image: str) -> JsonMap:
    if directory.exists():
        fail("local instance directory already exists; use instance status or a different --state-dir")
    if not 1024 <= port <= 65535:
        fail("port must be between 1024 and 65535")
    if not IMAGE_PATTERN.fullmatch(image):
        fail("image must be an official SearXNG Docker Hub or GHCR tag")
    directory.mkdir(parents=True, mode=0o700)
    configure(directory)
    identity = instance_id(directory)
    record: JsonMap = {
        "contractVersion": "mere.run/searxng-instance.v1",
        "plugin": "mere-searxng-search",
        "instanceId": identity,
        "containerName": f"mere-searxng-{identity}",
        "port": port,
        "image": image,
        "dockerContext": context,
        "status": "planned",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    write_state(directory, record)
    return record


def docker(record: JsonMap, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("docker")
    if executable is None:
        fail("Docker CLI is not installed")
    command = [executable]
    context = record.get("dockerContext")
    if isinstance(context, str) and context:
        command.extend(("--context", context))
    command.extend(args)
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        fail("Docker command failed or timed out")


def docker_ok(record: JsonMap, args: list[str], timeout: int = 60) -> str:
    result = docker(record, args, timeout)
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        fail(f"Docker {args[0]} failed: {(detail[-1] if detail else 'unknown error')[:300]}")
    return result.stdout.strip()


def require_local_docker(record: JsonMap) -> None:
    context = record.get("dockerContext")
    if isinstance(context, str) and context:
        endpoint = docker_ok(record, ["context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}"], 15)
    else:
        endpoint = os.environ.get("DOCKER_HOST", "")
        if not endpoint:
            current = docker_ok(record, ["context", "show"], 15)
            endpoint = docker_ok(record, ["context", "inspect", current, "--format", "{{.Endpoints.docker.Host}}"], 15)
    if not endpoint.startswith(("unix://", "npipe://")):
        fail("Docker context must use a local Unix socket or named pipe")


def inspect_container(record: JsonMap) -> JsonMap | None:
    name = record.get("containerName")
    if not isinstance(name, str):
        fail("local instance has no container name")
    result = docker(record, ["container", "inspect", "--format", "{{json .}}", name])
    if result.returncode:
        if "No such" in result.stderr:
            return None
        fail("could not inspect the local SearXNG container")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        fail("Docker returned an invalid container inspection")
    if not isinstance(value, dict):
        fail("Docker returned an invalid container inspection")
    container = cast(JsonMap, value)
    config = container.get("Config")
    if not isinstance(config, dict):
        fail("Docker container has no configuration")
    labels = config.get("Labels")
    if not isinstance(labels, dict) or labels.get(OWNER_LABEL) != "mere-searxng-search" or labels.get(STATE_LABEL) != record.get("instanceId"):
        fail("container name is occupied by an unmanaged container")
    return container


def wait_ready(port: int, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    fail("local SearXNG did not become ready")


def verify_mounted_config(directory: pathlib.Path, record: JsonMap) -> None:
    expected = hashlib.sha256((directory / "config" / "settings.yml").read_bytes()).hexdigest()
    result = docker(record, ["container", "exec", str(record["containerName"]), "cat", "/etc/searxng/settings.yml"], 15)
    if result.returncode or hashlib.sha256(result.stdout.encode()).hexdigest() != expected:
        fail("container did not load managed settings; choose a state directory shared with Docker")


def start(directory: pathlib.Path) -> JsonMap:
    record = load_state(directory)
    if record.get("status") == "removed":
        fail("local instance was removed; create a new plan")
    require_local_docker(record)
    docker_ok(record, ["info", "--format", "{{.ServerVersion}}"], 15)
    container = inspect_container(record)
    name = record.get("containerName")
    port = record.get("port")
    if not isinstance(name, str) or not isinstance(port, int):
        fail("local instance has invalid container settings")
    if container is None:
        image_id = record.get("imageId")
        if not isinstance(image_id, str):
            fail("instance is not installed; run instance install")
        docker_ok(record, [
            "run", "--detach", "--name", name,
            "--label", f"{OWNER_LABEL}=mere-searxng-search",
            "--label", f"{STATE_LABEL}={record['instanceId']}",
            "--publish", f"127.0.0.1:{port}:8080",
            "--volume", f"{directory / 'config'}:/etc/searxng",
            "--volume", f"{directory / 'cache'}:/var/cache/searxng",
            "--restart", "no", image_id,
        ], 90)
    else:
        state = container.get("State")
        if not isinstance(state, dict) or state.get("Running") is not True:
            docker_ok(record, ["container", "start", name], 60)
    try:
        verify_mounted_config(directory, record)
        wait_ready(port)
    except InstanceError:
        docker(record, ["container", "stop", name], 20)
        docker(record, ["container", "rm", name], 20)
        record["status"] = "failed"
        write_state(directory, record)
        raise
    record["status"] = "running"
    write_state(directory, record)
    return record


def install(directory: pathlib.Path, port: int, context: str | None, image: str) -> JsonMap:
    record = load_state(directory) if state_path(directory).is_file() else plan(directory, port, context, image)
    if record.get("status") == "running":
        return start(directory)
    if record.get("status") not in ("planned", "failed", "stopped"):
        fail("local instance cannot be installed from this state")
    require_local_docker(record)
    docker_ok(record, ["info", "--format", "{{.ServerVersion}}"], 15)
    if record.get("imageId") is None:
        saved_image = record.get("image")
        if not isinstance(saved_image, str):
            fail("local instance has no image")
        docker_ok(record, ["pull", saved_image], 600)
        image_id = docker_ok(record, ["image", "inspect", "--format", "{{.Id}}", saved_image], 30)
        if not image_id.startswith("sha256:"):
            fail("Docker returned an invalid image ID")
        record["imageId"] = image_id
        record["status"] = "installed"
        write_state(directory, record)
    return start(directory)


def status(directory: pathlib.Path) -> JsonMap:
    record = load_state(directory)
    if record.get("status") == "removed":
        return record
    require_local_docker(record)
    docker_ok(record, ["info", "--format", "{{.ServerVersion}}"], 15)
    container = inspect_container(record)
    state = container.get("State") if container is not None else None
    running = isinstance(state, dict) and state.get("Running") is True
    return {**record, "containerExists": container is not None, "running": running}


def stop(directory: pathlib.Path) -> JsonMap:
    record = load_state(directory)
    if record.get("status") == "removed":
        return record
    require_local_docker(record)
    container = inspect_container(record)
    state = container.get("State") if container is not None else None
    if isinstance(state, dict) and state.get("Running") is True:
        docker_ok(record, ["container", "stop", str(record["containerName"])], 60)
    record["status"] = "stopped"
    write_state(directory, record)
    return record


def uninstall(directory: pathlib.Path, purge: bool = False) -> JsonMap:
    record = load_state(directory)
    if record.get("status") != "removed":
        require_local_docker(record)
        container = inspect_container(record)
        if container is not None:
            state = container.get("State")
            if isinstance(state, dict) and state.get("Running") is True:
                docker_ok(record, ["container", "stop", str(record["containerName"])], 60)
            docker_ok(record, ["container", "rm", str(record["containerName"])], 60)
        record["status"] = "removed"
        record["removedAt"] = now_iso()
        write_state(directory, record)
    if purge:
        try:
            shutil.rmtree(directory)
        except OSError:
            fail("container was removed, but local instance files could not be purged")
        record["dataPurged"] = True
    return record

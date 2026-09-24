"""Own a loopback mere.run vision API only for the duration of a plugin run."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.parse
from contextlib import suppress
from dataclasses import dataclass
from typing import Callable, TextIO, cast

AUTOSTART_MODEL = "vision-chat-muse-glimmer-30b"
AUTOSTART_ENGINE = "text-chat-muse-glimmer"
ModelReady = Callable[[str, str], bool]
JsonMap = dict[str, object]


class APIServerError(RuntimeError):
    pass


def mere_run_command() -> str:
    return os.environ.get("MERE_COMPUTER_USE_MERE_RUN", "mere.run")


def connection_refused(error: urllib.error.URLError) -> bool:
    return isinstance(error.reason, ConnectionRefusedError)


def server_address(base_url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.hostname is None:
        raise APIServerError("local API URL has no host")
    return parsed.hostname, parsed.port or 80


def server_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["MERERUN_AGENT_PARENT_PID"] = str(os.getpid())
    key = os.environ.get("MERE_COMPUTER_USE_API_KEY")
    if key:
        environment["MERERUN_API_KEY"] = key
    else:
        environment.pop("MERERUN_API_KEY", None)
    return environment


def serve_command(base_url: str, model_path: str) -> list[str]:
    host, port = server_address(base_url)
    return [mere_run_command(), "api", "serve", "--engine", AUTOSTART_ENGINE,
            "--model", model_path, "--host", host, "--port", str(port)]


def preflight(base_url: str, model: str) -> pathlib.Path:
    if model != AUTOSTART_MODEL:
        raise APIServerError(f"automatic API start supports {AUTOSTART_MODEL}; start {model} separately")
    command = [*serve_command(base_url, model), "--preflight", "--json"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=40,
                            env=server_environment(), check=False)
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise APIServerError(f"mere.run API preflight returned no JSON: {result.stderr.strip()[-500:]}") from exc
    if not isinstance(payload, dict):
        raise APIServerError("mere.run API preflight returned no JSON object")
    report = cast(JsonMap, payload)
    detail = report.get("result")
    model_detail = detail.get("model") if isinstance(detail, dict) else None
    if result.returncode or report.get("status") != "ok" or not isinstance(model_detail, dict) \
            or model_detail.get("id") != model or model_detail.get("installed") is not True:
        raise APIServerError(f"mere.run API preflight did not approve the installed {model} model")
    model_path = model_detail.get("path")
    if not isinstance(model_path, str) or not pathlib.Path(model_path).is_absolute() \
            or not pathlib.Path(model_path).is_dir():
        raise APIServerError(f"mere.run API preflight returned no installed path for {model}")
    require_acknowledged_terms(model)
    return pathlib.Path(model_path)


def require_acknowledged_terms(model: str) -> None:
    result = subprocess.run(
        [mere_run_command(), "model", "info", model, "--json"],
        text=True, capture_output=True, timeout=40, check=False,
    )
    try:
        manifest = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise APIServerError(f"mere.run model info returned no JSON: {result.stderr.strip()[-500:]}") from exc
    if result.returncode or not isinstance(manifest, dict) or manifest.get("id") != model:
        raise APIServerError(f"mere.run could not inspect the installed {model} model manifest")
    if manifest.get("usageTermsAcknowledged") is not True:
        raise APIServerError(
            f"{model} has unacknowledged upstream usage terms. "
            f"Review them with 'mere.run model info {model}', then record acceptance in mere.run before running."
        )


@dataclass
class OwnedServer:
    process: subprocess.Popen[str]
    log: TextIO
    log_path: pathlib.Path

    def stop(self) -> None:
        if self.process.poll() is None:
            with suppress(ProcessLookupError):
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log.close()


def ensure_model(base_url: str, model: str, ready: ModelReady,
                 run_dir: pathlib.Path, startup_timeout: int) -> OwnedServer | None:
    try:
        if ready(base_url, model):
            return None
        raise APIServerError("an API already serves this port without the requested image/tool model")
    except urllib.error.URLError as exc:
        if not connection_refused(exc):
            raise APIServerError(f"existing API is unreachable or rejected access: {exc}") from exc
    model_path = preflight(base_url, model)
    log_path = run_dir / "api-server.log"
    log = log_path.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(serve_command(base_url, str(model_path)), stdout=log, stderr=subprocess.STDOUT,
                                   text=True, env=server_environment(), start_new_session=True)
    except OSError:
        log.close()
        raise
    server = OwnedServer(process, log, log_path)
    deadline = time.monotonic() + startup_timeout
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise APIServerError(f"mere.run API exited during startup; see {log_path}")
            try:
                if ready(base_url, model):
                    return server
            except urllib.error.URLError as exc:
                if not connection_refused(exc):
                    raise APIServerError(f"mere.run API startup failed: {exc}") from exc
            time.sleep(0.5)
        raise APIServerError(f"mere.run API did not become ready within {startup_timeout} seconds; see {log_path}")
    except BaseException:
        server.stop()
        raise

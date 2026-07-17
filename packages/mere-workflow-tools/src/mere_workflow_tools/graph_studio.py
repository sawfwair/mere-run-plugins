from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, cast
from urllib.parse import parse_qs, quote, urlparse

from .graph_sdk import GraphProviderError, JsonMap, as_map

STATIC_ROOT = pathlib.Path(__file__).resolve().parent / "studio"
SIDECAR_KIND = "mere.run/workflow-editor"
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 64 * 1024
PROJECT_PATH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,255}$")


@dataclasses.dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str

    def document(self) -> JsonMap:
        parsed: object = None
        if self.stdout.strip():
            try:
                parsed = json.loads(self.stdout)
            except json.JSONDecodeError:
                parsed = None
        return {
            "exit_code": self.exit_code,
            "result": parsed,
            "stdout": self.stdout if parsed is None else "",
            "stderr": self.stderr[-MAX_DIAGNOSTIC_BYTES:],
        }


@dataclasses.dataclass
class StudioRun:
    id: str
    executor: str
    run_directory: pathlib.Path
    graph_path: pathlib.Path
    inputs_path: pathlib.Path
    state: str
    created_at: str
    updated_at: str
    process: subprocess.Popen[str] | None = None
    exit_code: int | None = None
    result: object = None
    stderr: str = ""
    remote_reference: str | None = None

    def public(self, include_events: bool = False) -> JsonMap:
        value: JsonMap = {
            "id": self.id,
            "executor": self.executor,
            "run_directory": str(self.run_directory),
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "exit_code": self.exit_code,
            "result": self.result,
            "stderr": self.stderr[-MAX_DIAGNOSTIC_BYTES:],
            "remote_reference": self.remote_reference,
        }
        if include_events:
            value["events"] = read_json_lines(self.run_directory / "events.jsonl", 250)
            value["manifest"] = read_optional_json(self.run_directory / "run.json")
        return value


CommandRunner = Callable[[list[str]], CommandResult]


class GraphStudioService:
    def __init__(
        self,
        workspace: pathlib.Path,
        mere_run_command: str,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.mere_run_command = mere_run_command
        self.command_runner = command_runner or self._run_command
        self.runs: dict[str, StudioRun] = {}
        self.run_lock = threading.Lock()
        self.state_root = self.workspace / ".mere-graph-studio"
        self.request_root = self.state_root / "requests"
        self.run_root = self.workspace / "runs"
        self.request_root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)

    def catalog(self) -> JsonMap:
        return self.command_runner([self.mere_run_command, "graph", "catalog", "--json"]).document()

    def executors(self) -> JsonMap:
        return self.command_runner([self.mere_run_command, "executor", "list", "--json"]).document()

    def check(self, body: JsonMap) -> JsonMap:
        mode = body.get("mode")
        if mode not in {"validate", "preflight"}:
            raise GraphProviderError("check mode must be validate or preflight")
        graph_path, inputs_path = self._write_request(body)
        command = [self.mere_run_command, "graph", cast(str, mode), str(graph_path), "--inputs-json", str(inputs_path)]
        if mode == "preflight":
            command += ["--executor", required_string(body, "executor", "local")]
        command.append("--json")
        return self.command_runner(command).document()

    def projects(self) -> JsonMap:
        projects: list[JsonMap] = []
        for path in sorted(self.workspace.rglob("*.workflow.json")):
            if self.state_root in path.parents or len(projects) >= 250:
                continue
            try:
                relative = path.relative_to(self.workspace)
            except ValueError:
                continue
            projects.append({
                "path": relative.as_posix().removesuffix(".workflow.json"),
                "name": path.name.removesuffix(".workflow.json"),
                "modified_at": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).isoformat(),
            })
        return {"projects": projects}

    def load_project(self, raw_path: str) -> JsonMap:
        base = self._project_base(raw_path)
        graph_path, inputs_path, sidecar_path = project_paths(base)
        if not graph_path.is_file():
            raise GraphProviderError(f"workflow project does not exist: {raw_path}")
        return {
            "path": raw_path,
            "graph": read_required_json(graph_path, "workflow graph"),
            "inputs": read_optional_json(inputs_path) or {},
            "sidecar": read_optional_json(sidecar_path) or default_sidecar(),
        }

    def save_project(self, body: JsonMap) -> JsonMap:
        raw_path = required_string(body, "path")
        base = self._project_base(raw_path)
        graph = as_map(body.get("graph"), "graph")
        inputs = as_map(body.get("inputs", {}), "inputs")
        sidecar = as_map(body.get("sidecar", default_sidecar()), "sidecar")
        if sidecar.get("schema_version") != 1 or sidecar.get("kind") != SIDECAR_KIND:
            raise GraphProviderError(f"editor sidecar must use schema_version 1 and kind {SIDECAR_KIND}")
        base.parent.mkdir(parents=True, exist_ok=True)
        graph_path, inputs_path, sidecar_path = project_paths(base)
        write_json_atomic(graph_path, graph)
        write_json_atomic(inputs_path, inputs)
        write_json_atomic(sidecar_path, sidecar)
        return {"status": "saved", "path": raw_path}

    def start_run(self, body: JsonMap) -> JsonMap:
        executor = required_string(body, "executor", "local")
        graph = as_map(body.get("graph"), "graph")
        inputs = as_map(body.get("inputs", {}), "inputs")
        run_id = uuid.uuid4().hex[:12]
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        request_directory = self.request_root / run_id
        request_directory.mkdir(parents=True)
        graph_path = request_directory / "workflow.json"
        inputs_path = request_directory / "inputs.json"
        write_json_atomic(graph_path, graph)
        write_json_atomic(inputs_path, inputs)
        graph_name = graph.get("name") if isinstance(graph.get("name"), str) else "workflow"
        slug = re.sub(r"[^a-z0-9]+", "-", cast(str, graph_name).lower()).strip("-")[:40] or "workflow"
        run_directory = self.run_root / f"{slug}-{run_id}"
        studio_run = StudioRun(
            id=run_id,
            executor=executor,
            run_directory=run_directory,
            graph_path=graph_path,
            inputs_path=inputs_path,
            state="starting",
            created_at=now,
            updated_at=now,
        )
        with self.run_lock:
            self.runs[run_id] = studio_run
        thread = threading.Thread(target=self._execute_run, args=(studio_run,), daemon=True)
        thread.start()
        return studio_run.public()

    def list_runs(self) -> JsonMap:
        with self.run_lock:
            rows = [item.public() for item in self.runs.values()]
        rows.sort(key=lambda item: cast(str, item["created_at"]), reverse=True)
        return {"runs": rows}

    def inspect_run(self, run_id: str) -> JsonMap:
        with self.run_lock:
            studio_run = self.runs.get(run_id)
        if not studio_run:
            raise GraphProviderError(f"unknown Studio run: {run_id}")
        return studio_run.public(include_events=True)

    def cancel_run(self, run_id: str) -> JsonMap:
        with self.run_lock:
            studio_run = self.runs.get(run_id)
        if not studio_run:
            raise GraphProviderError(f"unknown Studio run: {run_id}")
        if studio_run.process and studio_run.process.poll() is None:
            (studio_run.run_directory / "cancel.request").parent.mkdir(parents=True, exist_ok=True)
            (studio_run.run_directory / "cancel.request").write_text(dt.datetime.now(dt.timezone.utc).isoformat())
            studio_run.process.terminate()
        if studio_run.remote_reference:
            self.command_runner([self.mere_run_command, "run", "cancel", studio_run.remote_reference, "--json"])
        studio_run.state = "cancelled"
        studio_run.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
        return studio_run.public()

    def _execute_run(self, studio_run: StudioRun) -> None:
        command = [self.mere_run_command, "graph"]
        if studio_run.executor == "local":
            command += ["run", str(studio_run.graph_path)]
        else:
            command += ["submit", str(studio_run.graph_path), "--executor", studio_run.executor]
        command += [
            "--inputs-json",
            str(studio_run.inputs_path),
            "--run-dir",
            str(studio_run.run_directory),
            "--json",
        ]
        studio_run.state = "running" if studio_run.executor == "local" else "submitting"
        studio_run.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            process = subprocess.Popen(
                command,
                cwd=self.workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            studio_run.process = process
            stdout, stderr = process.communicate()
            studio_run.exit_code = process.returncode
            studio_run.stderr = stderr[-MAX_DIAGNOSTIC_BYTES:]
            try:
                studio_run.result = json.loads(stdout) if stdout.strip() else None
            except json.JSONDecodeError:
                studio_run.result = {"stdout": stdout[-MAX_DIAGNOSTIC_BYTES:]}
            studio_run.remote_reference = find_remote_reference(studio_run.result)
            if studio_run.state != "cancelled":
                if process.returncode == 0:
                    studio_run.state = "queued" if studio_run.remote_reference else "finished"
                else:
                    studio_run.state = "failed"
        except OSError as exc:
            studio_run.state = "failed"
            studio_run.stderr = str(exc)
        finally:
            studio_run.process = None
            studio_run.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()

    def _write_request(self, body: JsonMap) -> tuple[pathlib.Path, pathlib.Path]:
        request_id = uuid.uuid4().hex
        request_directory = self.request_root / request_id
        request_directory.mkdir(parents=True)
        graph_path = request_directory / "workflow.json"
        inputs_path = request_directory / "inputs.json"
        write_json_atomic(graph_path, as_map(body.get("graph"), "graph"))
        write_json_atomic(inputs_path, as_map(body.get("inputs", {}), "inputs"))
        return graph_path, inputs_path

    def _project_base(self, raw_path: str) -> pathlib.Path:
        if not PROJECT_PATH_PATTERN.fullmatch(raw_path) or ".." in pathlib.PurePosixPath(raw_path).parts:
            raise GraphProviderError(f"invalid project path: {raw_path}")
        path = (self.workspace / pathlib.Path(*pathlib.PurePosixPath(raw_path).parts)).resolve()
        if path != self.workspace and self.workspace not in path.parents:
            raise GraphProviderError(f"project path escapes the workspace: {raw_path}")
        return path

    def _run_command(self, command: list[str]) -> CommandResult:
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class StudioHTTPServer(ThreadingHTTPServer):
    service: GraphStudioService
    token: str


class StudioRequestHandler(BaseHTTPRequestHandler):
    server: StudioHTTPServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._api_get(parsed.path, parse_qs(parsed.query))
            return
        self._static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            self._require_token()
            body = self._read_body()
            if parsed.path == "/api/check":
                self._json(self.server.service.check(body))
            elif parsed.path == "/api/project":
                self._json(self.server.service.save_project(body))
            elif parsed.path == "/api/runs":
                self._json(self.server.service.start_run(body), HTTPStatus.ACCEPTED)
            elif parsed.path.startswith("/api/runs/") and parsed.path.endswith("/cancel"):
                run_id = parsed.path.split("/")[3]
                self._json(self.server.service.cancel_run(run_id))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except GraphProviderError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (OSError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _api_get(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            self._require_token()
            if path == "/api/catalog":
                self._json(self.server.service.catalog())
            elif path == "/api/executors":
                self._json(self.server.service.executors())
            elif path == "/api/projects":
                self._json(self.server.service.projects())
            elif path == "/api/project":
                raw_path = query.get("path", [""])[0]
                self._json(self.server.service.load_project(raw_path))
            elif path == "/api/runs":
                self._json(self.server.service.list_runs())
            elif path.startswith("/api/runs/"):
                self._json(self.server.service.inspect_run(path.split("/")[3]))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except GraphProviderError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.removeprefix("/")
        if relative not in {"index.html", "app.js", "styles.css"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        target = STATIC_ROOT / relative
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }[target.suffix]
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _require_token(self) -> None:
        if self.headers.get("X-Mere-Studio-Token") != self.server.token:
            raise GraphProviderError("Studio session token is invalid")

    def _read_body(self) -> JsonMap:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise GraphProviderError("invalid request content length") from None
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise GraphProviderError("request body is empty or too large")
        try:
            return as_map(json.loads(self.rfile.read(length)), "request")
        except json.JSONDecodeError as exc:
            raise GraphProviderError(f"invalid request JSON: {exc}") from None

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format_value: str, *args: object) -> None:
        sys.stderr.write(f"studio: {format_value % args}\n")


def required_string(body: JsonMap, key: str, default: str | None = None) -> str:
    value = body.get(key, default)
    if not isinstance(value, str) or not value:
        raise GraphProviderError(f"{key} must be a non-empty string")
    return value


def default_sidecar() -> JsonMap:
    return {
        "schema_version": 1,
        "kind": SIDECAR_KIND,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": {},
    }


def project_paths(base: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    return (
        base.parent / f"{base.name}.workflow.json",
        base.parent / f"{base.name}.inputs.json",
        base.parent / f"{base.name}.studio.json",
    )


def write_json_atomic(path: pathlib.Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def read_required_json(path: pathlib.Path, label: str) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), label)
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"invalid {label} JSON: {exc}") from None


def read_optional_json(path: pathlib.Path) -> object:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def read_json_lines(path: pathlib.Path, limit: int) -> list[object]:
    if not path.is_file():
        return []
    lines = path.read_text(errors="replace").splitlines()[-limit:]
    values: list[object] = []
    for line in lines:
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return values


def find_remote_reference(value: object) -> str | None:
    if isinstance(value, str) and (value.startswith("ssh://") or value.startswith("relay://")):
        return value
    if isinstance(value, list):
        for item in value:
            found = find_remote_reference(item)
            if found:
                return found
    if isinstance(value, dict):
        for item in cast(dict[object, object], value).values():
            found = find_remote_reference(item)
            if found:
                return found
    return None


def resolve_mere_run(command: str) -> str:
    if pathlib.Path(command).is_absolute():
        if not pathlib.Path(command).is_file():
            raise GraphProviderError(f"mere.run executable does not exist: {command}")
        return command
    resolved = shutil.which(command)
    if not resolved:
        raise GraphProviderError(f"mere.run executable is unavailable: {command}")
    return resolved


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Launch the optional local graph authoring studio.")
    value.add_argument("--workspace", type=pathlib.Path, default=pathlib.Path.cwd())
    value.add_argument("--mere-run-command", default=os.environ.get("MERE_WORKFLOW_TOOLS_MERE_RUN", "mere.run"))
    value.add_argument("--host", default="127.0.0.1")
    value.add_argument("--port", type=int, default=0)
    value.add_argument("--no-open", action="store_true")
    return value


def main() -> int:
    args = parser().parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        sys.stderr.write("Graph Studio binds only to a loopback address.\n")
        return 2
    try:
        command = resolve_mere_run(args.mere_run_command)
        workspace = args.workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        service = GraphStudioService(workspace, command)
        server = StudioHTTPServer((args.host, args.port), StudioRequestHandler)
        server.service = service
        server.token = secrets.token_urlsafe(24)
    except (GraphProviderError, OSError) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 2
    host, port = cast(tuple[str, int], server.server_address[:2])
    url = f"http://{host}:{port}/?token={quote(server.token)}"
    sys.stdout.write(json.dumps({"status": "ready", "url": url, "workspace": str(workspace)}) + "\n")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

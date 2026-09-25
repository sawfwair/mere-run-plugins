from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from typing import NoReturn, cast

from . import __version__

JsonMap = dict[str, object]
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
REQUEST_FIELDS = {"contractVersion", "backend", "mode", "prompt", "outputFormat", "model", "workspace", "access"}
MAX_REQUEST_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 8_000_000
DEFAULT_TIMEOUT_SECONDS = 600


class HandoffError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def fail(message: str, code: int = 2) -> NoReturn:
    raise HandoffError(message, code)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def print_json(value: object) -> None:
    sys.stdout.write(json_bytes(value).decode("utf-8"))


def write_private(path: pathlib.Path, value: object) -> None:
    payload = json_bytes(value)
    descriptor, temporary = tempfile.mkstemp(prefix=".handoff-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_map(path: pathlib.Path, label: str) -> JsonMap:
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot read {label}: {error}")
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return cast(JsonMap, value)


def request_from_bytes(data: bytes) -> JsonMap:
    if len(data) > MAX_REQUEST_BYTES:
        fail("request exceeds the 1 MB limit")
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as error:
        fail(f"invalid request JSON: {error}")
    if not isinstance(value, dict):
        fail("request must be a JSON object")
    request = cast(JsonMap, value)
    unknown = set(request) - REQUEST_FIELDS
    if unknown:
        fail(f"unknown request fields: {', '.join(sorted(unknown))}")
    if request.get("contractVersion") != "mere.run/frontier-handoff-request.v1":
        fail("unsupported request contractVersion")
    if request.get("backend") not in ("claude", "codex"):
        fail("backend must be claude or codex")
    mode = request.get("mode")
    if mode not in ("chat", "agent"):
        fail("mode must be chat or agent")
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        fail("prompt must be a nonempty string")
    if request.get("outputFormat") not in ("text", "json"):
        fail("outputFormat must be text or json")
    model = request.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        fail("model must be a nonempty string")
    workspace = request.get("workspace")
    access = request.get("access", "read-only")
    if mode == "chat":
        if workspace is not None or "access" in request:
            fail("chat requests cannot set workspace or access")
    else:
        if not isinstance(workspace, str) or not workspace.strip():
            fail("agent requests require a workspace")
        if access not in ("read-only", "workspace-write"):
            fail("access must be read-only or workspace-write")
        if not pathlib.Path(workspace).expanduser().resolve().is_dir():
            fail("workspace must be an existing directory")
    return request


def manifest_path(value: str) -> pathlib.Path:
    path = pathlib.Path(value).expanduser().resolve()
    if path.name != "run.json":
        fail("expected a run.json path")
    return path


def load_manifest(path: pathlib.Path) -> JsonMap:
    manifest = read_map(path, "run manifest")
    if manifest.get("contractVersion") != "mere.run/frontier-handoff-run.v1":
        fail("unsupported run manifest")
    if manifest.get("plugin") != "mere-frontier-handoff":
        fail("run manifest has a different plugin")
    if manifest.get("resultPath") != str(path.resolve().parent / "result.json"):
        fail("run manifest resultPath differs from its run directory")
    return manifest


def update_manifest(path: pathlib.Path, manifest: JsonMap, **changes: object) -> None:
    manifest.update(changes)
    manifest["updatedAt"] = now_iso()
    write_private(path, manifest)


def executable(backend: str) -> str:
    found = shutil.which(backend)
    if found is None:
        raise HandoffError(f"{backend} CLI is not installed", 3)
    return found


def cli_probe(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HandoffError(f"CLI readiness check failed: {type(error).__name__}", 3) from error


def backend_readiness(backend: str) -> JsonMap:
    found = shutil.which(backend)
    if found is None:
        return {"backend": backend, "installed": False, "authenticated": False}
    version_result = cli_probe([found, "--version"])
    status_command = [found, "auth", "status"] if backend == "claude" else [found, "login", "status"]
    auth_result = cli_probe(status_command)
    version = version_result.stdout.strip().splitlines()
    return {
        "backend": backend,
        "installed": True,
        "authenticated": auth_result.returncode == 0,
        "version": version[0][:160] if version and version_result.returncode == 0 else "unknown",
    }


def plugin_manifest() -> JsonMap:
    commands = [
        ("manifest", "Describe the plugin"),
        ("doctor", "Check local CLI installation and sign-in"),
        ("plan", "Validate and record a request without invoking a model"),
        ("run", "Execute a planned handoff"),
        ("resume", "Inspect an interrupted or completed handoff"),
        ("cleanup", "Record that no remote resource needs cleanup"),
    ]
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": "mere-frontier-handoff",
        "version": __version__,
        "executable": "mere-frontier-handoff",
        "description": "Hand off bounded chat or agent tasks to a user-authenticated Claude Code or Codex CLI.",
        "commands": [{"name": name, "description": description, "stdout": "json"} for name, description in commands],
        "capabilities": ["frontier-handoff", "structured-proposal", "local-agent", "durable-receipt"],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": True,
            "storesSecrets": False,
            "createsPaidResources": True,
            "cleanupDefault": "none",
        },
    }


def plan(request_file: pathlib.Path, output: pathlib.Path, run_id: str | None) -> JsonMap:
    source = request_file.expanduser().resolve(strict=True)
    data = source.read_bytes()
    request = request_from_bytes(data)
    identifier = run_id or uuid.uuid4().hex
    if not RUN_ID.fullmatch(identifier):
        fail("run ID contains unsupported characters")
    destination = output.expanduser().resolve()
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(destination, 0o700)
    mode = cast(str, request["mode"])
    workspace = request.get("workspace")
    manifest: JsonMap = {
        "contractVersion": "mere.run/frontier-handoff-run.v1",
        "runId": identifier,
        "plugin": "mere-frontier-handoff",
        "status": "planned",
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "request": {"path": str(source), "sha256": sha256(data)},
        "backend": request["backend"],
        "mode": mode,
        "outputFormat": request["outputFormat"],
        "access": request.get("access", "read-only") if mode == "agent" else "none",
        "resultPath": str(destination / "result.json"),
        "cleanup": "not-needed",
    }
    if isinstance(workspace, str):
        manifest["workspace"] = str(pathlib.Path(workspace).expanduser().resolve())
    if "model" in request:
        manifest["model"] = request["model"]
    write_private(destination / "run.json", manifest)
    return manifest


def read_planned_request(manifest: JsonMap) -> JsonMap:
    reference = manifest.get("request")
    if not isinstance(reference, dict):
        fail("run manifest has no request reference")
    source = reference.get("path")
    expected = reference.get("sha256")
    if not isinstance(source, str) or not isinstance(expected, str):
        fail("run manifest has an invalid request reference")
    try:
        data = pathlib.Path(source).read_bytes()
    except OSError as error:
        fail(f"cannot read request file: {error}")
    if sha256(data) != expected:
        fail("request changed after planning")
    request = request_from_bytes(data)
    for key in ("backend", "mode", "outputFormat", "model"):
        if request.get(key) != manifest.get(key):
            fail(f"run manifest {key} differs from the planned request")
    access = request.get("access", "read-only") if request["mode"] == "agent" else "none"
    if access != manifest.get("access"):
        fail("run manifest access differs from the planned request")
    if request["mode"] == "agent":
        workspace = cast(str, request["workspace"])
        if str(pathlib.Path(workspace).expanduser().resolve()) != manifest.get("workspace"):
            fail("run manifest workspace differs from the planned request")
    return request


def command_for_request(request: JsonMap, binary: str, cwd: pathlib.Path, last_message: pathlib.Path) -> list[str]:
    backend = request["backend"]
    mode = request["mode"]
    fmt = request["outputFormat"]
    model = request.get("model")
    if backend == "claude":
        tools = "" if mode == "chat" else "Read,Glob,Grep"
        if mode == "agent" and request.get("access", "read-only") == "workspace-write":
            tools += ",Edit,Write"
        command = [
            binary, "--print", "--output-format", "json", "--no-session-persistence",
            "--permission-mode", "dontAsk", "--tools", tools,
        ]
        if mode == "agent":
            command.extend(["--allowedTools", tools])
        if fmt == "json":
            command.extend(["--json-schema", '{"type":"object"}'])
        if isinstance(model, str):
            command.extend(["--model", model])
        return command
    command = [
        binary, "exec", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
        "--sandbox", "workspace-write" if request.get("access") == "workspace-write" else "read-only",
        "--cd", str(cwd), "--output-last-message", str(last_message),
    ]
    if fmt == "json":
        schema_path = last_message.parent / "output-schema.json"
        write_private(schema_path, {
            "type": "object",
            "properties": {"output": {"type": "string"}},
            "required": ["output"],
            "additionalProperties": False,
        })
        command.extend(["--output-schema", str(schema_path)])
    if isinstance(model, str):
        command.extend(["--model", model])
    command.append("-")
    return command


def invoke(command: list[str], prompt: str, cwd: pathlib.Path, timeout: int, *, capture_stdout: bool) -> str:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as error:
        raise HandoffError(f"could not start frontier CLI: {type(error).__name__}", 4) from error
    try:
        stdout, stderr = process.communicate(input=prompt.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired as error:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise HandoffError(f"frontier CLI exceeded {timeout} seconds", 4) from error
    except KeyboardInterrupt:
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate()
        raise
    if process.returncode != 0:
        if capture_stdout:
            try:
                envelope = json.loads(stdout or b"")
                status = envelope.get("api_error_status") if isinstance(envelope, dict) else None
                if isinstance(status, int) and 400 <= status <= 599:
                    raise HandoffError(f"Claude API returned HTTP {status}", 4)
            except (UnicodeError, json.JSONDecodeError):
                pass
        else:
            diagnostic = (stderr or b"").decode("utf-8", errors="replace")[-8192:]
            code = re.search(r'"code"\s*:\s*"([a-z_]+)"', diagnostic)
            status = re.search(r'"status"\s*:\s*(\d{3})', diagnostic)
            if code and status:
                raise HandoffError(f"Codex API returned HTTP {status.group(1)} ({code.group(1)})", 4)
        raise HandoffError(f"frontier CLI exited {process.returncode}", 4)
    if len(stdout or b"") > MAX_RESPONSE_BYTES:
        raise HandoffError("frontier CLI response exceeded the 8 MB limit", 4)
    try:
        return (stdout or b"").decode("utf-8")
    except UnicodeError as error:
        raise HandoffError("frontier CLI response was not UTF-8", 4) from error


def parse_output(backend: str, raw: str, last_message: pathlib.Path, output_format: str) -> object:
    if backend == "claude":
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as error:
            raise HandoffError("Claude returned invalid JSON output", 4) from error
        if not isinstance(envelope, dict) or envelope.get("is_error") is True:
            raise HandoffError("Claude reported an unsuccessful run", 4)
        value = envelope.get("structured_output", envelope.get("result"))
    else:
        try:
            value = last_message.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise HandoffError("Codex did not write a final response", 4) from error
        if output_format == "json":
            try:
                wrapper = json.loads(value)
            except json.JSONDecodeError as error:
                raise HandoffError("Codex returned invalid JSON wrapper", 4) from error
            if not isinstance(wrapper, dict) or not isinstance(wrapper.get("output"), str):
                raise HandoffError("Codex returned no JSON output field", 4)
            value = wrapper["output"]
    if output_format == "text":
        if not isinstance(value, str) or not value.strip():
            raise HandoffError("frontier CLI returned no text", 4)
        return value
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as error:
        raise HandoffError("frontier CLI returned invalid result JSON", 4) from error
    if not isinstance(parsed, dict):
        raise HandoffError("JSON result must be an object", 4)
    return parsed


def run(path: pathlib.Path, timeout: int) -> JsonMap:
    manifest = load_manifest(path)
    if manifest.get("status") != "planned":
        fail("only a planned handoff can run")
    request = read_planned_request(manifest)
    backend = cast(str, request["backend"])
    ready = backend_readiness(backend)
    if ready["authenticated"] is not True:
        raise HandoffError(f"{backend} CLI is missing or not signed in", 3)
    binary = executable(backend)
    lock = path.parent / ".run.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise HandoffError("handoff is already running or needs interruption review", 4) from error
    with os.fdopen(descriptor, "w") as file:
        file.write(str(os.getpid()))
    started = now_iso()
    update_manifest(path, manifest, status="running", startedAt=started)
    try:
        mode = cast(str, request["mode"])
        with tempfile.TemporaryDirectory(prefix="mere-frontier-handoff-") as temporary:
            cwd = pathlib.Path(cast(str, manifest["workspace"])) if mode == "agent" else pathlib.Path(temporary)
            last_message = pathlib.Path(temporary) / "last-message.txt"
            command = command_for_request(request, binary, cwd, last_message)
            prompt = cast(str, request["prompt"])
            if backend == "codex" and request["outputFormat"] == "json":
                prompt += ("\n\nReturn the requested JSON object serialized as a compact JSON string "
                           "in the output field. The output field is only a response container.")
            raw = invoke(command, prompt, cwd, timeout, capture_stdout=backend == "claude")
            output = parse_output(backend, raw, last_message, cast(str, request["outputFormat"]))
        encoded_output = json.dumps(output, sort_keys=True, ensure_ascii=False).encode("utf-8")
        if len(encoded_output) > MAX_RESPONSE_BYTES:
            raise HandoffError("frontier CLI result exceeded the 8 MB limit", 4)
        digest = sha256(encoded_output)
        completed = now_iso()
        receipt: JsonMap = {
            "requestSha256": cast(dict[str, str], manifest["request"])["sha256"],
            "outputSha256": digest,
            "cliVersion": ready["version"],
            "startedAt": started,
            "completedAt": completed,
        }
        if "model" in request:
            receipt["requestedModel"] = request["model"]
        result: JsonMap = {
            "contractVersion": "mere.run/frontier-handoff-result.v1",
            "runId": manifest["runId"],
            "backend": backend,
            "mode": mode,
            "outputFormat": request["outputFormat"],
            "output": output,
            "receipt": receipt,
        }
        write_private(path.parent / "result.json", result)
        update_manifest(path, manifest, status="succeeded", completedAt=completed, outputSha256=digest)
    except (HandoffError, KeyboardInterrupt) as error:
        message = str(error) if isinstance(error, HandoffError) else "interrupted by operator"
        update_manifest(path, manifest, status="failed" if isinstance(error, HandoffError) else "interrupted", error=message)
        raise
    finally:
        lock.unlink(missing_ok=True)
    return manifest


def lock_is_active(path: pathlib.Path) -> bool:
    try:
        pid = int(path.read_text().strip())
        if pid < 1:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ValueError) as error:
        return isinstance(error, PermissionError)


def resume(path: pathlib.Path) -> JsonMap:
    manifest = load_manifest(path)
    lock = path.parent / ".run.lock"
    if lock.exists() and not lock_is_active(lock):
        lock.unlink()
    if manifest.get("status") == "running" and not lock.exists():
        update_manifest(path, manifest, status="interrupted", error="process stopped before recording a result")
    elif manifest.get("status") == "planned" and lock.exists():
        return manifest
    if manifest.get("status") == "succeeded":
        result = read_map(path.parent / "result.json", "result")
        output = result.get("output")
        digest = sha256(json.dumps(output, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if digest != manifest.get("outputSha256"):
            raise HandoffError("result digest differs from the run manifest", 4)
    return manifest


def cleanup(path: pathlib.Path) -> JsonMap:
    manifest = resume(path)
    if manifest.get("status") == "running" or (path.parent / ".run.lock").exists():
        raise HandoffError("cannot clean up while a handoff may be running", 4)
    update_manifest(path, manifest, cleanup="recorded")
    return manifest


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="mere-frontier-handoff")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("manifest").add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--backend", choices=("claude", "codex"))
    planned = commands.add_parser("plan")
    planned.add_argument("--request", required=True, type=pathlib.Path)
    planned.add_argument("--output", required=True, type=pathlib.Path)
    planned.add_argument("--run-id")
    execution = commands.add_parser("run")
    execution.add_argument("manifest", type=str)
    execution.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    commands.add_parser("resume").add_argument("manifest", type=str)
    commands.add_parser("cleanup").add_argument("manifest", type=str)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "manifest":
            print_json(plugin_manifest())
        elif args.command == "doctor":
            backends = [args.backend] if args.backend is not None else ["claude", "codex"]
            reports = [backend_readiness(backend) for backend in backends]
            print_json({"plugin": "mere-frontier-handoff", "backends": reports})
            if not any(report["authenticated"] is True for report in reports):
                return 3
        elif args.command == "plan":
            print_json(plan(args.request, args.output, args.run_id))
        elif args.command == "run":
            if args.timeout_seconds < 1 or args.timeout_seconds > 86_400:
                fail("timeout must be between 1 and 86400 seconds")
            print_json(run(manifest_path(args.manifest), args.timeout_seconds))
        elif args.command == "resume":
            print_json(resume(manifest_path(args.manifest)))
        elif args.command == "cleanup":
            print_json(cleanup(manifest_path(args.manifest)))
    except HandoffError as error:
        sys.stderr.write(f"mere-frontier-handoff: {error}\n")
        return error.exit_code
    except KeyboardInterrupt:
        sys.stderr.write("mere-frontier-handoff: interrupted by operator\n")
        return 130
    except (OSError, ValueError) as error:
        sys.stderr.write(f"mere-frontier-handoff: {error}\n")
        return 2
    return 0

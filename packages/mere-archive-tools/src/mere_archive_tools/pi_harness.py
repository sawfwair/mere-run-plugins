"""Run a bounded, read-only archive investigation through Pi and mere.run."""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast

from .runtime import InferenceError, MereRunClient, command_available, split_command

JsonMap = dict[str, object]
INVESTIGATION_CONTRACT = "mere.run/archive-investigation.v1"
DEFAULT_MODEL = "text-chat-bonsai-27b-1bit"
DEFAULT_ENGINE = "text-chat-q36"
JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


class InvestigationError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class InvestigationConfig:
    database: pathlib.Path
    question: str
    model: str
    engine: str
    max_searches: int
    top: int
    context_size: int
    server_timeout_seconds: int
    pi_timeout_seconds: int
    mere_run_command: str
    pi_command: str
    replacement: str


@dataclass(frozen=True)
class LocalServer:
    process: subprocess.Popen[str]
    base_url: str


def resource_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent / "resources" / "pi"


def _as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    raise InvestigationError(f"{label} isn't an object")


def _as_list(value: object, label: str) -> list[object]:
    if isinstance(value, list):
        return value
    raise InvestigationError(f"{label} isn't an array")


def _as_string(value: object, label: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise InvestigationError(f"{label} must be a nonempty string")


def parse_json_output(text: str) -> JsonMap:
    stripped = text.strip()
    match = JSON_FENCE.fullmatch(stripped)
    if match:
        stripped = match.group(1).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise InvestigationError(f"Pi returned non-JSON output: {exc}") from None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as nested:
            raise InvestigationError(f"Pi returned invalid JSON: {nested}") from None
    return _as_map(value, "Pi investigation output")


def validate_model_result(payload: JsonMap, source_paths: set[str]) -> None:
    if payload.get("contractVersion") != INVESTIGATION_CONTRACT:
        raise InvestigationError("Pi returned the wrong investigation contractVersion")
    _as_string(payload.get("answer"), "answer")
    claims = _as_list(payload.get("claims"), "claims")
    if not claims:
        raise InvestigationError("claims must not be empty")
    claim_ids: set[str] = set()
    for index, raw_claim in enumerate(claims, start=1):
        claim = _as_map(raw_claim, f"claims[{index}]")
        claim_id = _as_string(claim.get("id"), f"claims[{index}].id")
        if claim_id in claim_ids:
            raise InvestigationError(f"duplicate claim id: {claim_id}")
        claim_ids.add(claim_id)
        _as_string(claim.get("statement"), f"claims[{index}].statement")
        status = _as_string(claim.get("status"), f"claims[{index}].status")
        if status not in {"supported", "unresolved"}:
            raise InvestigationError(f"claims[{index}].status must be supported or unresolved")
        sources = _as_list(claim.get("sources"), f"claims[{index}].sources")
        if not all(isinstance(source, str) and source.strip() for source in sources):
            raise InvestigationError(f"claims[{index}].sources must contain nonempty strings")
        normalized_sources = [str(source) for source in sources]
        if status == "supported" and not normalized_sources:
            raise InvestigationError(f"supported claim {claim_id} must cite at least one source")
        unknown = sorted(set(normalized_sources) - source_paths)
        if unknown:
            raise InvestigationError(
                f"claim {claim_id} cites paths that weren't returned by archive_search: {', '.join(unknown)}"
            )


def load_search_trace(path: pathlib.Path) -> list[JsonMap]:
    if not path.is_file():
        return []
    records: list[JsonMap] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(_as_map(json.loads(line), f"search trace line {line_number}"))
        except json.JSONDecodeError as exc:
            raise InvestigationError(f"search trace line {line_number} isn't valid JSON: {exc}") from None
    return records


def trace_source_paths(trace: list[JsonMap]) -> set[str]:
    paths: set[str] = set()
    for index, record in enumerate(trace, start=1):
        values = _as_list(record.get("resultPaths"), f"searches[{index}].resultPaths")
        for value in values:
            if isinstance(value, str) and value:
                paths.add(value)
    return paths


def resolve_pi_command(pi_command: str, mere_run_command: str) -> list[str]:
    if pi_command.strip():
        resolved = split_command(pi_command)
        if not command_available(resolved):
            raise InvestigationError(f"Pi executable not found: {resolved[0]}", 3)
        return resolved
    path_pi = shutil.which("pi")
    if path_pi:
        return [path_pi]
    mere_run = split_command(mere_run_command)
    completed = subprocess.run(
        [*mere_run, "agent", "status", "--json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode == 0:
        try:
            status = _as_map(json.loads(completed.stdout), "mere.run agent status")
            pi = _as_map(status.get("pi"), "mere.run agent status pi")
            path = pi.get("path")
            if isinstance(path, str) and os.access(path, os.X_OK):
                return [path]
        except (json.JSONDecodeError, InvestigationError):
            pass
    raise InvestigationError(
        "Pi isn't installed. Run `mere.run agent onboard --install-pi` or pass --pi-command.",
        3,
    )


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _read_server_models(base_url: str) -> list[JsonMap]:
    request = urllib.request.Request(f"{base_url}/models", headers={"Authorization": "Bearer mere-run"})
    with urllib.request.urlopen(request, timeout=2) as response:
        payload = _as_map(json.loads(response.read()), "model discovery response")
    return [_as_map(value, "model discovery item") for value in _as_list(payload.get("data"), "model data")]


def _process_detail(process: subprocess.Popen[str], stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> str:
    status = f"exit {process.returncode}" if process.returncode is not None else "server didn't become ready"
    details: list[str] = [status]
    for label, path in (("stdout", stdout_path), ("stderr", stderr_path)):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                details.append(f"{label}: {text[-2_000:]}")
    return "\n".join(details)


def preflight_server(config: InvestigationConfig) -> None:
    command = [
        *split_command(config.mere_run_command),
        "api",
        "serve",
        "--engine",
        config.engine,
        "--model",
        config.model,
        "--context-size",
        str(config.context_size),
        "--memory-guard",
        "balanced",
        "--preflight",
        "--json",
    ]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise InvestigationError(f"mere.run API preflight failed: {detail}", 3)
    try:
        report = _as_map(json.loads(completed.stdout), "mere.run API preflight")
    except json.JSONDecodeError as exc:
        raise InvestigationError(f"mere.run API preflight returned invalid JSON: {exc}", 3) from None
    if report.get("ok") is False or report.get("status") in {"blocked", "error"}:
        raise InvestigationError("mere.run API preflight blocked the investigation", 3)


@contextmanager
def local_server(config: InvestigationConfig, run_directory: pathlib.Path) -> Iterator[LocalServer]:
    preflight_server(config)
    port = available_port()
    base_url = f"http://127.0.0.1:{port}/v1"
    command = [
        *split_command(config.mere_run_command),
        "api",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--engine",
        config.engine,
        "--model",
        config.model,
        "--context-size",
        str(config.context_size),
        "--memory-guard",
        "balanced",
    ]
    stdout_path = run_directory / "server.stdout.log"
    stderr_path = run_directory / "server.stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        try:
            process = subprocess.Popen(command, text=True, stdout=stdout, stderr=stderr)
        except FileNotFoundError:
            raise InvestigationError(f"mere.run executable not found: {command[0]}", 3) from None
        deadline = time.monotonic() + config.server_timeout_seconds
        last_error = ""
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise InvestigationError(
                    "mere.run API server stopped before it became ready:\n"
                    + _process_detail(process, stdout_path, stderr_path),
                    3,
                )
            try:
                models = _read_server_models(base_url)
                if any(model.get("id") == config.model for model in models):
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError, InvestigationError) as exc:
                last_error = str(exc)
            time.sleep(0.25)
        else:
            detail = _process_detail(process, stdout_path, stderr_path)
            if last_error:
                detail += f"\nlast probe: {last_error}"
            process.terminate()
            process.wait(timeout=10)
            raise InvestigationError(f"mere.run API server wasn't ready in time:\n{detail}", 3)
        try:
            yield LocalServer(process=process, base_url=base_url)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def investigation_prompt(question: str, prior_error: str = "") -> str:
    prompt_path = resource_root() / "prompts" / "investigate.md"
    if not prompt_path.is_file():
        raise InvestigationError("the bundled archive investigation prompt is missing", 2)
    prompt = prompt_path.read_text(encoding="utf-8").replace("{{QUESTION}}", question)
    if prior_error:
        prompt += f"\nYour prior response was rejected: {prior_error}\nCorrect the response and return only the contract."
    return prompt


def build_pi_command(
    pi_command: list[str],
    model: str,
    prompt: str,
) -> list[str]:
    resources = resource_root()
    return [
        *pi_command,
        "--provider",
        "mere-run-archive",
        "--model",
        model,
        "--print",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-context-files",
        "--no-approve",
        "--no-builtin-tools",
        "--tools",
        "archive_search",
        "--extension",
        str(resources / "extensions" / "mere-run-provider.ts"),
        "--extension",
        str(resources / "extensions" / "archive-investigator.ts"),
        "--system-prompt",
        "You are a read-only archive investigator. Use only returned evidence. Never infer missing facts.",
        prompt,
    ]


def investigate(config: InvestigationConfig) -> JsonMap:
    if not config.database.is_file():
        raise InvestigationError(f"archive database doesn't exist: {config.database}", 2)
    pi_command = resolve_pi_command(config.pi_command, config.mere_run_command)
    reduced_question = MereRunClient(config.mere_run_command, config.replacement).anonymize(config.question).strip()
    if not reduced_question:
        raise InvestigationError("PII reduction returned an empty question", 2)
    with tempfile.TemporaryDirectory(prefix="mere-archive-investigate-") as temporary:
        run_directory = pathlib.Path(temporary)
        with local_server(config, run_directory) as server:
            prior_error = ""
            last_diagnostic = ""
            for attempt in range(1, 3):
                trace_path = run_directory / f"searches-{attempt}.jsonl"
                environment = os.environ.copy()
                environment.update(
                    {
                        "MERERUN_BASE_URL": server.base_url,
                        "MERERUN_API_KEY": "mere-run",
                        "MERE_ARCHIVE_DATABASE": str(config.database),
                        "MERE_ARCHIVE_MAX_SEARCHES": str(config.max_searches),
                        "MERE_ARCHIVE_SEARCH_TOP": str(config.top),
                        "MERE_ARCHIVE_SEARCH_TRACE": str(trace_path),
                        "MERE_ARCHIVE_REPLACEMENT": config.replacement,
                        "MERE_ARCHIVE_TOOLS_COMMAND_JSON": json.dumps(
                            [sys.executable, "-m", "mere_archive_tools"]
                        ),
                        "MERE_ARCHIVE_TOOLS_MERE_RUN": config.mere_run_command,
                    }
                )
                command = build_pi_command(
                    pi_command,
                    config.model,
                    investigation_prompt(reduced_question, prior_error),
                )
                try:
                    completed = subprocess.run(
                        command,
                        cwd=run_directory,
                        env=environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=config.pi_timeout_seconds,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    prior_error = f"Pi timed out after {config.pi_timeout_seconds} seconds"
                    continue
                trace = load_search_trace(trace_path)
                last_diagnostic = completed.stderr.strip()
                if completed.returncode != 0:
                    prior_error = last_diagnostic or completed.stdout.strip() or f"Pi exited {completed.returncode}"
                    continue
                try:
                    payload = parse_json_output(completed.stdout)
                    if not trace:
                        raise InvestigationError("Pi didn't call archive_search")
                    sources = trace_source_paths(trace)
                    validate_model_result(payload, sources)
                    claims = cast(list[JsonMap], payload["claims"])
                    unresolved = [
                        _as_string(claim.get("statement"), "unresolved claim statement")
                        for claim in claims
                        if claim.get("status") == "unresolved"
                    ]
                    return {
                        "contractVersion": INVESTIGATION_CONTRACT,
                        "question": reduced_question,
                        "piiReductionApplied": True,
                        "model": config.model,
                        "answer": payload["answer"],
                        "claims": claims,
                        "searches": trace,
                        "unresolvedClaims": unresolved,
                        "limits": {"maxSearches": config.max_searches, "resultsPerSearch": config.top},
                        "attempts": attempt,
                    }
                except InvestigationError as exc:
                    prior_error = str(exc)
            detail = prior_error
            if last_diagnostic and last_diagnostic not in detail:
                detail += f"\nPi diagnostic: {last_diagnostic[-2_000:]}"
            raise InvestigationError(f"Pi investigation failed after two attempts: {detail}")


def validate_config(config: InvestigationConfig) -> None:
    if not 1 <= config.max_searches <= 8:
        raise InvestigationError("--max-searches must be between 1 and 8", 2)
    if not 1 <= config.top <= 10:
        raise InvestigationError("--top must be between 1 and 10", 2)
    if not 2_048 <= config.context_size <= 32_768:
        raise InvestigationError("--context-size must be between 2048 and 32768", 2)
    if config.server_timeout_seconds <= 0:
        raise InvestigationError("--server-timeout must be greater than zero", 2)
    if config.pi_timeout_seconds <= 0:
        raise InvestigationError("--pi-timeout must be greater than zero", 2)
    if not config.question.strip():
        raise InvestigationError("--question must not be empty", 2)
    try:
        if not command_available(split_command(config.mere_run_command)):
            raise InvestigationError(
                f"mere.run executable not found: {split_command(config.mere_run_command)[0]}", 3
            )
    except InferenceError as exc:
        raise InvestigationError(str(exc), 2) from None

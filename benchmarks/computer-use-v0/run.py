"""Run three window-scoped computer-use cases against a local mere.run model."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import cast

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
CASES = ("read-code", "button", "form")
ENGINES = {
    "text-agent-ornith-35b-mlx-4bit": "text-chat-q36",
    "vision-chat-lfm25-3b-bf16": "text-chat-lfm2",
    "vision-chat-muse-glimmer-30b": "text-chat-muse-glimmer",
}
JsonMap = dict[str, object]


def object_map(value: object) -> JsonMap:
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return cast(JsonMap, value)


def read_json(path: pathlib.Path) -> JsonMap:
    return object_map(json.loads(path.read_text(encoding="utf-8")))


def write_json(path: pathlib.Path, value: JsonMap) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def score_case(case_id: str, nonce: str, state: JsonMap, run: JsonMap) -> list[str]:
    """Return independent failure reasons; an empty list is a pass."""
    failures: list[str] = []
    if state.get("caseID") != case_id or state.get("nonce") != nonce:
        failures.append("fixture identity mismatch")
    if run.get("status") != "finished":
        failures.append("plugin run did not finish")
    observations = run.get("observationCount")
    if run.get("needsObservation") is not False or not isinstance(observations, int) or observations < 1:
        failures.append("no final observation")
    actions = run.get("actionCount")
    if not isinstance(actions, int):
        failures.append("action count missing")
        actions = -1
    if case_id == "read-code":
        if str(run.get("result", "")).strip() != nonce:
            failures.append("reported code does not exactly match the visible code")
        if actions != 0:
            failures.append("read-only case changed the desktop")
    elif case_id == "button":
        if actions < 1:
            failures.append("no recorded desktop action")
        if state.get("recordCount") != 1 or state.get("resetCount") != 0 or state.get("cancelCount") != 0:
            failures.append("button state does not show exactly one Record click and no distractor clicks")
    elif case_id == "form":
        if actions < 2:
            failures.append("fewer than two recorded desktop actions")
        if state.get("submitCount") != 1 or state.get("submittedText") != nonce \
                or state.get("discardCount") != 0:
            failures.append("form state does not show the exact phrase submitted once without Discard")
    else:
        raise ValueError(f"unknown case: {case_id}")
    return failures


def outcome_reached(case_id: str, nonce: str, state: JsonMap, run: JsonMap) -> bool:
    """Judge the task outcome independently of agent shutdown and final prose."""
    if state.get("caseID") != case_id or state.get("nonce") != nonce:
        return False
    actions = run.get("actionCount")
    if not isinstance(actions, int):
        return False
    if case_id == "read-code":
        observations = run.get("observationCount")
        return actions == 0 and isinstance(observations, int) and observations >= 1 \
            and str(run.get("result", "")).strip() == nonce
    if case_id == "button":
        return actions >= 1 and state.get("recordCount") == 1 \
            and state.get("resetCount") == 0 and state.get("cancelCount") == 0
    if case_id == "form":
        return actions >= 2 and state.get("submitCount") == 1 \
            and state.get("submittedText") == nonce and state.get("discardCount") == 0
    raise ValueError(f"unknown case: {case_id}")


def task_for(case_id: str) -> str:
    tasks = {
        "read-code": "Read the six-digit reference code visible in this window. Do not change anything. "
                     "Reply with only those six digits.",
        "button": "Click the Record button exactly once, then observe the window to check the result.",
        "form": "Read the phrase shown in this window, enter it into the text field, click Submit once, "
                "then observe the window to check the result.",
    }
    return tasks[case_id]


def code_for(seed: str, case_id: str, iteration: int) -> str:
    digest = hashlib.sha256(f"{seed}:{case_id}:{iteration}".encode()).digest()
    return str(100000 + int.from_bytes(digest[:4], "big") % 900000)


def command(args: list[str], *, env: dict[str, str] | None = None, timeout: int = 40) -> JsonMap:
    result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args[:4])} exited {result.returncode}: {result.stderr.strip()[-1000:]}")
    return object_map(json.loads(result.stdout))


def preflight(mere_run: str, engine: str, model: str, port: int) -> None:
    info = command([mere_run, "model", "info", model, "--json"], timeout=60)
    if info.get("id") != model:
        raise RuntimeError("mere.run model info returned a different model")
    terms = info.get("usageTerms")
    if isinstance(terms, list) and terms and info.get("usageTermsAcknowledged") is not True:
        raise RuntimeError(f"{model} usage terms have not been acknowledged")
    result = command([mere_run, "api", "serve", "--engine", engine, "--model", model,
                      "--host", "127.0.0.1", "--port", str(port), "--preflight", "--json"], timeout=60)
    detail = result.get("result")
    model_detail = detail.get("model") if isinstance(detail, dict) else None
    if result.get("status") != "ok" or not isinstance(model_detail, dict) \
            or model_detail.get("id") != model or model_detail.get("installed") is not True:
        raise RuntimeError(f"mere.run preflight did not approve installed model {model}")


def plugin_command(python: str, args: list[str], env: dict[str, str], timeout: int = 40) -> JsonMap:
    return command([python, "-m", "mere_computer_use", *args], env=env, timeout=timeout)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as address:
        address.bind(("127.0.0.1", 0))
        return int(address.getsockname()[1])


def model_ready(base_url: str, model: str) -> bool:
    request = urllib.request.Request(base_url + "/models", headers={"Authorization": "Bearer mere-run"})
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = object_map(json.load(response))
    data = payload.get("data")
    if not isinstance(data, list):
        return False
    for item in data:
        if not isinstance(item, dict) or item.get("id") != model or item.get("tool_call") is not True:
            continue
        modalities = item.get("modalities")
        inputs = modalities.get("input") if isinstance(modalities, dict) else None
        if isinstance(inputs, list) and "image" in inputs:
            return True
    return False


def wait_for_model(server: subprocess.Popen[str], base_url: str, model: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError("mere.run API exited during startup; inspect api-server.log")
        try:
            if model_ready(base_url, model):
                return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f"mere.run API did not offer image/tool model within {timeout} seconds")


def model_benchmark_stats(base_url: str, model: str) -> JsonMap | None:
    request = urllib.request.Request(base_url.removesuffix("/v1") + "/runtime/status",
                                     headers={"Authorization": "Bearer mere-run"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = object_map(json.load(response))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None
    models = payload.get("models")
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict) and item.get("id") == model \
                    and isinstance(item.get("benchmarkStats"), dict):
                return object_map(item["benchmarkStats"])
    return None


def decode_delta(before: JsonMap | None, after: JsonMap | None) -> JsonMap | None:
    if before is None or after is None:
        return None
    completed = after.get("completedRequests")
    generated = after.get("generatedTokens")
    average = after.get("averageDecodeSeconds")
    if not isinstance(completed, int) or not isinstance(generated, int) \
            or not isinstance(average, (int, float)):
        return None
    previous_completed_value = before.get("completedRequests")
    previous_generated_value = before.get("generatedTokens")
    previous_average = before.get("averageDecodeSeconds")
    if not isinstance(previous_completed_value, int) or not isinstance(previous_generated_value, int):
        return None
    previous_completed = previous_completed_value
    previous_generated = previous_generated_value
    previous_seconds = 0.0
    if previous_completed:
        if not isinstance(previous_average, (int, float)):
            return None
        previous_seconds = float(previous_average) * previous_completed
    requests = completed - previous_completed
    tokens = generated - previous_generated
    seconds = float(average) * completed - previous_seconds
    if requests < 1 or tokens < 0 or seconds <= 0:
        return None
    return {"completedRequests": requests, "generatedTokens": tokens,
            "decodeSeconds": round(seconds, 3), "tokensPerSecond": round(tokens / seconds, 2)}


def window_for(python: str, env: dict[str, str], pid: int, case_id: str, timeout: int) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = plugin_command(python, ["windows"], env)
        windows = response.get("windows")
        if isinstance(windows, list):
            for item in windows:
                if isinstance(item, dict) and item.get("pid") == pid \
                        and item.get("title") == f"Computer Use Eval: {case_id}" \
                        and item.get("is_on_screen") is True and isinstance(item.get("window_id"), int):
                    return int(item["window_id"])
        time.sleep(0.3)
    raise RuntimeError(f"fixture window {case_id} did not appear in Cua Driver")


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run_case(case_id: str, iteration: int, args: argparse.Namespace, app: pathlib.Path,
             base_url: str, env: dict[str, str], output: pathlib.Path) -> JsonMap:
    case_dir = output / f"{case_id}-{iteration:02d}"
    case_dir.mkdir()
    nonce = code_for(args.seed, case_id, iteration)
    state_path = case_dir / "fixture-state.json"
    started = time.monotonic()
    wall_started_ns = time.time_ns()
    agent_started: float | None = None
    agent_finished: float | None = None
    with (case_dir / "fixture.log").open("w", encoding="utf-8") as log:
        fixture = subprocess.Popen([str(app), case_id, nonce, str(state_path)], stdout=log,
                                   stderr=subprocess.STDOUT, text=True, start_new_session=True)
        run_path = case_dir / "run.json"
        error = None
        try:
            window_id = window_for(args.python, env, fixture.pid, case_id, 15)
            plugin_command(args.python, ["plan", "--pid", str(fixture.pid), "--window-id", str(window_id),
                                         "--task", task_for(case_id), "--output", str(case_dir),
                                         "--model", args.model, "--base-url", base_url,
                                         "--max-actions", "8"], env)
            agent_started = time.monotonic()
            try:
                plugin_command(args.python, ["run", str(run_path), "--timeout", str(args.timeout),
                                             "--api-start-timeout", str(args.startup_timeout)],
                               env, timeout=args.timeout + args.startup_timeout + 30)
            finally:
                agent_finished = time.monotonic()
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            error = str(exc)
        finally:
            stop(fixture)
    case_finished = time.monotonic()
    state = read_json(state_path) if state_path.is_file() else {}
    run = read_json(run_path) if run_path.is_file() else {}
    failures = score_case(case_id, nonce, state, run)
    if error:
        failures.insert(0, error)
    reached = outcome_reached(case_id, nonce, state, run)
    outcome_seconds: float | None = None
    if reached and case_id == "read-code" and agent_finished is not None:
        outcome_seconds = round(agent_finished - started, 3)
    elif reached and state_path.is_file():
        elapsed = (state_path.stat().st_mtime_ns - wall_started_ns) / 1_000_000_000
        if 0 <= elapsed <= case_finished - started + 2:
            outcome_seconds = round(elapsed, 3)
    result: JsonMap = {
        "case": case_id,
        "iteration": iteration,
        "passed": not failures,
        "outcomeReached": reached,
        "outcomeWallTimeSeconds": outcome_seconds,
        "failures": failures,
        "durationSeconds": round(case_finished - started, 3),
        "agentWallTimeSeconds": round(agent_finished - agent_started, 3)
        if agent_started is not None and agent_finished is not None else None,
        "actionCount": run.get("actionCount"),
        "observationCount": run.get("observationCount"),
        "runStatus": run.get("status"),
        "verification": run.get("verification"),
        "manifestPath": str(run_path) if run_path.is_file() else None,
        "fixtureStatePath": str(state_path) if state_path.is_file() else None,
        "fixtureStateSha256": hashlib.sha256(state_path.read_bytes()).hexdigest() if state_path.is_file() else None,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--engine", help="mere.run engine; known model IDs have defaults")
    parser.add_argument("--mere-run", default="mere.run")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--seed", default=secrets.token_hex(8), help="reuse the same seed to compare models")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--startup-timeout", type=int, default=300)
    args = parser.parse_args()
    if args.repeat < 1 or args.timeout < 1 or args.startup_timeout < 1:
        parser.error("repeat and timeouts must be positive")
    engine = args.engine or ENGINES.get(args.model)
    if engine is None:
        parser.error("unknown model engine; provide --engine")
    benchmark_started = time.monotonic()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or ROOT / "runs" / "computer-use-v0" / f"{stamp}-{args.model}").resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = output / "EvalApp"
    environment = os.environ.copy()
    source = str(ROOT / "packages" / "mere-computer-use" / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
    environment["MERE_COMPUTER_USE_MERE_RUN"] = args.mere_run
    wrapper = output / "mere-computer-use"
    wrapper.write_text(f"#!/bin/sh\nexec {shlex.quote(args.python)} -m mere_computer_use \"$@\"\n",
                       encoding="utf-8")
    wrapper.chmod(0o700)
    environment["MERE_COMPUTER_USE_COMMAND"] = str(wrapper)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}/v1"
    mere_run_path = shutil.which(args.mere_run)
    if mere_run_path is None:
        parser.error(f"mere.run executable not found: {args.mere_run}")
    report: JsonMap = {"benchmark": "computer-use-v0", "model": args.model, "engine": engine,
                       "mereRun": str(pathlib.Path(mere_run_path).resolve()), "baseUrl": base_url,
                       "cases": [], "status": "running", "startedAt": stamp,
                       "requestedCases": args.case or list(CASES), "repeat": args.repeat, "seed": args.seed,
                       "suiteSha256": hashlib.sha256((HERE / "EvalApp.swift").read_bytes()
                                                     + pathlib.Path(__file__).read_bytes()).hexdigest(),
                       "sourceCommit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                                     capture_output=True, check=True).stdout.strip()}
    write_json(output / "report.json", report)
    server: subprocess.Popen[str] | None = None
    api_started: float | None = None
    try:
        preflight(args.mere_run, engine, args.model, port)
        subprocess.run(["swiftc", str(HERE / "EvalApp.swift"), "-o", str(app)], check=True,
                       text=True, capture_output=True, timeout=60)
        with (output / "api-server.log").open("w", encoding="utf-8") as log:
            api_started = time.monotonic()
            server = subprocess.Popen([args.mere_run, "api", "serve", "--engine", engine,
                                       "--model", args.model, "--host", "127.0.0.1", "--port", str(port)],
                                      stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            wait_for_model(server, base_url, args.model, args.startup_timeout)
            report["apiStartupWallTimeSeconds"] = round(time.monotonic() - api_started, 3)
            report["setupWallTimeSeconds"] = round(time.monotonic() - benchmark_started, 3)
            for iteration in range(1, args.repeat + 1):
                for case_id in args.case or CASES:
                    before_stats = model_benchmark_stats(base_url, args.model)
                    result = run_case(case_id, iteration, args, app, base_url, environment, output)
                    result["decode"] = decode_delta(before_stats, model_benchmark_stats(base_url, args.model))
                    cast(list[JsonMap], report["cases"]).append(result)
                    write_json(output / "report.json", report)
                    sys.stderr.write(f"{case_id} #{iteration}: {'pass' if result['passed'] else 'fail'}\n")
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        report["error"] = str(exc)
        report["status"] = "setup-failed"
    finally:
        if server:
            stop(server)
        if api_started is not None and "apiStartupWallTimeSeconds" not in report:
            report["apiStartupWallTimeSeconds"] = round(time.monotonic() - api_started, 3)
        if "setupWallTimeSeconds" not in report:
            report["setupWallTimeSeconds"] = round(time.monotonic() - benchmark_started, 3)
    if report["status"] == "running":
        cases = cast(list[JsonMap], report["cases"])
        report["status"] = "passed" if cases and all(case["passed"] for case in cases) else "failed"
    report["benchmarkWallTimeSeconds"] = round(time.monotonic() - benchmark_started, 3)
    report["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_json(output / "report.json", report)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["status"] == "passed" else 1 if report["status"] == "setup-failed" else 2


if __name__ == "__main__":
    sys.exit(main())

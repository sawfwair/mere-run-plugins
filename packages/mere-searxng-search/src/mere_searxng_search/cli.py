from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from importlib import resources
from typing import NoReturn, cast

from . import __version__
from . import instance as local_instance

JsonMap = dict[str, object]
MAX_RESPONSE_BYTES = 4_000_000


class SearchError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise SearchError(message)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def print_json(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def private_json(path: pathlib.Path, value: object) -> None:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=".searxng-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_json(path: pathlib.Path) -> JsonMap:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail(f"cannot read {path.name}")
    if not isinstance(value, dict):
        fail(f"{path.name} must be a JSON object")
    return cast(JsonMap, value)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def instance_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        fail("instance must be an HTTP(S) URL without credentials")
    if parsed.query or parsed.fragment:
        fail("instance URL cannot contain a query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        fail("remote SearXNG instances must use HTTPS")
    try:
        _ = parsed.port
    except ValueError:
        fail("instance URL has an invalid port")
    return raw.rstrip("/")


def request_from_args(args: argparse.Namespace) -> JsonMap:
    instance = args.instance or os.environ.get("SEARXNG_URL", "") or local_instance.instance_url(
        local_instance.state_dir(args.state_dir)
    )
    if not instance:
        fail("install a local instance or set --instance or SEARXNG_URL")
    query = args.query.strip()
    if not query:
        fail("query must be nonempty")
    if args.page < 1 or args.limit < 1 or args.limit > 100:
        fail("page must be positive and limit must be between 1 and 100")
    if args.timeout <= 0 or args.timeout > 120:
        fail("timeout must be between 1 and 120 seconds")
    return {
        "instance": instance_url(instance),
        "query": query,
        "page": args.page,
        "limit": args.limit,
        "language": args.language,
        "categories": args.categories,
        "timeRange": args.time_range,
        "safeSearch": args.safe_search,
        "timeout": args.timeout,
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, _request: urllib.request.Request, _fp: object, _code: int, _msg: str,
        _headers: object, _newurl: str,
    ) -> None:
        return None


def search(request: JsonMap) -> JsonMap:
    base = request.get("instance")
    query = request.get("query")
    if not isinstance(base, str) or not isinstance(query, str) or not query.strip():
        fail("invalid saved search request")
    base = instance_url(base)
    params = {"q": query, "format": "json", "pageno": str(request["page"]), "safesearch": str(request["safeSearch"])}
    for source, destination in (("language", "language"), ("categories", "categories"), ("timeRange", "time_range")):
        value = request.get(source)
        if isinstance(value, str) and value:
            params[destination] = value
    url = base + "/search?" + urllib.parse.urlencode(params)
    http_request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "mere-searxng-search/0.1"})
    try:
        with urllib.request.build_opener(NoRedirect).open(http_request, timeout=float(str(request["timeout"]))) as response:
            content_type = response.headers.get_content_type()
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 403:
            fail("SearXNG refused JSON search (HTTP 403); enable search.formats: [html, json] on the instance")
        fail(f"SearXNG returned HTTP {error.code}")
    except (urllib.error.URLError, TimeoutError, OSError):
        fail("could not reach the SearXNG instance")
    if len(data) > MAX_RESPONSE_BYTES:
        fail("SearXNG response exceeds 4 MB")
    if content_type != "application/json":
        fail("SearXNG did not return JSON; check that JSON output is enabled")
    try:
        payload = json.loads(data)
    except (UnicodeError, json.JSONDecodeError):
        fail("SearXNG returned invalid JSON")
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        fail("SearXNG response has no results array")
    raw_results = cast(list[object], payload["results"])
    results: list[JsonMap] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        item = cast(JsonMap, raw)
        title, link = item.get("title"), item.get("url")
        if not isinstance(title, str) or not isinstance(link, str):
            continue
        results.append({
            "title": title,
            "url": link,
            "snippet": item.get("content") if isinstance(item.get("content"), str) else "",
            "engine": item.get("engine") if isinstance(item.get("engine"), str) else None,
            "score": item.get("score") if isinstance(item.get("score"), (int, float)) else None,
        })
        if len(results) >= int(str(request["limit"])):
            break
    return {"query": query, "page": request["page"], "instance": base, "results": results,
            "suggestions": payload.get("suggestions", []), "answers": payload.get("answers", [])}


def manifest() -> JsonMap:
    commands = [("manifest", "Describe this plugin"), ("doctor", "Check instance JSON search"),
                ("search", "Search directly"), ("plan", "Save a search plan"), ("run", "Execute a saved search"),
                ("resume", "Read a completed search"), ("cleanup", "Record cleanup"),
                ("instance", "Install and manage a local SearXNG instance"),
                ("pi-extension", "Locate the bundled Pi search tool")]
    return {
        "contractVersion": "mere.run/plugin.v1", "name": "mere-searxng-search", "version": __version__,
        "executable": "mere-searxng-search", "description": "Search a user-configured SearXNG instance",
        "homepage": "https://github.com/searxng/searxng",
        "capabilities": ["web-search", "searxng", "json-results", "local-instance", "container-management", "pi-tool"],
        "commands": [{"name": name, "description": description,
                      "stdout": "paths" if name == "pi-extension" else "json"} for name, description in commands],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {"usesUserCredentials": False, "storesSecrets": False, "createsPaidResources": False,
                     "cleanupDefault": "none"},
    }


def run_path(value: str) -> pathlib.Path:
    path = pathlib.Path(value).expanduser().resolve()
    if path.name != "run.json":
        fail("expected a run.json path")
    return path


def saved_request(path: pathlib.Path, manifest_data: JsonMap) -> JsonMap:
    if manifest_data.get("plugin") != "mere-searxng-search":
        fail("run manifest belongs to a different plugin")
    request = load_json(path.parent / "request.json")
    if digest(request) != manifest_data.get("requestSha256"):
        fail("saved request changed after planning")
    return request


def execute(path: pathlib.Path) -> JsonMap:
    record = load_json(path)
    request = saved_request(path, record)
    if record.get("status") != "planned":
        fail("run is not planned; inspect or create a new plan")
    record["status"] = "running"
    record["updatedAt"] = now_iso()
    private_json(path, record)
    try:
        result = search(request)
    except SearchError:
        record["status"] = "failed"
        record["updatedAt"] = now_iso()
        private_json(path, record)
        raise
    private_json(path.parent / "result.json", result)
    record["status"] = "complete"
    record["updatedAt"] = now_iso()
    private_json(path, record)
    return result


def add_search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("query")
    parser.add_argument("--instance")
    parser.add_argument("--state-dir")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--language")
    parser.add_argument("--categories")
    parser.add_argument("--time-range", choices=("day", "month", "year"))
    parser.add_argument("--safe-search", type=int, choices=(0, 1, 2), default=1)
    parser.add_argument("--timeout", type=float, default=15.0)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="mere-searxng-search")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("manifest").add_argument("--json", action="store_true")
    commands.add_parser("pi-extension")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--instance")
    doctor.add_argument("--state-dir")
    doctor.add_argument("--timeout", type=float, default=15.0)
    add_search_args(commands.add_parser("search"))
    plan = commands.add_parser("plan")
    add_search_args(plan)
    plan.add_argument("--output", required=True)
    for command in ("run", "resume", "cleanup"):
        commands.add_parser(command).add_argument("run_manifest")
    instance = commands.add_parser("instance")
    actions = instance.add_subparsers(dest="instance_command", required=True)
    for command in ("plan", "install", "start", "status", "stop", "uninstall"):
        action = actions.add_parser(command)
        action.add_argument("--state-dir")
        if command in ("plan", "install"):
            action.add_argument("--port", type=int, default=8888)
            action.add_argument("--docker-context")
            action.add_argument("--image", default=local_instance.DEFAULT_IMAGE)
        if command == "uninstall":
            action.add_argument("--purge", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "manifest":
            print_json(manifest())
        elif args.command == "pi-extension":
            extension = pathlib.Path(str(resources.files("mere_searxng_search"))) / "resources" / "pi" / "extensions" / "searxng-search.ts"
            if not extension.is_file():
                fail("bundled Pi extension is missing")
            sys.stdout.write(str(extension) + "\n")
        elif args.command == "doctor":
            probe = argparse.Namespace(query="searxng", instance=args.instance, page=1, limit=1,
                                       language=None, categories=None, time_range=None, safe_search=1,
                                       timeout=args.timeout, state_dir=args.state_dir)
            result = search(request_from_args(probe))
            print_json({"ready": True, "instance": result["instance"], "jsonSearch": True})
        elif args.command == "instance":
            directory = local_instance.state_dir(args.state_dir)
            if args.instance_command == "plan":
                print_json(local_instance.plan(directory, args.port, args.docker_context, args.image))
            elif args.instance_command == "install":
                print_json(local_instance.install(directory, args.port, args.docker_context, args.image))
            elif args.instance_command == "start":
                print_json(local_instance.start(directory))
            elif args.instance_command == "status":
                print_json(local_instance.status(directory))
            elif args.instance_command == "stop":
                print_json(local_instance.stop(directory))
            elif args.instance_command == "uninstall":
                print_json(local_instance.uninstall(directory, args.purge))
        elif args.command == "search":
            print_json(search(request_from_args(args)))
        elif args.command == "plan":
            request = request_from_args(args)
            directory = pathlib.Path(args.output).expanduser().resolve()
            if directory.exists():
                fail("output directory already exists")
            directory.mkdir(parents=True, mode=0o700)
            private_json(directory / "request.json", request)
            record: JsonMap = {"contractVersion": "mere.run/searxng-search-run.v1", "plugin": "mere-searxng-search",
                               "status": "planned", "createdAt": now_iso(), "updatedAt": now_iso(),
                               "requestSha256": digest(request), "resultPath": str(directory / "result.json")}
            private_json(directory / "run.json", record)
            print_json(record)
        elif args.command == "run":
            print_json(execute(run_path(args.run_manifest)))
        elif args.command == "resume":
            path = run_path(args.run_manifest)
            record = load_json(path)
            saved_request(path, record)
            if record.get("status") != "complete":
                fail("run is not complete; resume never repeats a search")
            print_json(load_json(path.parent / "result.json"))
        elif args.command == "cleanup":
            path = run_path(args.run_manifest)
            record = load_json(path)
            saved_request(path, record)
            record["cleanedAt"] = now_iso()
            record["updatedAt"] = now_iso()
            private_json(path, record)
            print_json(record)
    except (SearchError, local_instance.InstanceError) as error:
        sys.stderr.write(str(error) + "\n")
        return 2
    return 0

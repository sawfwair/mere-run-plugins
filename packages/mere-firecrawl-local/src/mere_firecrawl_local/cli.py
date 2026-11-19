from __future__ import annotations

import argparse
import ipaddress
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import cast

from . import __version__, pi, standalone

PLUGIN = "mere-firecrawl-local"
MAX_RESPONSE_BYTES = 4_000_000
MAX_MARKDOWN_CHARS = 16_000
DESCRIPTION = "Read public web pages through a separately installed Firecrawl Local instance"
COMMANDS = (
    ("manifest", "Describe this plugin", "json"),
    ("doctor", "Check Firecrawl Local readiness", "json"),
    ("setup", "Install and start the separate Firecrawl Local app", "json"),
    ("scrape", "Read one page as Markdown", "json"),
    ("pi-extension", "Locate the Pi extension", "paths"),
    ("pi", "Manage the tool in mere.run's Pi agent", "json"),
)


class InputError(ValueError):
    pass


class FirecrawlError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, _request: urllib.request.Request, _fp: object, _code: int, _msg: str,
        _headers: object, _newurl: str,
    ) -> None:
        return None


def http_url(raw: str, label: str) -> urllib.parse.SplitResult:
    message = f"{label} must be an HTTP(S) URL without credentials"
    if len(raw) > 2048 or any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in raw):
        raise InputError(message)
    try:
        parsed = urllib.parse.urlsplit(raw)
        _ = parsed.port
        host = parsed.hostname
    except ValueError as error:
        raise InputError(message) from error
    if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None:
        raise InputError(message)
    return parsed


def endpoint_url(raw: str) -> str:
    parsed = http_url(raw, "Firecrawl endpoint")
    if parsed.query or parsed.fragment:
        raise InputError("Firecrawl endpoint cannot contain a query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise InputError("A Firecrawl endpoint outside loopback must use HTTPS")
    return raw.rstrip("/")


def public_page_url(raw: str) -> str:
    host = (http_url(raw, "Page URL").hostname or "").rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise InputError("Page URL must refer to a public host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return raw
    if not address.is_global or address.is_multicast:
        raise InputError("Page URL must refer to a public host")
    return raw


def request_json(endpoint: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
    request = urllib.request.Request(
        endpoint + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    token = os.environ.get("MERE_FIRECRAWL_TOKEN")
    if token:
        if not token.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise InputError("MERE_FIRECRAWL_TOKEN must be a single ASCII token")
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
        with opener.open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        error.close()
        raise FirecrawlError(f"Firecrawl returned HTTP {error.code}") from error
    except (urllib.error.URLError, OSError) as error:
        raise FirecrawlError(
            "Could not reach Firecrawl. Open the standalone Firecrawl Local app or check MERE_FIRECRAWL_URL."
        ) from error
    if len(raw) > MAX_RESPONSE_BYTES:
        raise FirecrawlError("Firecrawl response exceeds 4 MB")
    try:
        payload: object = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise FirecrawlError("Firecrawl returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise FirecrawlError("Firecrawl returned an unexpected response")
    return cast(dict[str, object], payload)


def scrape(endpoint: str, url: str) -> dict[str, object]:
    url = public_page_url(url)
    payload = request_json(endpoint, "/v2/scrape", {"url": url, "formats": ["markdown"], "timeout": 15_000})
    data = payload.get("data")
    if payload.get("success") is not True or not isinstance(data, dict):
        raise FirecrawlError("Firecrawl did not return a page")
    page = cast(dict[str, object], data)
    markdown = page.get("markdown")
    if page.get("blocked") is True or not isinstance(markdown, str) or not markdown.strip():
        raise FirecrawlError("Firecrawl did not return readable Markdown")
    metadata = page.get("metadata")
    title = cast(dict[str, object], metadata).get("title") if isinstance(metadata, dict) else None
    final_url = cast(dict[str, object], metadata).get("url") if isinstance(metadata, dict) else None
    if isinstance(final_url, str):
        try:
            final_url = public_page_url(final_url)
        except InputError:
            final_url = None
    return {
        "requestedUrl": url,
        "url": final_url if isinstance(final_url, str) else url,
        "title": title[:300] if isinstance(title, str) else None,
        "markdown": markdown[:MAX_MARKDOWN_CHARS],
        "truncated": len(markdown) > MAX_MARKDOWN_CHARS,
    }


def manifest() -> dict[str, object]:
    return {
        "contractVersion": "mere.run/plugin.v1", "name": PLUGIN, "executable": PLUGIN,
        "version": __version__, "description": DESCRIPTION,
        "capabilities": ["web-scrape", "markdown", "pi-tool"],
        "commands": [
            {"name": name, "description": description, "stdout": stream}
            for name, description, stream in COMMANDS
        ],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {"usesUserCredentials": True, "storesSecrets": False, "createsPaidResources": False,
                     "cleanupDefault": "none"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=PLUGIN, description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("manifest").add_argument("--json", action="store_true")
    commands.add_parser("pi-extension")
    pi_command = commands.add_parser("pi")
    pi_command.add_argument("action", choices=("enable", "status", "disable"))
    commands.add_parser("doctor").add_argument("--endpoint")
    commands.add_parser("setup").add_argument("--yes", action="store_true")
    scrape_command = commands.add_parser("scrape")
    scrape_command.add_argument("--endpoint")
    scrape_command.add_argument("url")
    args = parser.parse_args(argv)

    extension = pathlib.Path(__file__).resolve().parent / "resources/pi/extensions/firecrawl-scrape.ts"
    try:
        if args.command == "manifest":
            result = manifest()
        elif args.command == "pi-extension":
            if not extension.is_file():
                raise pi.PiError("Bundled Pi extension is missing")
            sys.stdout.write(f"{extension}\n")
            return 0
        elif args.command == "pi":
            result = pi.manage(args.action, extension)
        elif args.command == "setup":
            configured = os.environ.get("MERE_FIRECRAWL_URL")
            endpoint = endpoint_url(configured) if configured else standalone.ENDPOINT
            if not args.yes:
                result = {"status": "planned", "endpoint": endpoint, "download": None if configured else standalone.IMAGE}
            elif configured:
                health = request_json(endpoint, "/health")
                if health.get("status") != "ok":
                    raise FirecrawlError("The configured Firecrawl endpoint did not report a healthy service")
                result = {"ready": True, "status": "configured", "endpoint": endpoint, "version": health.get("version")}
            else:
                result = standalone.setup()
        else:
            endpoint = endpoint_url(args.endpoint or os.environ.get("MERE_FIRECRAWL_URL") or standalone.ENDPOINT)
            if args.command == "doctor":
                health = request_json(endpoint, "/health")
                if health.get("status") != "ok":
                    raise FirecrawlError("Firecrawl did not report a healthy service")
                result = {"ready": True, "endpoint": endpoint, "version": health.get("version")}
            else:
                result = scrape(endpoint, args.url)
    except (InputError, FirecrawlError, pi.PiError, standalone.SetupError, OSError) as error:
        sys.stderr.write(f"{PLUGIN}: {error}\n")
        if isinstance(error, InputError):
            return 2
        return 3 if args.command == "doctor" else 1
    sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
    return 0

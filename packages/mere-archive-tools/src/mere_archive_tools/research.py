"""Collect a bounded set of public web sources through installed plugins."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import pathlib
import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

from .runtime import InferenceError, JsonMap, as_list, as_map, split_command

SEARCH_PLUGIN = "mere-searxng-search"
SCRAPE_PLUGIN = "mere-firecrawl-local"
MAX_RESULTS = 20
INDEX_MODELS = ("text-anonymize-privacy-filter", "vision-embed-qwen3-vl-2b")
TRACKING_PARAMETERS = {"gclid", "dclid", "fbclid", "msclkid"}


class ResearchError(RuntimeError):
    pass


def validate_query(query: str, limit: int) -> None:
    if not query.strip() or len(query) > 600 or any(ord(char) < 32 or ord(char) == 127 for char in query):
        raise ResearchError("Provide a single-line query of 1 to 600 characters.")
    if not 1 <= limit <= MAX_RESULTS:
        raise ResearchError(f"--limit must be between 1 and {MAX_RESULTS}.")


def public_url(raw: object) -> str | None:
    if not isinstance(raw, str) or len(raw) > 2_048 or any(ord(char) <= 32 or ord(char) == 127 for char in raw):
        return None
    if "\\" in raw:
        return None
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").rstrip(".")
        port = parsed.port
        if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None or parsed.password is not None:
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", host) or "." not in host:
                return None
            if host.endswith((".localhost", ".local", ".internal", ".home", ".test")) or re.fullmatch(
                r"(?:0x[0-9a-f]+|[0-9]+)", host.rsplit(".", 1)[-1],
            ):
                return None
        else:
            if not address.is_global or address.is_multicast:
                return None
    except ValueError:
        return None
    if port not in {None, 80 if parsed.scheme == "http" else 443}:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def comparison_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".")
    google_article = host == "support.google.com" and re.fullmatch(
        r"/(?:mail|a(?:/users)?)/answer/\d+/?", parsed.path,
    )
    query = []
    for parameter in parsed.query.split("&") if parsed.query else ():
        raw_key, _, raw_value = parameter.partition("=")
        key, value = unquote_plus(raw_key), unquote_plus(raw_value)
        if key.lower() in TRACKING_PARAMETERS or key.lower().startswith("utm_"):
            continue
        if host == "slack.com" and key == "nojsmode" and value == "1":
            continue
        if google_article and (
            (key == "hl" and re.fullmatch(r"en(?:-[a-z]{2})?", value, re.IGNORECASE))
            or (key == "co" and value == "GENIE.Platform=Desktop")
        ):
            continue
        query.append(parameter)
    authority = f"[{host}]" if ":" in host else host
    return urlunsplit((parsed.scheme, authority, parsed.path or "/", "&".join(query), ""))


def call_json(runtime: str, command: list[str], service: str) -> JsonMap:
    try:
        completed = subprocess.run(
            [*split_command(runtime), *command], stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=40, check=False,
        )
    except subprocess.TimeoutExpired:
        raise ResearchError(f"{service} did not respond within 40 seconds.") from None
    except OSError:
        raise ResearchError("Could not start mere.run. Check --mere-run-command.") from None
    if completed.returncode:
        raise ResearchError(f"{service} exited with status {completed.returncode}. Check its setup and connectivity.")
    try:
        return as_map(json.loads(completed.stdout), service)
    except (ValueError, InferenceError):
        raise ResearchError(f"{service} returned invalid JSON.") from None


def plugin_json(runtime: str, plugin: str, command: list[str]) -> JsonMap:
    return call_json(runtime, ["plugin", "run", plugin, "--", *command], plugin)


def check_index_models(runtime: str) -> None:
    payload = call_json(runtime, ["model", "list", "--json"], "mere.run model list")
    inventory = as_map(payload.get("inventory"), "model inventory")
    rows = as_list(inventory.get("rows"), "model inventory rows")
    installed = {
        row.get("id") for row in rows if isinstance(row, dict) and row.get("status") == "installed"
        and row.get("runtimeAvailable") is True
    }
    if missing := [model for model in INDEX_MODELS if model not in installed]:
        raise ResearchError("Install the archive models, then resume this run: " + ", ".join(missing))


@contextmanager
def run_lock(directory: pathlib.Path) -> Iterator[None]:
    import fcntl

    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ResearchError("A research command is already running in this directory.") from None
        yield
    finally:
        os.close(descriptor)


def write_private_json(path: pathlib.Path, payload: object) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = pathlib.Path(handle.name)
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def clean_label(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    return " ".join("".join(char for char in value if char.isprintable() or char.isspace()).split())[:300] or fallback


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass
class Source:
    identifier: str
    url: str
    requested_url: str
    title: str
    engine: str | None
    body_sha256: str
    truncated: bool
    alternate_urls: list[str] = field(default_factory=list)

    @property
    def relative_path(self) -> str:
        return f"sources/{self.identifier}.md"

    def add_alias(self, url: str) -> None:
        if url not in {self.url, self.requested_url, *self.alternate_urls}:
            self.alternate_urls.append(url)

    def citation(self) -> JsonMap:
        return {
            "id": self.identifier, "title": self.title, "url": self.url, "requestedUrl": self.requested_url,
            "alternateUrls": self.alternate_urls, "engine": self.engine, "path": self.relative_path,
            "sha256": self.body_sha256, "truncated": self.truncated,
        }


def search_results(runtime: str, root: pathlib.Path, query: str, limit: int) -> list[object]:
    cache = root / "search.json"
    if cache.is_file():
        saved = as_map(json.loads(cache.read_bytes()), "saved search")
        if saved.get("query") != query or saved.get("limit") != limit:
            raise ResearchError("The saved search does not match the run plan.")
        return as_list(saved.get("results"), "saved search results")
    reply = plugin_json(runtime, SEARCH_PLUGIN, ["search", "--limit", str(limit), "--", query])
    if reply.get("query") != query:
        raise ResearchError("SearXNG returned results for a different query.")
    rows = as_list(reply.get("results"), "SearXNG results")[:limit]
    results: list[object] = []
    for raw in rows:
        row = as_map(raw, "SearXNG result")
        results.append({
            "url": public_url(row.get("url")), "title": clean_label(row.get("title"), ""),
            "engine": clean_label(row.get("engine"), "") or None,
        })
    write_private_json(cache, {"query": query, "limit": limit, "results": results})
    return results


def render_citations(sources: list[Source]) -> str:
    lines = ["# Source citations", ""]
    for source in sources:
        title = re.sub(r"([\\`*_\[\]<>!&])", r"\\\1", source.title)
        url = quote(source.url, safe=":/?&=%+;@,._~[]!$'-")
        lines.append(f"- [{source.identifier}](<{url}>) {title}")
    return "\n".join(lines) + "\n"


def scrape_sources(runtime: str, staging: pathlib.Path, candidates: list[object]) -> tuple[list[Source], list[JsonMap]]:
    sources: list[Source] = []
    skipped: list[JsonMap] = []
    requested: dict[str, Source | None] = {}
    by_url: dict[str, Source] = {}
    by_content: dict[str, Source] = {}
    manifest = plugin_json(runtime, SCRAPE_PLUGIN, ["manifest", "--json"])
    capabilities = as_list(manifest.get("capabilities", []), "Firecrawl capabilities")
    scrape_command = ["scrape", "--full"] if "full-markdown" in capabilities else ["scrape"]
    for rank, raw in enumerate(candidates, 1):
        row = as_map(raw, "research search result")
        url = public_url(row.get("url"))
        if url is None:
            skipped.append({"rank": rank, "reason": "invalid-public-url"})
            continue
        key = comparison_url(url)
        if key in requested:
            if previous := requested[key]:
                previous.add_alias(url)
            skipped.append({"rank": rank, "url": url, "reason": "duplicate-url"})
            continue
        requested[key] = None
        try:
            page = plugin_json(runtime, SCRAPE_PLUGIN, [*scrape_command, "--", url])
        except ResearchError as exc:
            skipped.append({"rank": rank, "url": url, "reason": "fetch-failed", "detail": str(exc)})
            continue
        final_url = public_url(page.get("url"))
        markdown = page.get("markdown")
        if page.get("requestedUrl") != url or final_url is None or not isinstance(markdown, str) or not markdown.strip():
            skipped.append({"rank": rank, "url": url, "reason": "invalid-page"})
            continue
        body = (markdown.strip() + "\n").encode("utf-8", errors="replace")
        body_hash = digest(body)
        final_key = comparison_url(final_url)
        previous = by_url.get(final_key) or by_content.get(body_hash)
        if previous is not None:
            previous.add_alias(url)
            previous.add_alias(final_url)
            requested[key] = by_url[final_key] = previous
            skipped.append({"rank": rank, "url": url, "reason": "duplicate-source", "citation": previous.identifier})
            continue
        source = Source(
            f"S{len(sources) + 1:02d}", final_url, url, clean_label(page.get("title"), clean_label(row.get("title"), final_url)),
            clean_label(row.get("engine"), "") or None, body_hash, page.get("truncated") is True,
        )
        (staging / source.relative_path).write_bytes(body)
        sources.append(source)
        requested[key] = by_url[final_key] = by_content[body_hash] = source
    return sources, skipped


def collect(runtime: str, root: pathlib.Path, query: str, limit: int) -> JsonMap:
    destination = root / "collection"
    if destination.exists():
        return read_collection(destination, query, limit)
    candidates = search_results(runtime, root, query, limit)
    with tempfile.TemporaryDirectory(prefix=".research-", dir=root) as temporary:
        staging = pathlib.Path(temporary) / "collection"
        (staging / "sources").mkdir(parents=True)
        sources, skipped = scrape_sources(runtime, staging, candidates)
        if not sources:
            write_private_json(root / "skipped.json", skipped)
            raise ResearchError("No source pages could be collected. See skipped.json for the result of each attempt.")
        citations = render_citations(sources).encode("utf-8")
        report = {"query": query, "limit": limit, "sources": [source.citation() for source in sources],
                  "citationsSha256": digest(citations), "skipped": skipped}
        (staging / "citations.md").write_bytes(citations)
        write_private_json(staging / "sources.json", report)
        staging.rename(destination)
    (root / "skipped.json").unlink(missing_ok=True)
    return report


def read_collection(directory: pathlib.Path, query: str, limit: int) -> JsonMap:
    source_root, index, citations = directory / "sources", directory / "sources.json", directory / "citations.md"
    if any(path.is_symlink() for path in (directory, source_root, index, citations)) or not source_root.is_dir():
        raise ResearchError("The saved collection has missing or unexpected paths. Start a new run.")
    report = as_map(json.loads(index.read_bytes()), "saved research collection")
    if report.get("query") != query or report.get("limit") != limit:
        raise ResearchError("The saved collection does not match the run plan.")
    sources = as_list(report.get("sources"), "saved collection sources")
    if not sources or len(sources) > limit:
        raise ResearchError("The saved collection has an invalid source count.")
    expected_paths: set[pathlib.Path] = set()
    for ordinal, row in enumerate(sources, 1):
        record = as_map(row, "saved source citation")
        path = source_root / f"S{ordinal:02d}.md"
        if (record.get("path") != f"sources/{path.name}" or path.is_symlink() or not path.is_file()
                or digest(path.read_bytes()) != record.get("sha256")):
            raise ResearchError("A saved source changed after collection. Start a new run.")
        expected_paths.add(path)
    if set(source_root.iterdir()) != expected_paths or not citations.is_file() or digest(citations.read_bytes()) != report.get("citationsSha256"):
        raise ResearchError("The saved collection has missing or unexpected files. Start a new run.")
    return report

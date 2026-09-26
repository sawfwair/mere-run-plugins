from __future__ import annotations

import contextlib
import http.server
import io
import json
import pathlib
import tempfile
import threading
import unittest
import urllib.parse
from collections.abc import Iterator

from mere_searxng_search import cli


class Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    calls = 0

    def do_GET(self) -> None:
        type(self).calls += 1
        path = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(path.query)
        if path.path != "/search" or params.get("format") != ["json"]:
            self.send_error(404)
            return
        if type(self).status != 200:
            self.send_error(type(self).status)
            return
        data = json.dumps({
            "results": [
                {"title": "First", "url": "https://example.org/first", "content": "A result", "engine": "test"},
                {"title": "Second", "url": "https://example.org/second"},
            ],
            "answers": [], "suggestions": ["sample"],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextlib.contextmanager
def server() -> Iterator[str]:
    Handler.status = 200
    Handler.calls = 0
    server_instance = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server_instance.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server_instance.server_port}"
    finally:
        server_instance.shutdown()
        thread.join()
        server_instance.server_close()


def invoke(*args: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(list(args))
    return code, stdout.getvalue(), stderr.getvalue()


class SearchTests(unittest.TestCase):
    def test_search_and_lifecycle(self) -> None:
        with server() as instance, tempfile.TemporaryDirectory() as directory:
            code, output, error = invoke("search", "sample query", "--instance", instance, "--limit", "1",
                                         "--page", "2", "--language", "en", "--categories", "general")
            self.assertEqual((code, error), (0, ""))
            result = json.loads(output)
            self.assertEqual(result["page"], 2)
            self.assertEqual(len(result["results"]), 1)
            self.assertEqual(result["results"][0]["snippet"], "A result")
            output_dir = pathlib.Path(directory) / "planned"
            code, output, _ = invoke("plan", "sample query", "--instance", instance, "--output", str(output_dir))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["status"], "planned")
            self.assertEqual(Handler.calls, 1)
            run_path = str(output_dir / "run.json")
            self.assertEqual(invoke("run", run_path)[0], 0)
            self.assertEqual(Handler.calls, 2)
            self.assertEqual(invoke("resume", run_path)[0], 0)
            self.assertEqual(Handler.calls, 2)
            self.assertEqual(invoke("cleanup", run_path)[0], 0)
            self.assertEqual(json.loads((output_dir / "run.json").read_text())["status"], "complete")
            self.assertEqual(output_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output_dir / "request.json").stat().st_mode & 0o777, 0o600)

    def test_disabled_json_and_request_change(self) -> None:
        with server() as instance, tempfile.TemporaryDirectory() as directory:
            Handler.status = 403
            code, output, error = invoke("doctor", "--instance", instance)
            self.assertEqual(code, 2)
            self.assertEqual(output, "")
            self.assertIn("enable search.formats", error)
            output_dir = pathlib.Path(directory) / "planned"
            self.assertEqual(invoke("plan", "original", "--instance", instance, "--output", str(output_dir))[0], 0)
            request_path = output_dir / "request.json"
            request = json.loads(request_path.read_text())
            request["query"] = "changed"
            request_path.write_text(json.dumps(request))
            code, _, error = invoke("run", str(output_dir / "run.json"))
            self.assertEqual(code, 2)
            self.assertIn("changed after planning", error)
            self.assertEqual(Handler.calls, 1)

    def test_instance_validation(self) -> None:
        for instance in ("http://example.org", "https://user:secret@example.org", "https://example.org/?key=secret"):
            with self.subTest(instance=instance):
                code, output, _ = invoke("search", "sample", "--instance", instance)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()

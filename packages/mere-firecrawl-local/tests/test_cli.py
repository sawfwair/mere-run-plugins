from __future__ import annotations

import contextlib
import io
import json
import pathlib
import tempfile
import unittest
import urllib.error
from unittest import mock

from mere_firecrawl_local import cli, pi


class FirecrawlTests(unittest.TestCase):
    def invoke(self, *args: str) -> tuple[int, str, str]:
        with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
            status = cli.main(list(args))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_doctor_checks_health_without_scraping(self) -> None:
        with mock.patch.object(cli, "request_json", return_value={"status": "ok", "version": "0.1.0"}) as request:
            status, stdout, stderr = self.invoke("doctor", "--endpoint", "http://127.0.0.1:4321/")
        request.assert_called_once_with("http://127.0.0.1:4321", "/health")
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["version"], "0.1.0")

    def test_scrape_limits_output_and_uses_caller_endpoint(self) -> None:
        url = "https://example.com/?q=sea"
        markdown = "A" * (cli.MAX_MARKDOWN_CHARS + 1)
        page = {"markdown": markdown, "metadata": {"url": "https://example.org/", "title": "Example"}}
        with mock.patch.dict(cli.os.environ, {"MERE_FIRECRAWL_URL": "https://firecrawl.example.org"}):
            with mock.patch.object(cli, "request_json", return_value={"success": True, "data": page}) as request:
                status, stdout, stderr = self.invoke("scrape", url)
        request.assert_called_once_with(
            "https://firecrawl.example.org", "/v2/scrape", {"url": url, "formats": ["markdown"], "timeout": 15_000}
        )
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(json.loads(stdout), {
            "requestedUrl": url, "url": "https://example.org/", "title": "Example",
            "markdown": markdown[:-1], "truncated": True,
        })

    def test_rejects_unsafe_inputs_before_request(self) -> None:
        for url in ("file:///etc/hosts", "https://user@example.com/", "http://127.0.0.1/", "http://[::1]/",
                    "http://foo.localhost./", "http://10.1.2.3", "https://example.com:70000", "https://example.com/\n"):
            with self.subTest(url=url), mock.patch.object(cli, "request_json") as request:
                status, stdout, _stderr = self.invoke("scrape", url)
                self.assertEqual((status, stdout), (2, ""))
                request.assert_not_called()
        self.assertEqual(self.invoke("doctor", "--endpoint", "http://firecrawl.example.org")[0], 2)

    def test_missing_service_and_failed_response_keep_stdout_empty(self) -> None:
        with mock.patch.object(cli.urllib.request, "build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.URLError("connection refused")
            status, stdout, stderr = self.invoke("doctor")
        self.assertEqual((status, stdout), (3, ""))
        self.assertIn("Open the standalone Firecrawl Local app", stderr)
        not_readable = {"success": True, "data": {"blocked": True, "markdown": "Blocked"}}
        with mock.patch.object(cli, "request_json", return_value=not_readable):
            self.assertEqual(self.invoke("scrape", "https://example.com/")[:2], (1, ""))

    def test_pi_extension_can_be_managed(self) -> None:
        status, stdout, _stderr = self.invoke("pi-extension")
        source = pathlib.Path(stdout.strip())
        self.assertEqual(status, 0)
        self.assertIn("firecrawl_scrape", source.read_text())
        with tempfile.TemporaryDirectory() as directory:
            directory_path = pathlib.Path(directory)
            self.assertFalse(pi.manage("status", source, directory_path)["enabled"])
            self.assertTrue(pi.manage("enable", source, directory_path)["enabled"])
            self.assertFalse(pi.manage("disable", source, directory_path)["enabled"])

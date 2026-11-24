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

    def test_setup_previews_without_installing(self) -> None:
        with mock.patch.dict(cli.os.environ, {}, clear=True), mock.patch.object(cli.standalone, "setup") as install:
            status, stdout, stderr = self.invoke("setup")
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["download"], cli.standalone.IMAGE)
        install.assert_not_called()

    def test_setup_preview_does_not_print_credentials_in_an_invalid_endpoint(self) -> None:
        with mock.patch.dict(cli.os.environ, {"MERE_FIRECRAWL_URL": "https://user:invalid-token@example.com"}):
            status, stdout, stderr = self.invoke("setup")
        self.assertEqual((status, stdout), (2, ""))
        self.assertNotIn("invalid-token", stderr)

    def test_setup_respects_a_configured_instance(self) -> None:
        endpoint = "https://firecrawl.example.org"
        with mock.patch.dict(cli.os.environ, {"MERE_FIRECRAWL_URL": endpoint}), mock.patch.object(
            cli, "request_json", return_value={"status": "ok", "version": "fixture"},
        ) as health, mock.patch.object(cli.standalone, "setup") as install:
            status, stdout, stderr = self.invoke("setup", "--yes")
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["status"], "configured")
        health.assert_called_once_with(endpoint, "/health")
        install.assert_not_called()

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

    def test_full_scrape_preserves_evidence_past_preview_cutoff(self) -> None:
        url = "https://example.com/retention"
        markdown = "Earlier documentation.\n" * 900 + "Public repository limit: 90 days."
        page = {"markdown": markdown, "metadata": {"url": url}}
        with mock.patch.object(cli, "request_json", return_value={"success": True, "data": page}):
            status, stdout, stderr = self.invoke("scrape", "--full", url)
        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["markdown"], markdown)
        self.assertFalse(json.loads(stdout)["truncated"])

    def test_scrape_does_not_cite_a_page_with_an_invalid_redirect(self) -> None:
        page = {"markdown": "A document.", "metadata": {"url": "http://127.0.0.1/"}}
        with mock.patch.object(cli, "request_json", return_value={"success": True, "data": page}):
            status, stdout, stderr = self.invoke("scrape", "https://example.com")
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("nonpublic page URL", stderr)

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

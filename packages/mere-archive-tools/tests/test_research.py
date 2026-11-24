from __future__ import annotations

import json
import pathlib
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from mere_archive_tools import cli, research

FIRST = "https://example.com/report?utm_source=test"
SAME_URL = "https://EXAMPLE.COM/report#top"
SAME_BODY = "https://example.org/reprinted"
FINAL = "https://example.com/final"


class ResearchTests(unittest.TestCase):
    def test_plan_is_private_and_does_not_contact_either_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "research"
            with patch.object(research, "plugin_json") as network, redirect_stdout(StringIO()):
                self.assertEqual(cli.main(["research", "--query", "flood mapping", "--output-dir", str(root),
                                           "--collection-only", "--dry-run"]), 0)
            network.assert_not_called()
            manifest = json.loads((root / "run.json").read_bytes())
            self.assertEqual(manifest["status"], "planned")
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((root / "run.json").stat().st_mode), 0o600)

    def test_deduplication_keeps_redirects_and_citations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)

            def plugin(_runtime: str, name: str, command: list[str]) -> research.JsonMap:
                if name == research.SEARCH_PLUGIN:
                    self.assertEqual(command, ["search", "--limit", "5", "--", "flood mapping"])
                    return {"query": "flood mapping", "results": [
                        {"url": FIRST, "title": "Primary", "engine": "example"},
                        {"url": SAME_URL, "title": "Same URL"},
                        {"url": SAME_BODY, "title": "Reprinted"},
                        {"url": "http://127.0.0.1/", "title": "Private"},
                        {"url": "https://example.net/missing", "title": "Fetch failure"},
                    ]}
                self.assertEqual(name, research.SCRAPE_PLUGIN)
                if command == ["manifest", "--json"]:
                    return {"capabilities": ["full-markdown"]}
                self.assertEqual(command[:3], ["scrape", "--full", "--"])
                url = command[-1]
                self.assertNotIn(url, {SAME_URL, "http://127.0.0.1/"})
                if url.endswith("/missing"):
                    raise research.ResearchError("fixture HTTP 404")
                return {
                    "requestedUrl": url, "url": FINAL if url == FIRST else url, "title": "[Unsafe](file:///private)",
                    "markdown": "A report about flood mapping.", "truncated": url == FIRST,
                }

            with patch.object(research, "plugin_json", side_effect=plugin) as network:
                result = research.collect("mere.run", root, "flood mapping", 5)
                self.assertEqual(network.call_count, 5)
                self.assertEqual(research.collect("mere.run", root, "flood mapping", 5), result)
                self.assertEqual(network.call_count, 5)
            sources = research.as_list(result["sources"], "test sources")
            self.assertEqual(len(sources), 1)
            source = research.as_map(sources[0], "test source")
            self.assertEqual(source["id"], "S01")
            self.assertEqual(source["url"], FINAL)
            self.assertEqual(source["requestedUrl"], FIRST)
            self.assertEqual(source["alternateUrls"], ["https://EXAMPLE.COM/report", SAME_BODY])
            self.assertTrue(source["truncated"])
            self.assertEqual([item["reason"] for item in research.as_list(result["skipped"], "skipped") if isinstance(item, dict)],
                             ["duplicate-url", "duplicate-source", "invalid-public-url", "fetch-failed"])
            citations = (root / "collection" / "citations.md").read_text()
            self.assertIn(f"[S01](<{FINAL}>)", citations)
            self.assertIn(r"\[Unsafe\]", citations)
            (root / "collection" / "sources" / "S01.md").write_text("changed")
            with self.assertRaisesRegex(research.ResearchError, "source changed"):
                research.collect("mere.run", root, "flood mapping", 5)

    def test_collect_keeps_long_evidence_and_gmail_citation_alias(self) -> None:
        canonical = "https://support.google.com/mail/answer/6584"
        desktop = canonical + "?hl=en&co=GENIE.Platform%3DDesktop"
        mobile = canonical + "?co=GENIE.Platform%3DAndroid"
        text = "Earlier documentation.\n" * 900 + "The administrator sets attachment sending limits."

        def plugin(_runtime: str, name: str, command: list[str]) -> research.JsonMap:
            if name == research.SEARCH_PLUGIN:
                return {"query": "Gmail attachment limits", "results": [
                    {"url": desktop}, {"url": canonical}, {"url": mobile},
                ]}
            if command == ["manifest", "--json"]:
                return {"capabilities": ["full-markdown"]}
            self.assertEqual(command[:3], ["scrape", "--full", "--"])
            url = command[-1]
            self.assertIn(url, {desktop, mobile})
            return {"url": url, "requestedUrl": url, "truncated": False,
                    "markdown": text if url == desktop else "Mobile documentation."}

        with tempfile.TemporaryDirectory() as directory, patch.object(research, "plugin_json", side_effect=plugin):
            root = pathlib.Path(directory)
            collected = research.collect("mere.run", root, "Gmail attachment limits", 3)
            first, second = research.as_list(collected["sources"], "test sources")
            self.assertEqual(research.as_map(first, "desktop source")["alternateUrls"], [canonical])
            self.assertFalse(research.as_map(first, "desktop source")["truncated"])
            self.assertEqual(research.as_map(second, "mobile source")["url"], mobile)
            self.assertEqual((root / "collection/sources/S01.md").read_text(), text + "\n")
            self.assertNotEqual(research.comparison_url(canonical), research.comparison_url(canonical + "?version=2"))

    def test_resume_after_index_failure_uses_saved_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "research"
            receipt = root / "run.json"

            def plugin(_runtime: str, name: str, arguments: list[str]) -> research.JsonMap:
                if name == research.SEARCH_PLUGIN:
                    return {"query": "flood mapping", "results": [{"url": FINAL}]}
                if arguments == ["manifest", "--json"]:
                    return {"capabilities": ["markdown"]}
                self.assertEqual(arguments, ["scrape", "--", FINAL])
                return {"url": FINAL, "requestedUrl": FINAL, "markdown": "Local snapshot."}

            with patch.object(research, "plugin_json", side_effect=plugin) as network, \
                    patch.object(cli, "index_research_collection", side_effect=research.ResearchError("missing model")), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(cli.main(["research", "--query", "flood mapping", "--output-dir", str(root)]), 1)
                self.assertEqual(network.call_count, 3)
            self.assertEqual(json.loads(receipt.read_bytes())["status"], "failed")
            with patch.object(research, "plugin_json") as network, \
                    patch.object(cli, "index_research_collection", return_value={"database": "archive.sqlite3"}), \
                    redirect_stdout(StringIO()):
                self.assertEqual(cli.main(["resume", str(receipt)]), 0)
                self.assertEqual(cli.main(["run", str(receipt)]), 0)
            network.assert_not_called()
            result = json.loads(receipt.read_bytes())
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["artifacts"]["database"], "archive.sqlite3")


if __name__ == "__main__":
    unittest.main()

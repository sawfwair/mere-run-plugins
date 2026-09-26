from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mere_searxng_search import cli, pi


class PiTests(unittest.TestCase):
    def test_resolves_mere_run_agent_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            extension = pathlib.Path(temporary) / ".pi" / "agent" / "extensions" / "mere-run-local-provider.ts"
            response = subprocess.CompletedProcess([], 0, json.dumps({"provider": {"extensionPath": str(extension)}}), "")
            with patch.object(pi.shutil, "which", return_value="/usr/local/bin/mere.run"), patch.object(pi.subprocess, "run", return_value=response) as run:
                self.assertEqual(pi.agent_extension_directory(), extension.parent)
            run.assert_called_once_with(["/usr/local/bin/mere.run", "agent", "status", "--json"],
                                        capture_output=True, text=True, timeout=15, check=True)

    def test_enable_status_disable_and_preserve_foreign_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary) / "extensions"
            source = cli.pi_extension_path()
            self.assertTrue(pi.manage("enable", source, directory)["enabled"])
            self.assertTrue(pi.manage("status", source, directory)["enabled"])
            link = directory / pi.LINK_NAME
            self.assertTrue(link.is_symlink())
            self.assertFalse(pi.manage("disable", source, directory)["enabled"])
            self.assertFalse(link.exists())
            link.write_text("user extension")
            with self.assertRaisesRegex(pi.PiError, "does not own"):
                pi.manage("enable", source, directory)
            self.assertEqual(link.read_text(), "user extension")


if __name__ == "__main__":
    unittest.main()

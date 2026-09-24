from __future__ import annotations

import pathlib
import shutil
import tarfile
import tempfile
import unittest
from unittest import mock

from mere_computer_use import driver_setup


class DriverSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.app = self.root / "Applications/CuaDriver.app"
        self.app.parent.mkdir()
        self.link = self.root / "bin/cua-driver"
        for patcher in (
            mock.patch.object(driver_setup, "APP", self.app),
            mock.patch.object(driver_setup, "BIN_LINK", self.link),
            mock.patch.object(driver_setup.sys, "platform", "darwin"),
            mock.patch.object(driver_setup.platform, "machine", return_value="arm64"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_preview_does_not_download_or_install(self) -> None:
        with mock.patch.object(driver_setup, "download") as download:
            result = driver_setup.setup(False)
        self.assertEqual(result["status"], "ready-to-install")
        self.assertEqual(result["sha256"], driver_setup.SHA256)
        download.assert_not_called()
        self.assertFalse(self.app.exists())

    def test_installs_only_verified_app_and_links_binary(self) -> None:
        def fake_download(archive: pathlib.Path) -> None:
            source = self.root / "source" / driver_setup.ARCHIVE.removesuffix(".tar.gz") / "CuaDriver.app"
            binary = source / "Contents/MacOS/cua-driver"
            binary.parent.mkdir(parents=True)
            binary.write_text("verified fixture", encoding="utf-8")
            with tarfile.open(archive, "w:gz") as output:
                output.add(source.parent, arcname=source.parent.name)

        def fake_checked(command: list[str]) -> str:
            if command[0] == "ditto":
                shutil.copytree(command[1], command[2])
            return ""

        with mock.patch.object(driver_setup, "download", side_effect=fake_download), \
             mock.patch.object(driver_setup, "verify_app") as verify, \
             mock.patch.object(driver_setup, "checked", side_effect=fake_checked), \
             mock.patch.object(driver_setup.os, "access", return_value=True):
            result = driver_setup.setup(True)
        self.assertEqual(result["status"], "installed")
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(self.link.resolve(), (self.app / "Contents/MacOS/cua-driver").resolve())

    def test_existing_app_is_preserved_and_wrong_link_is_rejected(self) -> None:
        binary = self.app / "Contents/MacOS/cua-driver"
        binary.parent.mkdir(parents=True)
        binary.write_text("fixture", encoding="utf-8")
        with mock.patch.object(driver_setup, "verify_app"), \
             mock.patch.object(driver_setup, "checked", return_value="cua-driver 0.29.0\n"):
            self.assertEqual(driver_setup.setup(False)["status"], "needs-link")
            self.link.parent.mkdir()
            self.link.write_text("other command", encoding="utf-8")
            with self.assertRaises(driver_setup.SetupError):
                driver_setup.setup(True)
        self.assertTrue(binary.exists())


if __name__ == "__main__":
    unittest.main()

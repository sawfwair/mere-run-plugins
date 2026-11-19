from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from mere_firecrawl_local import standalone


class StandaloneTests(unittest.TestCase):
    def test_running_instance_avoids_installation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            applications = pathlib.Path(directory) / "unused"
            with mock.patch.object(standalone, "supported_mac", return_value=True), mock.patch.object(
                standalone, "local_version", return_value="local-version",
            ):
                result = standalone.setup(applications)
            self.assertEqual(result["status"], "reused")
            self.assertEqual(result["version"], "local-version")
            self.assertFalse(applications.exists())

    def test_conflicting_service_leaves_applications_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            applications = pathlib.Path(directory) / "unused"
            with mock.patch.object(standalone, "supported_mac", return_value=True), mock.patch.object(
                standalone, "local_version", side_effect=standalone.SetupError("Port 3002 is in use"),
            ), self.assertRaisesRegex(standalone.SetupError, "Port 3002"):
                standalone.setup(applications)
            self.assertFalse(applications.exists())

    def test_existing_app_is_verified_before_launch_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            applications = pathlib.Path(directory)
            app = applications / standalone.APP_NAME
            app.mkdir()
            with mock.patch.object(standalone, "supported_mac", return_value=True), mock.patch.object(
                standalone, "local_version", return_value=None,
            ), mock.patch.object(standalone, "verify_app") as verify, mock.patch.object(
                standalone, "install_app",
            ) as download, mock.patch.object(standalone, "open_app") as launch, mock.patch.object(
                standalone, "wait_for_app", return_value="local-version",
            ):
                result = standalone.setup(applications)
            verify.assert_called_once_with(app)
            launch.assert_called_once_with(app)
            download.assert_not_called()
            self.assertEqual(result["status"], "started")
            self.assertEqual(result["application"], str(app))

    def test_install_failure_does_not_launch_firecrawl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            applications = pathlib.Path(directory)
            with mock.patch.object(standalone, "supported_mac", return_value=True), mock.patch.object(
                standalone, "local_version", return_value=None,
            ), mock.patch.object(standalone, "SYSTEM_APP", applications / "nonexistent"), mock.patch.object(
                standalone, "install_app", side_effect=standalone.SetupError("Invalid image"),
            ), mock.patch.object(standalone, "open_app") as launch, self.assertRaisesRegex(
                standalone.SetupError, "Invalid image",
            ):
                standalone.setup(applications)
            launch.assert_not_called()

    def test_wrong_checksum_fails_before_platform_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = pathlib.Path(directory) / "example.dmg"
            image.write_bytes(b"modified disk image")
            with mock.patch.object(standalone, "run_tool") as run, self.assertRaisesRegex(
                standalone.SetupError, "published checksum",
            ):
                standalone.verify_image(image)
            run.assert_not_called()

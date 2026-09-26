from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mere_searxng_search import instance


class FakeDocker:
    def __init__(self, directory: pathlib.Path) -> None:
        self.directory = directory
        self.exists = False
        self.running = False
        self.wrong_mount = False
        self.wrong_owner = False
        self.commands: list[list[str]] = []

    def __call__(self, record: instance.JsonMap, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        _ = timeout
        self.commands.append(args)
        if args[:2] == ["context", "inspect"]:
            return subprocess.CompletedProcess(args, 0, "unix:///var/run/docker.sock\n", "")
        if args[:2] == ["context", "show"]:
            return subprocess.CompletedProcess(args, 0, "default\n", "")
        if args[:2] == ["container", "inspect"]:
            if not self.exists:
                return subprocess.CompletedProcess(args, 1, "", "No such object")
            labels = {instance.OWNER_LABEL: "other" if self.wrong_owner else "mere-searxng-search",
                      instance.STATE_LABEL: record["instanceId"]}
            payload = {"Config": {"Labels": labels}, "State": {"Running": self.running}}
            return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")
        if args[:2] == ["image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, "sha256:exampleimage\n", "")
        if args[:2] == ["container", "exec"]:
            settings = (self.directory / "config" / "settings.yml").read_text()
            return subprocess.CompletedProcess(args, 0, "wrong settings" if self.wrong_mount else settings, "")
        if args[0] == "run":
            self.exists = True
            self.running = True
        elif args[:2] == ["container", "start"]:
            self.running = True
        elif args[:2] == ["container", "stop"]:
            self.running = False
        elif args[:2] == ["container", "rm"]:
            self.exists = False
        return subprocess.CompletedProcess(args, 0, "ok\n", "")


class InstanceTests(unittest.TestCase):
    def test_install_stop_start_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            directory = pathlib.Path(root) / "instance"
            fake = FakeDocker(directory)
            with patch.object(instance, "docker", side_effect=fake), patch.object(instance, "wait_ready"):
                planned = instance.plan(directory, 18888, "colima", instance.DEFAULT_IMAGE)
                self.assertEqual(planned["status"], "planned")
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                settings = directory / "config" / "settings.yml"
                self.assertEqual(settings.stat().st_mode & 0o777, 0o600)
                self.assertIn("    - json", settings.read_text())
                self.assertNotIn("secret_key", json.dumps(planned))
                record = instance.install(directory, 18888, "colima", instance.DEFAULT_IMAGE)
                self.assertEqual(record["status"], "running")
                run = next(command for command in fake.commands if command[0] == "run")
                self.assertIn("127.0.0.1:18888:8080", run)
                self.assertIn("sha256:exampleimage", run)
                self.assertTrue(instance.status(directory)["running"])
                self.assertEqual(instance.stop(directory)["status"], "stopped")
                self.assertFalse(instance.status(directory)["running"])
                self.assertEqual(instance.start(directory)["status"], "running")
                self.assertEqual(instance.uninstall(directory)["status"], "removed")
                self.assertFalse(fake.exists)
                self.assertTrue(settings.exists())
                self.assertIsNone(instance.instance_url(directory))
                self.assertTrue(instance.uninstall(directory, purge=True)["dataPurged"])
                self.assertFalse(directory.exists())

    def test_wrong_mount_stops_and_removes_container(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            directory = pathlib.Path(root) / "instance"
            fake = FakeDocker(directory)
            fake.wrong_mount = True
            with patch.object(instance, "docker", side_effect=fake), patch.object(instance, "wait_ready"):
                with self.assertRaisesRegex(instance.InstanceError, "shared with Docker"):
                    instance.install(directory, 18888, None, instance.DEFAULT_IMAGE)
            self.assertFalse(fake.exists)
            self.assertEqual(instance.load_state(directory)["status"], "failed")

    def test_unmanaged_container_is_never_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            directory = pathlib.Path(root) / "instance"
            instance.plan(directory, 18888, None, instance.DEFAULT_IMAGE)
            record = instance.load_state(directory)
            record["imageId"] = "sha256:exampleimage"
            instance.write_state(directory, record)
            fake = FakeDocker(directory)
            fake.exists = True
            fake.running = True
            fake.wrong_owner = True
            with patch.object(instance, "docker", side_effect=fake):
                with self.assertRaisesRegex(instance.InstanceError, "unmanaged container"):
                    instance.uninstall(directory)
            self.assertFalse(any(command[:2] == ["container", "stop"] for command in fake.commands))
            self.assertFalse(any(command[:2] == ["container", "rm"] for command in fake.commands))

    def test_plan_validation(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = pathlib.Path(root)
            with self.assertRaisesRegex(instance.InstanceError, "port"):
                instance.plan(base / "low", 80, None, instance.DEFAULT_IMAGE)
            with self.assertRaisesRegex(instance.InstanceError, "official"):
                instance.plan(base / "image", 18888, None, "example.org/other:latest")

    def test_remote_docker_context_is_rejected(self) -> None:
        record: instance.JsonMap = {"dockerContext": "remote"}
        with patch.object(instance, "docker", return_value=subprocess.CompletedProcess([], 0, "ssh://example.org\n", "")):
            with self.assertRaisesRegex(instance.InstanceError, "local Unix socket"):
                instance.require_local_docker(record)


if __name__ == "__main__":
    unittest.main()

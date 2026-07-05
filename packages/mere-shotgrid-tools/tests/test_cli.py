from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any

from mere_shotgrid_tools import cli


class FakeShotGrid:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.updated: list[tuple[str, int, dict[str, Any], dict[str, Any]]] = []
        self.uploaded: list[tuple[str, int, str, dict[str, Any]]] = []
        self.thumbnails: list[tuple[str, int, str]] = []
        self.deleted: list[tuple[str, int]] = []
        self.next_id = 1000

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def find_one(self, entity_type: str, filters: list[list[Any]], fields: list[str]) -> dict[str, Any] | None:
        if entity_type == "Project":
            return {"type": "Project", "id": 123, "name": "Demo"}
        if entity_type == "Shot":
            return {"type": "Shot", "id": 456, "code": "shot010"}
        if entity_type == "Task":
            return {"type": "Task", "id": 789, "content": "Animation"}
        if entity_type == "Playlist":
            return {"type": "Playlist", "id": 321, "code": "Daily"}
        if entity_type == "Version":
            return {"type": "Version", "id": filters[0][2], "code": "shot010_v003", "sg_status_list": "rev"}
        return None

    def find(self, entity_type: str, filters: list[list[Any]], fields: list[str], limit: int = 50) -> list[dict[str, Any]]:
        self.updated.append(("find", 0, {"entity_type": entity_type, "filters": filters, "fields": fields, "limit": limit}, {}))
        return [
            {
                "type": "Task",
                "id": 789,
                "content": "Animation",
                "entity": {"type": "Shot", "id": 456, "name": "shot010"},
                "project": {"type": "Project", "id": 123},
                "sg_status_list": "rdy",
                "description": "Make the review pass.",
            }
        ]

    def create(self, entity_type: str, data: dict[str, Any]) -> dict[str, Any]:
        self.created.append((entity_type, data))
        return {"type": entity_type, "id": self._id(), **({"code": data.get("code")} if data.get("code") else {})}

    def update(self, entity_type: str, entity_id: int, data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        self.updated.append((entity_type, entity_id, data, kwargs))
        return {"type": entity_type, "id": entity_id, **data}

    def upload(self, entity_type: str, entity_id: int, path: str, **kwargs: Any) -> int:
        self.uploaded.append((entity_type, entity_id, path, kwargs))
        return self._id()

    def upload_thumbnail(self, entity_type: str, entity_id: int, path: str) -> int:
        self.thumbnails.append((entity_type, entity_id, path))
        return self._id()

    def delete(self, entity_type: str, entity_id: int) -> bool:
        self.deleted.append((entity_type, entity_id))
        return True


class MereShotGridToolsTests(unittest.TestCase):
    def test_manifest_has_required_commands(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        self.assertEqual(manifest["name"], "mere-shotgrid-tools")
        names = {command["name"] for command in manifest["commands"]}
        self.assertTrue({"manifest", "doctor", "plan", "run", "resume", "cleanup", "publish", "pull-tasks"}.issubset(names))
        self.assertEqual(manifest["security"]["usesUserCredentials"], True)
        self.assertEqual(manifest["security"]["storesSecrets"], False)
        self.assertEqual(manifest["security"]["cleanupDefault"], "none")

    def test_plan_writes_publish_manifest_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "review.mov"
            thumbnail = root / "poster.png"
            artifact.write_bytes(b"fake movie")
            thumbnail.write_bytes(b"fake thumbnail")
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan",
                    "--project-id",
                    "123",
                    "--entity-type",
                    "Shot",
                    "--entity-id",
                    "456",
                    "--task-id",
                    "789",
                    "--artifact",
                    str(artifact),
                    "--thumbnail",
                    str(thumbnail),
                    "--note",
                    "Ready for review.",
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "unit-plan",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["shotgrid"]["version"]["code"], "Shot_456_unit-plan")
            self.assertEqual(payload["shotgrid"]["uploads"][0]["fieldName"], "sg_uploaded_movie")
            self.assertTrue((root / "out" / "run.json").is_file())
            serialized = json.dumps(payload)
            self.assertNotIn("api_key", serialized)
            self.assertNotIn("password", serialized)

    def test_execute_manifest_creates_version_uploads_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "review.mov"
            thumbnail = root / "poster.png"
            artifact.write_bytes(b"fake movie")
            thumbnail.write_bytes(b"fake thumbnail")
            args = cli.build_parser().parse_args([
                "plan",
                "--project-id",
                "123",
                "--entity-type",
                "Shot",
                "--entity-id",
                "456",
                "--task-id",
                "789",
                "--playlist-id",
                "321",
                "--artifact",
                str(artifact),
                "--thumbnail",
                str(thumbnail),
                "--task-status",
                "rev",
                "--note",
                "Ready for review.",
                "--output-dir",
                str(root / "out"),
                "--run-id",
                "unit-execute",
            ])
            args = cli.normalize_paths(args)
            manifest = cli.make_publish_manifest(args)
            manifest_path = root / "out" / "run.json"
            cli.write_json(manifest_path, manifest)
            fake = FakeShotGrid()
            result = cli.execute_manifest(manifest_path, manifest, sg=fake)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(fake.created[0][0], "Version")
            self.assertEqual(fake.created[1][0], "Note")
            self.assertEqual(fake.uploaded[0][0], "Version")
            self.assertEqual(fake.uploaded[0][3]["field_name"], "sg_uploaded_movie")
            self.assertEqual(fake.thumbnails[0][0], "Version")
            self.assertIn(("Playlist", 321, {"versions": [{"type": "Version", "id": 1001}]}, {"multi_entity_update_modes": {"versions": "add"}}), fake.updated)
            self.assertIn(("Task", 789, {"sg_status_list": "rev"}, {}), fake.updated)
            persisted = json.loads(manifest_path.read_text())
            self.assertEqual(persisted["status"], "succeeded")
            self.assertEqual(persisted["shotgrid"]["result"]["version"]["type"], "Version")

    def test_cleanup_defaults_to_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest_path = root / "run.json"
            cli.write_json(manifest_path, {
                "contractVersion": "mere.run/plugin-run.v1",
                "runId": "unit-cleanup",
                "plugin": {"name": "mere-shotgrid-tools", "version": "0.1.0"},
                "recipe": {"id": "shotgrid-version-publish", "family": "production-tracking"},
                "status": "succeeded",
                "createdAt": "2026-07-05T00:00:00+00:00",
                "dataset": {"path": str(root), "pairCount": 1},
                "command": ["mere-shotgrid-tools", "run", str(manifest_path)],
                "artifacts": {},
                "shotgrid": {"result": {"created": [{"type": "Version", "id": 1001}]}},
                "cleanup": {"default": "none", "status": "not-started"},
            })
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["cleanup", str(manifest_path)])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["cleanup"]["status"], "skipped")

    def test_pull_tasks_writes_jsonl_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            args = cli.build_parser().parse_args([
                "pull-tasks",
                "--project-id",
                "123",
                "--assignee-id",
                "42",
                "--status",
                "rdy",
                "--tool",
                "shot-kit",
                "--output",
                str(root / "jobs.jsonl"),
            ])
            args = cli.normalize_paths(args)
            payload = cli.pull_tasks(args, sg=FakeShotGrid())
            self.assertEqual(payload["count"], 1)
            lines = (root / "jobs.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            job = json.loads(lines[0])
            self.assertEqual(job["tool"], "shot-kit")
            self.assertEqual(job["inputs"]["shotgrid"]["task"], {"type": "Task", "id": 789})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import pathlib
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any
from unittest import mock

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

    def find_one(self, entity_type: str, filters: list[list[Any]], _fields: list[str]) -> dict[str, Any] | None:
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

    def test_config_redaction_and_key_value_parsing(self) -> None:
        args = cli.build_parser().parse_args([
            "doctor",
            "--site-url",
            "https://studio.shotgrid.autodesk.com",
            "--script-name",
            "mere",
            "--api-key",
            "secret",
            "--allow-missing-credentials",
        ])
        config = cli.config_from_args(args)
        redacted = cli.redacted_config(config)
        self.assertEqual(redacted["siteUrl"], "https://studio.shotgrid.autodesk.com")
        self.assertEqual(redacted["authMode"], "script")
        self.assertTrue(redacted["hasApiKey"])
        self.assertEqual(cli.parse_key_value(["sg_status_list=rev", "sg_cut_order=12"]), {"sg_status_list": "rev", "sg_cut_order": 12})
        with self.assertRaises(cli.PluginError):
            cli.parse_key_value(["missing-equals"])
        with self.assertRaises(cli.PluginError):
            cli.parse_key_value(["=empty"])

    def test_json_boundary_helpers_and_config_validation(self) -> None:
        with self.assertRaises(cli.PluginError):
            cli.as_map([], "payload")
        with self.assertRaises(cli.PluginError):
            cli.as_list({}, "items")
        with self.assertRaises(cli.PluginError):
            cli.string_field({"name": 1}, "name", "payload")
        with self.assertRaises(cli.PluginError):
            cli.int_value(True, "count")
        self.assertIsNone(cli.int_or_none("not-an-int"))
        self.assertIsNone(cli.ref_from_payload({"type": "Shot"}))
        with self.assertRaises(cli.PluginError):
            cli.validate_config(cli.ShotGridConfig(None, None, None, None, None))
        with self.assertRaises(cli.PluginError):
            cli.validate_config(cli.ShotGridConfig("https://example.shotgrid.autodesk.com", None, None, None, None))

    def test_doctor_can_report_missing_credentials_as_allowed(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            exit_code = cli.main(["doctor", "--allow-missing-credentials"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["checks"][-1]["ok"])

    def test_doctor_live_and_manifest_warning_paths(self) -> None:
        stdout = StringIO()
        with (
            redirect_stdout(stdout),
            redirect_stderr(StringIO()),
            mock.patch.dict("sys.modules", {"shotgun_api3": types.SimpleNamespace(__version__="test")}),
            mock.patch("mere_shotgrid_tools.cli.make_shotgrid_client", return_value=FakeShotGrid()),
        ):
            exit_code = cli.main([
                "doctor",
                "--site-url",
                "https://studio.shotgrid.autodesk.com",
                "--script-name",
                "mere",
                "--api-key",
                "secret",
                "--live",
                "--project-id",
                "123",
            ])
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(any(check["name"] == "live-api" for check in payload["checks"]))

        stderr = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            exit_code = cli.main(["manifest"])
        self.assertEqual(exit_code, 0)
        self.assertIn("manifest output is JSON", stderr.getvalue())

    def test_collects_artifacts_from_source_manifest_and_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            direct = root / "direct.mov"
            bundled = root / "bundled.png"
            manifest_file = root / "source-run.json"
            bundle_file = root / "bundle.json"
            direct.write_bytes(b"movie")
            bundled.write_bytes(b"image")
            manifest_file.write_text(json.dumps({
                "artifacts": {
                    "items": [{"path": str(direct)}],
                    "files": [str(direct)],
                    "thumbnail": {"path": str(bundled)},
                }
            }))
            bundle_file.write_text(json.dumps({"files": [{"path": str(bundled)}, str(direct)]}))
            args = cli.build_parser().parse_args([
                "plan",
                "--project-id",
                "123",
                "--source-run-manifest",
                str(manifest_file),
                "--artifact-bundle",
                str(bundle_file),
                "--artifact",
                str(direct),
                "--output-dir",
                str(root / "out"),
                "--run-id",
                "collect-test",
            ])
            args = cli.normalize_paths(args)
            items = cli.collect_artifacts(args)
            self.assertEqual([pathlib.Path(item["path"]).name for item in items], ["direct.mov", "bundled.png"])
            self.assertEqual(cli.first_image_artifact(items), bundled.resolve())
            self.assertEqual(cli.artifact_item(root / "missing.mov", allow_missing=True)["missing"], True)
            with self.assertRaises(cli.PluginError):
                cli.artifact_item(root / "missing.mov")

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

    def test_resolve_branches_and_missing_records(self) -> None:
        class FallbackShotGrid(FakeShotGrid):
            def __init__(self) -> None:
                super().__init__()
                self.project_calls = 0

            def find_one(self, entity_type: str, filters: list[list[Any]], _fields: list[str]) -> dict[str, Any] | None:
                if entity_type == "Project":
                    self.project_calls += 1
                    if filters[0][0] == "code":
                        return None
                    return {"type": "Project", "id": 222, "name": "By Name"}
                if entity_type == "Asset":
                    return {"type": "Asset", "id": 333, "code": filters[1][2]}
                if entity_type == "Playlist":
                    return None
                return super().find_one(entity_type, filters, _fields)

        fake = FallbackShotGrid()
        project = cli.resolve_project(fake, {"type": "Project", "code": "Demo"})
        self.assertEqual(project["id"], 222)
        self.assertEqual(fake.project_calls, 2)
        entity = cli.resolve_linked_entity(fake, project, {"type": "Asset", "code": "hero"})
        self.assertEqual(entity, {"type": "Asset", "id": 333})
        task = cli.resolve_task(fake, project, entity, {"type": "Task", "name": "Animation"})
        self.assertEqual(task, {"type": "Task", "id": 789})
        playlist, created = cli.resolve_playlist(fake, project, {"type": "Playlist", "code": "New Daily", "createIfMissing": True})
        self.assertTrue(created)
        self.assertEqual(playlist["type"], "Playlist")
        with self.assertRaises(cli.PluginError):
            cli.resolve_playlist(fake, project, {"type": "Playlist", "code": "Missing", "createIfMissing": False})

    def test_execute_manifest_wraps_unexpected_shotgrid_errors(self) -> None:
        class BrokenShotGrid(FakeShotGrid):
            def create(self, _entity_type: str, _data: dict[str, Any]) -> dict[str, Any]:
                raise RuntimeError("provider exploded")

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "review.mov"
            artifact.write_bytes(b"movie")
            args = cli.build_parser().parse_args([
                "plan",
                "--project-id",
                "123",
                "--entity-type",
                "Shot",
                "--entity-id",
                "456",
                "--artifact",
                str(artifact),
                "--output-dir",
                str(root / "out"),
                "--run-id",
                "broken-provider",
            ])
            args = cli.normalize_paths(args)
            manifest = cli.make_publish_manifest(args)
            manifest_path = root / "out" / "run.json"
            cli.write_json(manifest_path, manifest)
            with self.assertRaises(cli.PluginError) as error:
                cli.execute_manifest(manifest_path, manifest, sg=BrokenShotGrid())
            self.assertIn("ShotGrid publish failed", str(error.exception))
            self.assertEqual(json.loads(manifest_path.read_text())["status"], "failed")

    def test_publish_and_run_dry_run_do_not_create_remote_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "review.mov"
            artifact.write_bytes(b"fake movie")
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "publish",
                    "--project-id",
                    "123",
                    "--entity-type",
                    "Shot",
                    "--entity-id",
                    "456",
                    "--artifact",
                    str(artifact),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "unit-publish-dry-run",
                    "--dry-run",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "planned")

            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["run", str(root / "out" / "run.json"), "--dry-run"])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["runId"], "unit-publish-dry-run")

    def test_publish_and_run_execute_through_command_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "review.mov"
            artifact.write_bytes(b"fake movie")
            with (
                mock.patch("mere_shotgrid_tools.cli.config_from_args", return_value=cli.ShotGridConfig(None, None, None, None, None)),
                mock.patch("mere_shotgrid_tools.cli.execute_manifest", side_effect=lambda _path, manifest, **_kwargs: {**manifest, "status": "succeeded"}) as execute,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                exit_code = cli.main([
                    "publish",
                    "--project-id",
                    "123",
                    "--artifact",
                    str(artifact),
                    "--output-dir",
                    str(root / "out"),
                    "--run-id",
                    "publish-execute",
                ])
            self.assertEqual(exit_code, 0)
            self.assertEqual(execute.call_count, 1)

            with (
                mock.patch("mere_shotgrid_tools.cli.config_from_args", return_value=cli.ShotGridConfig(None, None, None, None, None)),
                mock.patch("mere_shotgrid_tools.cli.execute_manifest", side_effect=lambda _path, manifest, **_kwargs: {**manifest, "status": "succeeded"}) as execute,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                exit_code = cli.main(["run", str(root / "out" / "run.json")])
            self.assertEqual(exit_code, 0)
            self.assertEqual(execute.call_count, 1)

    def test_upload_retry_and_cleanup_delete_only_created_records(self) -> None:
        class FlakyShotGrid(FakeShotGrid):
            def __init__(self) -> None:
                super().__init__()
                self.attempts = 0

            def upload(self, entity_type: str, entity_id: int, path: str, **kwargs: Any) -> int:
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("transient")
                return super().upload(entity_type, entity_id, path, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            artifact = root / "review.mov"
            artifact.write_bytes(b"fake movie")
            fake = FlakyShotGrid()
            upload_id = cli.upload_with_retry(fake, entity_type="Version", entity_id=1001, item={"path": str(artifact)})
            self.assertGreater(upload_id, 1000)
            self.assertEqual(fake.attempts, 2)

            manifest_path = root / "run.json"
            manifest = {
                "runId": "cleanup-created",
                "status": "succeeded",
                "shotgrid": {"result": {"created": [{"type": "Note", "id": 1002}, {"type": "Version", "id": 1001}]}},
                "cleanup": {"default": "none", "status": "not-started"},
            }
            cli.write_json(manifest_path, manifest)
            result = cli.cleanup_created_records(manifest_path, manifest, fake)
            self.assertEqual(result["cleanup"]["status"], "succeeded")
            self.assertEqual(fake.deleted, [("Version", 1001), ("Note", 1002)])

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

    def test_cleanup_requires_matching_confirmation_before_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest_path = root / "run.json"
            cli.write_json(manifest_path, {
                "runId": "unit-cleanup",
                "status": "succeeded",
                "shotgrid": {"result": {"created": [{"type": "Version", "id": 1001}]}},
                "cleanup": {"default": "none", "status": "not-started"},
            })
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "cleanup",
                    str(manifest_path),
                    "--delete-created-records",
                    "--confirm-run-id",
                    "wrong",
                ])
            self.assertEqual(exit_code, 2)

    def test_resume_live_fetches_version_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest_path = root / "run.json"
            cli.write_json(manifest_path, {
                "runId": "resume-live",
                "status": "succeeded",
                "shotgrid": {"result": {"version": {"type": "Version", "id": 1001}}},
                "cleanup": {"default": "none", "status": "not-started"},
            })
            stdout = StringIO()
            with (
                mock.patch("mere_shotgrid_tools.cli.make_shotgrid_client", return_value=FakeShotGrid()),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = cli.main([
                    "resume",
                    str(manifest_path),
                    "--site-url",
                    "https://studio.shotgrid.autodesk.com",
                    "--script-name",
                    "mere",
                    "--api-key",
                    "secret",
                    "--live",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["liveVersion"]["id"], 1001)

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

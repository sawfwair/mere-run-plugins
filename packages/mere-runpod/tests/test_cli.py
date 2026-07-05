from __future__ import annotations

import json
import pathlib
import tarfile
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from mere_runpod import cli


def write_dataset(path: pathlib.Path, count: int) -> None:
    path.mkdir()
    for index in range(1, count + 1):
        stem = f"{index:03d}"
        (path / f"{stem}.png").write_bytes(b"fake")
        (path / f"{stem}.txt").write_text("testtrigger, a test image\n")


def write_tar(path: pathlib.Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            source = path.parent / name.replace("/", "_")
            source.write_bytes(data)
            archive.add(source, arcname=name)


class FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class MereRunPodCLITests(unittest.TestCase):
    def test_manifest_has_required_commands(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        names = {command["name"] for command in manifest["commands"]}
        self.assertTrue({"manifest", "doctor", "volume", "plan", "run", "resume", "cleanup"}.issubset(names))
        self.assertEqual(manifest["security"]["cleanupDefault"], "terminate")

    def test_dataset_info_requires_captions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dataset = pathlib.Path(tmp)
            (dataset / "001.png").write_bytes(b"fake")
            with self.assertRaises(cli.PluginError):
                cli.dataset_info(dataset)

    def test_plan_writes_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            dataset = root / "dataset"
            output = root / "run"
            write_dataset(dataset, 12)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan",
                    "--recipe",
                    "klein-character-lora",
                    "--data",
                    str(dataset),
                    "--output",
                    str(output),
                    "--run-id",
                    "unit-test-run",
                ])
            self.assertEqual(exit_code, 0)
            manifest_path = output / "run.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["runId"], "unit-test-run")
            self.assertEqual(manifest["dataset"]["pairCount"], 12)
            self.assertEqual(manifest["recipe"]["id"], "klein-character-lora")
            self.assertEqual(manifest["recipe"]["trainModel"], "image-klein-base-9b")
            self.assertEqual(manifest["recipe"]["applyModel"], "image-klein-9b")
            self.assertIn("--rank", manifest["command"])
            self.assertIn("--alpha", manifest["command"])

    def test_plan_records_network_volume_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            dataset = root / "dataset"
            output = root / "run"
            write_dataset(dataset, 12)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan",
                    "--recipe",
                    "klein-character-lora",
                    "--data",
                    str(dataset),
                    "--output",
                    str(output),
                    "--run-id",
                    "volume-plan",
                    "--network-volume-id",
                    "volabc123",
                ])
            self.assertEqual(exit_code, 0)
            manifest = json.loads((output / "run.json").read_text())
            self.assertEqual(manifest["remote"]["networkVolumeId"], "volabc123")

    def test_build_pack_remote_path_is_sha_keyed_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            dataset = root / "dataset"
            output = root / "run"
            build_pack = root / "mere-run-linux-cuda.tar.gz"
            write_dataset(dataset, 12)
            write_tar(build_pack, {"mere-run-linux/mere.run": b"#!/usr/bin/env bash\n"})
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan",
                    "--recipe",
                    "klein-character-lora",
                    "--data",
                    str(dataset),
                    "--output",
                    str(output),
                    "--run-id",
                    "build-pack-plan",
                    "--build-pack",
                    str(build_pack),
                ])
            self.assertEqual(exit_code, 0)
            manifest = json.loads((output / "run.json").read_text())
            self.assertTrue(manifest["buildPack"]["remotePath"].startswith("/workspace/mere-runpod/build-packs/"))
            self.assertIn(manifest["buildPack"]["sha256"].split(":", 1)[1], manifest["buildPack"]["remotePath"])

    def test_plan_enforces_recipe_minimum_dataset_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            dataset = root / "dataset"
            output = root / "run"
            write_dataset(dataset, 1)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan",
                    "--recipe",
                    "klein-style-lora",
                    "--data",
                    str(dataset),
                    "--output",
                    str(output),
                    "--run-id",
                    "too-small",
                ])
            self.assertEqual(exit_code, 2)

    def test_run_id_rejects_path_segments(self) -> None:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            exit_code = cli.main([
                "plan",
                "--recipe",
                "klein-style-lora",
                "--data",
                "/tmp",
                "--output",
                "/tmp/out",
                "--run-id",
                "../../oops",
            ])
        self.assertEqual(exit_code, 2)

    def test_run_process_routes_child_stdout_to_stderr(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout), mock.patch("mere_runpod.cli.eprint") as eprint:
            completed = cli.run_process(["bash", "-lc", "echo child-output"])
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(stdout.getvalue(), "")
        eprint.assert_any_call("child-output")

    def test_graphql_returns_data_and_wraps_provider_errors(self) -> None:
        with mock.patch(
            "mere_runpod.cli.urllib.request.urlopen",
            return_value=FakeHTTPResponse('{"data":{"pod":{"id":"pod123"}}}'),
        ):
            self.assertEqual(cli.graphql("api", "query")["pod"]["id"], "pod123")

        with mock.patch(
            "mere_runpod.cli.urllib.request.urlopen",
            return_value=FakeHTTPResponse('{"errors":[{"message":"denied"}]}'),
        ):
            with self.assertRaises(cli.RunPodAPIError) as error:
                cli.graphql("api", "query")
        self.assertIn("denied", str(error.exception))

    def test_runpod_rest_handles_empty_json_and_unexpected_shapes(self) -> None:
        with mock.patch("mere_runpod.cli.urllib.request.urlopen", return_value=FakeHTTPResponse("")):
            self.assertIsNone(cli.runpod_rest("api", "DELETE", "/networkvolumes/vol123"))

        with mock.patch("mere_runpod.cli.urllib.request.urlopen", return_value=FakeHTTPResponse('{"id":"vol123"}')):
            self.assertEqual(cli.create_network_volume("api", name="cache", data_center_id="US-KS-2", size_gb=512)["id"], "vol123")

        with mock.patch("mere_runpod.cli.runpod_rest", return_value={"not": "a-list"}):
            with self.assertRaises(cli.RunPodAPIError):
                cli.list_network_volumes("api")

        with mock.patch("mere_runpod.cli.runpod_rest", return_value=["not-a-dict"]):
            with self.assertRaises(cli.RunPodAPIError):
                cli.list_network_volumes("api")

    def test_json_boundary_helpers_reject_invalid_shapes(self) -> None:
        with self.assertRaises(cli.PluginError):
            cli.as_map([], "payload")
        with self.assertRaises(cli.PluginError):
            cli.as_list({}, "items")
        with self.assertRaises(cli.PluginError):
            cli.string_list(["ok", 1], "command")
        with self.assertRaises(cli.PluginError):
            cli.string_field({"name": 3}, "name", "payload")
        with self.assertRaises(cli.PluginError):
            cli.int_value(True, "count")
        with self.assertRaises(cli.PluginError):
            cli.int_value(object(), "count")
        self.assertEqual(cli.int_value("22", "count"), 22)

    def test_query_pod_and_ssh_target_parse_runtime_ports(self) -> None:
        pod = {
            "id": "pod123",
            "runtime": {
                "ports": [
                    {"privatePort": 8888, "ip": "1.1.1.1", "publicPort": 8888},
                    {"privatePort": 22, "ip": "2.2.2.2", "publicPort": 32022},
                ]
            },
        }
        with mock.patch("mere_runpod.cli.graphql", return_value={"pod": pod}):
            self.assertEqual(cli.query_pod("api", "pod123"), pod)
        self.assertEqual(cli.ssh_target(pod), ("2.2.2.2", 32022))
        with self.assertRaises(cli.PluginError):
            cli.query_pod("api", "../../bad")

    def test_doctor_manifest_and_env_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            env_file = root / ".env"
            ssh_key = root / "id"
            ssh_pub = root / "id.pub"
            build_pack = root / "pack.tar.gz"
            env_file.write_text("RUNPOD_API_KEY=from-file\n# ignored\nEMPTY\n")
            ssh_key.write_text("fake")
            ssh_pub.write_text("fake.pub")
            build_pack.write_bytes(b"not a real tar for doctor")

            stdout = StringIO()
            with mock.patch.dict(cli.os.environ, {}, clear=True):
                with mock.patch("mere_runpod.cli.shutil.which", return_value="/usr/bin/tool"):
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        exit_code = cli.main([
                            "doctor",
                            "--env-file",
                            str(env_file),
                            "--ssh-key",
                            str(ssh_key),
                            "--public-key-file",
                            str(ssh_pub),
                            "--build-pack",
                            str(build_pack),
                        ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])

            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                exit_code = cli.main(["manifest"])
            self.assertEqual(exit_code, 0)
            self.assertIn("manifest output is JSON", stderr.getvalue())

    def test_cleanup_provider_failure_returns_json_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = pathlib.Path(tmp) / "run.json"
            manifest.write_text(json.dumps({
                "contractVersion": "mere.run/plugin-run.v1",
                "runId": "cleanup-test",
                "plugin": {"name": "mere-runpod", "version": "0.1.0"},
                "recipe": {"id": "klein-style-lora", "family": "style-lora"},
                "status": "failed",
                "createdAt": "2026-01-01T00:00:00+00:00",
                "dataset": {"path": tmp, "pairCount": 16},
                "command": ["mere.run"],
                "remote": {"podId": "pod123"},
                "artifacts": {},
                "cleanup": {"default": "terminate", "status": "not-started"},
            }))
            stdout = StringIO()
            with mock.patch.dict(cli.os.environ, {"RUNPOD_API_KEY": "fake"}, clear=False):
                with mock.patch("mere_runpod.cli.terminate_pod", side_effect=cli.RunPodAPIError("unauthorized", 4)):
                    with redirect_stdout(stdout):
                        exit_code = cli.main(["cleanup", str(manifest)])
            self.assertEqual(exit_code, 5)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["cleanup"]["status"], "failed")
            self.assertEqual(payload["cleanup"]["error"], "unauthorized")

    def test_cleanup_marks_active_manifest_cleanup_only_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = pathlib.Path(tmp) / "run.json"
            manifest.write_text(json.dumps({
                "contractVersion": "mere.run/plugin-run.v1",
                "runId": "cleanup-test",
                "plugin": {"name": "mere-runpod", "version": "0.1.0"},
                "recipe": {"id": "klein-style-lora", "family": "style-lora"},
                "status": "running",
                "createdAt": "2026-01-01T00:00:00+00:00",
                "dataset": {"path": tmp, "pairCount": 16},
                "command": ["mere.run"],
                "remote": {"podId": "pod123"},
                "artifacts": {},
                "cleanup": {"default": "terminate", "status": "not-started"},
            }))
            stdout = StringIO()
            with mock.patch.dict(cli.os.environ, {"RUNPOD_API_KEY": "fake"}, clear=False):
                with mock.patch("mere_runpod.cli.terminate_pod", return_value=None):
                    with redirect_stdout(stdout):
                        exit_code = cli.main(["cleanup", str(manifest)])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["cleanup"]["status"], "succeeded")
            self.assertEqual(payload["status"], "cleanup-only")

    def test_cleanup_is_idempotent_and_skips_missing_pod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            succeeded = root / "succeeded.json"
            succeeded.write_text(json.dumps({
                "runId": "already-clean",
                "status": "running",
                "remote": {"podId": "pod123"},
                "cleanup": {"default": "terminate", "status": "succeeded"},
            }))
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["cleanup", str(succeeded)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["cleanup"]["reason"], "already cleaned up")

            missing = root / "missing.json"
            missing.write_text(json.dumps({
                "runId": "no-pod",
                "status": "failed",
                "remote": {},
                "cleanup": {"default": "terminate", "status": "not-started"},
            }))
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main(["cleanup", str(missing)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["cleanup"]["reason"], "no pod id in run manifest")

    def test_cleanup_treats_missing_remote_resource_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = pathlib.Path(tmp) / "run.json"
            manifest.write_text(json.dumps({
                "runId": "already-gone",
                "status": "running",
                "remote": {"podId": "pod123"},
                "cleanup": {"default": "terminate", "status": "not-started"},
            }))
            stdout = StringIO()
            with mock.patch.dict(cli.os.environ, {"RUNPOD_API_KEY": "fake"}, clear=True):
                with mock.patch("mere_runpod.cli.terminate_pod", side_effect=cli.RunPodAPIError("pod not found", 4)):
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        exit_code = cli.main(["cleanup", str(manifest)])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["cleanup"]["status"], "succeeded")
            self.assertEqual(payload["cleanup"]["reason"], "remote resource already absent")

    def test_resume_queries_live_pod_when_api_key_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = pathlib.Path(tmp) / "run.json"
            manifest.write_text(json.dumps({
                "runId": "resume-test",
                "status": "running",
                "remote": {"podId": "pod123"},
                "cleanup": {"default": "terminate", "status": "not-started"},
            }))
            stdout = StringIO()
            with mock.patch.dict(cli.os.environ, {"RUNPOD_API_KEY": "fake"}, clear=True):
                with mock.patch("mere_runpod.cli.query_pod", return_value={"id": "pod123", "desiredStatus": "RUNNING"}):
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        exit_code = cli.main(["resume", str(manifest)])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["pod"]["desiredStatus"], "RUNNING")

    def test_command_from_style_recipe_preserves_base_and_apply_policy(self) -> None:
        recipe = cli.load_recipe("klein-style-lora")
        command = cli.command_from_recipe(
            recipe,
            data_path="/data",
            output_path="/out/style.safetensors",
            models_root="/models",
        )
        self.assertEqual(command[:4], ["mere.run", "--models-root", "/models", "image"])
        self.assertIn("--recipe", command)
        self.assertIn("klein-fast-style", command)
        self.assertIn("--sample-model", command)
        self.assertIn("image-klein-9b", command)

    def test_remote_train_script_extracts_build_pack_without_local_ownership(self) -> None:
        manifest = {
            "runId": "unit-test-run",
            "recipe": {"trainModel": "image-klein-base-9b"},
            "buildPack": {"path": "/tmp/mere.run-linux-cuda.tar.gz"},
            "command": ["mere.run", "image", "train-lora"],
            "remote": {
                "paths": {
                    "artifacts": "/remote/artifacts",
                    "build_pack": "/remote/build-pack",
                    "hub": "/remote/hub",
                    "models": "/remote/models",
                    "package": "/remote/package",
                }
            },
        }
        script = cli.remote_train_script(manifest)
        self.assertIn("tar --no-same-owner -xzf", script)
        self.assertIn("export MERERUN_HUB_CACHE=/remote/hub", script)
        self.assertIn("export MERERUN_MODEL_CACHE_HOME=/workspace/mere-runpod", script)
        self.assertIn("export MERERUN_MODELS_DIR=/remote/models", script)
        self.assertIn('export MLX_CUDA_USE_CUDNN_SDPA="${MLX_CUDA_USE_CUDNN_SDPA:-0}"', script)
        self.assertIn('export MLX_CUDA_GRAPH_CACHE_SIZE="${MLX_CUDA_GRAPH_CACHE_SIZE:-4096}"', script)

    def test_remote_train_script_pulls_sample_model(self) -> None:
        manifest = {
            "runId": "unit-test-run",
            "recipe": {"trainModel": "image-klein-base"},
            "buildPack": {"path": "/tmp/mere.run-linux-cuda.tar.gz"},
            "command": [
                "mere.run",
                "image",
                "train-lora",
                "--model",
                "image-klein-base",
                "--sample-model",
                "image-klein-max",
            ],
            "remote": {
                "paths": {
                    "artifacts": "/remote/artifacts",
                    "build_pack": "/remote/build-pack",
                    "hub": "/remote/hub",
                    "models": "/remote/models",
                    "package": "/remote/package",
                }
            },
        }
        script = cli.remote_train_script(manifest)
        self.assertIn("model pull image-klein-base || true", script)
        self.assertIn("model pull image-klein-max || true", script)

    def test_fetch_remote_artifacts_fetches_final_files_before_optional_checkpoints(self) -> None:
        manifest = {
            "runId": "unit-test-run",
            "remote": {
                "paths": {
                    "artifacts": "/remote/artifacts",
                },
            },
        }
        args = Namespace(fetch_checkpoints=False)
        target = ("host", 22)
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp)
            with mock.patch("mere_runpod.cli.rsync_remote_file_if_exists", return_value=True) as fetch_file:
                with mock.patch("mere_runpod.cli.rsync_from_remote") as fetch_all:
                    cli.fetch_remote_artifacts(args, target, manifest, output)
        self.assertEqual(fetch_file.call_args_list[0].args[2], "/remote/artifacts/unit-test-run.safetensors")
        self.assertEqual(fetch_file.call_args_list[0].args[3], output / "artifacts" / "unit-test-run.safetensors")
        fetched_sources = [call.args[2] for call in fetch_file.call_args_list]
        self.assertIn("/remote/artifacts/unit-test-run.events.jsonl", fetched_sources)
        fetch_all.assert_not_called()

    def test_fetch_remote_artifacts_can_fetch_full_checkpoint_tree(self) -> None:
        manifest = {
            "runId": "unit-test-run",
            "remote": {
                "paths": {
                    "artifacts": "/remote/artifacts",
                },
            },
        }
        args = Namespace(fetch_checkpoints=True)
        target = ("host", 22)
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp)
            with mock.patch("mere_runpod.cli.rsync_remote_file_if_exists", return_value=True):
                with mock.patch("mere_runpod.cli.rsync_from_remote") as fetch_all:
                    cli.fetch_remote_artifacts(args, target, manifest, output)
        fetch_all.assert_called_once_with(args, target, "/remote/artifacts", output / "artifacts")

    def test_ensure_remote_build_pack_reuses_cached_file(self) -> None:
        manifest = {
            "buildPack": {
                "remotePath": "/workspace/mere-runpod/build-packs/abc-pack.tar.gz",
            },
        }
        args = Namespace(build_pack=pathlib.Path("/tmp/pack.tar.gz"))
        target = ("host", 22)
        with mock.patch("mere_runpod.cli.remote_file_exists", return_value=True):
            with mock.patch("mere_runpod.cli.rsync_to_remote") as upload:
                with mock.patch("mere_runpod.cli.log"):
                    resolved = cli.ensure_remote_build_pack(args, target, manifest)
        self.assertEqual(resolved, "/workspace/mere-runpod/build-packs/abc-pack.tar.gz")
        upload.assert_not_called()

    def test_ensure_remote_build_pack_uploads_missing_file_to_cache_path(self) -> None:
        manifest = {
            "buildPack": {
                "remotePath": "/workspace/mere-runpod/build-packs/abc-pack.tar.gz",
            },
        }
        args = Namespace(build_pack=pathlib.Path("/tmp/pack.tar.gz"))
        target = ("host", 22)
        with mock.patch("mere_runpod.cli.remote_file_exists", return_value=False):
            with mock.patch("mere_runpod.cli.ssh_script") as run_script:
                with mock.patch("mere_runpod.cli.rsync_to_remote") as upload:
                    with mock.patch("mere_runpod.cli.log"):
                        resolved = cli.ensure_remote_build_pack(args, target, manifest)
        self.assertEqual(resolved, "/workspace/mere-runpod/build-packs/abc-pack.tar.gz")
        run_script.assert_called_once()
        upload.assert_called_once_with(args, target, pathlib.Path("/tmp/pack.tar.gz"), "/workspace/mere-runpod/build-packs/abc-pack.tar.gz")

    def test_create_pod_uses_network_volume_instead_of_ephemeral_volume(self) -> None:
        args = Namespace(
            cloud_type="SECURE",
            gpu_count=1,
            volume_gb=160,
            container_disk_gb=120,
            min_vcpu=16,
            min_memory_gb=120,
            gpu="NVIDIA H100 80GB HBM3",
            pod_name="test-pod",
            image="runpod/pytorch:test",
            network_volume_id="volabc123",
            data_center_id="US-KS-2",
            allowed_cuda_versions=[],
        )
        with mock.patch("mere_runpod.cli.graphql", return_value={"podFindAndDeployOnDemand": {"id": "pod123"}}) as graphql:
            cli.create_pod(args, "api", "ssh-rsa fake")
        pod_input = graphql.call_args.args[2]["input"]
        self.assertEqual(pod_input["networkVolumeId"], "volabc123")
        self.assertEqual(pod_input["dataCenterId"], "US-KS-2")
        self.assertNotIn("volumeInGb", pod_input)

    def test_run_command_records_remote_success_and_default_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            dataset = root / "dataset"
            output = root / "run"
            build_pack = root / "mere-run-linux-cuda.tar.gz"
            ssh_key = root / "id"
            ssh_pub = root / "id.pub"
            write_dataset(dataset, 12)
            write_tar(build_pack, {"mere-run-linux/mere.run": b"#!/usr/bin/env bash\n"})
            ssh_key.write_text("fake")
            ssh_pub.write_text("fake.pub")

            with (
                mock.patch.dict(
                    cli.os.environ,
                    {"RUNPOD_API_KEY": "api", "HF_TOKEN": "hf"},
                    clear=True,
                ),
                mock.patch("mere_runpod.cli.shutil.which", return_value="/usr/bin/tool"),
                mock.patch("mere_runpod.cli.create_pod", return_value={"id": "pod123", "costPerHr": 1.5}),
                mock.patch("mere_runpod.cli.wait_for_ssh", return_value=("2.2.2.2", 32022)),
                mock.patch("mere_runpod.cli.ssh_script"),
                mock.patch("mere_runpod.cli.rsync_to_remote"),
                mock.patch("mere_runpod.cli.ensure_remote_build_pack"),
                mock.patch("mere_runpod.cli.fetch_remote_artifacts"),
                mock.patch("mere_runpod.cli.terminate_pod") as terminate,
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                exit_code = cli.main([
                    "run",
                    "--recipe",
                    "klein-character-lora",
                    "--data",
                    str(dataset),
                    "--output",
                    str(output),
                    "--run-id",
                    "remote-success",
                    "--build-pack",
                    str(build_pack),
                    "--ssh-key",
                    str(ssh_key),
                    "--public-key-file",
                    str(ssh_pub),
                    "--data-center-id",
                    "US-KS-2",
                ])

            self.assertEqual(exit_code, 0)
            manifest = json.loads((output / "run.json").read_text())
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["cleanup"]["status"], "succeeded")
            terminate.assert_called_once_with("api", "pod123")

    def test_run_requires_data_center_with_network_volume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            dataset = root / "dataset"
            output = root / "run"
            build_pack = root / "mere-run-linux-cuda.tar.gz"
            write_dataset(dataset, 12)
            write_tar(build_pack, {"mere-run-linux/mere.run": b"#!/usr/bin/env bash\n"})
            stderr = StringIO()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                exit_code = cli.main([
                    "run",
                    "--recipe",
                    "klein-character-lora",
                    "--data",
                    str(dataset),
                    "--output",
                    str(output),
                    "--run-id",
                    "volume-without-dc",
                    "--build-pack",
                    str(build_pack),
                    "--network-volume-id",
                    "volabc123",
                ])
            self.assertEqual(exit_code, 2)
            self.assertIn("--data-center-id is required with --network-volume-id", stderr.getvalue())

    def test_volume_ensure_reuses_existing_volume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            existing = {
                "id": "volabc123",
                "name": "mere-klein-cache",
                "dataCenterId": "US-KS-2",
                "size": 512,
            }
            with mock.patch.dict(cli.os.environ, {"RUNPOD_API_KEY": "fake"}, clear=True):
                with mock.patch("mere_runpod.cli.list_network_volumes", return_value=[existing]):
                    with mock.patch("mere_runpod.cli.create_network_volume") as create:
                        with redirect_stdout(stdout), redirect_stderr(StringIO()):
                            exit_code = cli.main([
                                "volume",
                                "ensure",
                                "--name",
                                "mere-klein-cache",
                                "--data-center-id",
                                "US-KS-2",
                                "--size-gb",
                                "512",
                                "--env-file",
                                str(pathlib.Path(tmp) / "missing.env"),
                            ])
            self.assertEqual(exit_code, 0)
            create.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["created"])
            self.assertEqual(payload["volume"]["id"], "volabc123")

    def test_volume_list_create_and_validation_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = pathlib.Path(tmp) / "missing.env"

            stdout = StringIO()
            with mock.patch.dict(cli.os.environ, {"RUNPOD_API_KEY": "fake"}, clear=True):
                with mock.patch("mere_runpod.cli.list_network_volumes", return_value=[{"id": "vol123"}]):
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        exit_code = cli.main(["volume", "list", "--env-file", str(env_file)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["volumes"][0]["id"], "vol123")

            stdout = StringIO()
            with mock.patch.dict(cli.os.environ, {"RUNPOD_API_KEY": "fake"}, clear=True):
                with mock.patch("mere_runpod.cli.create_network_volume", return_value={"id": "new-vol"}) as create:
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        exit_code = cli.main([
                            "volume",
                            "create",
                            "--name",
                            "cache",
                            "--data-center-id",
                            "US-KS-2",
                            "--size-gb",
                            "512",
                            "--env-file",
                            str(env_file),
                        ])
            self.assertEqual(exit_code, 0)
            create.assert_called_once()
            self.assertTrue(json.loads(stdout.getvalue())["created"])

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "volume",
                    "create",
                    "--name",
                    "cache",
                    "--data-center-id",
                    "US-KS-2",
                    "--size-gb",
                    "1",
                    "--env-file",
                    str(env_file),
                ])
            self.assertEqual(exit_code, 2)

    def test_volume_ensure_dry_run_does_not_require_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            with mock.patch.dict(cli.os.environ, {}, clear=True):
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    exit_code = cli.main([
                        "volume",
                        "ensure",
                        "--name",
                        "mere-klein-cache",
                        "--data-center-id",
                        "US-KS-2",
                        "--size-gb",
                        "512",
                        "--dry-run",
                        "--env-file",
                        str(pathlib.Path(tmp) / "missing.env"),
                    ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["dryRun"])
            self.assertTrue(payload["createsPaidResource"])
            self.assertEqual(payload["request"]["name"], "mere-klein-cache")
            self.assertEqual(payload["request"]["dataCenterId"], "US-KS-2")

    def test_run_dry_run_writes_manifest_without_remote_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            dataset = root / "dataset"
            output = root / "run"
            write_dataset(dataset, 12)
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "run",
                    "--recipe",
                    "klein-character-lora",
                    "--data",
                    str(dataset),
                    "--output",
                    str(output),
                    "--run-id",
                    "dry-run",
                    "--dry-run",
                ])
            self.assertEqual(exit_code, 0)
            manifest = json.loads((output / "run.json").read_text())
            self.assertEqual(manifest["status"], "planned")

    def test_run_inputs_reject_bootstrap_build_pack_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            build_pack = root / "bootstrap.tar.gz"
            write_tar(build_pack, {
                "source.tar.gz": b"source",
                "bin/mere.run": b"#!/usr/bin/env bash\n",
            })
            args = Namespace(
                build_pack=build_pack,
                allow_bootstrap_build_pack=False,
                ssh_key=root / "missing-key",
                public_key_file=root / "missing-key.pub",
            )
            with self.assertRaises(cli.PluginError) as error:
                cli.validate_run_inputs(args, cli.load_recipe("klein-style-lora"))
            self.assertIn("refusing bootstrap/source build pack", str(error.exception))

    def test_run_inputs_require_hf_token_for_klein_recipes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            build_pack = root / "ready.tar.gz"
            ssh_key = root / "id"
            ssh_pub = root / "id.pub"
            write_tar(build_pack, {"mere-run-linux/mere.run": b"#!/usr/bin/env bash\n"})
            ssh_key.write_text("fake")
            ssh_pub.write_text("fake.pub")
            args = Namespace(
                build_pack=build_pack,
                allow_bootstrap_build_pack=False,
                ssh_key=ssh_key,
                public_key_file=ssh_pub,
            )
            env = {"RUNPOD_API_KEY": "fake"}
            with mock.patch.dict(cli.os.environ, env, clear=True):
                with mock.patch("mere_runpod.cli.shutil.which", return_value="/usr/bin/fake"):
                    with self.assertRaises(cli.PluginError) as error:
                        cli.validate_run_inputs(args, cli.load_recipe("klein-style-lora"))
            self.assertIn("requires a Hugging Face token", str(error.exception))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import mock

from mere_terminal_bench import cli


def write_job_result(
    job_dir: pathlib.Path,
    *,
    rewards: dict[str, float],
    errors: set[str] | None = None,
) -> None:
    job_dir.mkdir(parents=True)
    error_tasks = errors or set()
    (job_dir / "result.json").write_text(
        json.dumps(
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "started_at": "2026-08-30T12:00:00Z",
                "finished_at": "2026-08-30T12:02:00Z",
                "n_total_trials": len(rewards),
                "stats": {
                    "n_completed_trials": len(rewards),
                    "n_errored_trials": len(error_tasks),
                    "n_cancelled_trials": 0,
                    "n_input_tokens": 100,
                    "n_cache_tokens": 20,
                    "n_output_tokens": 30,
                },
            }
        )
    )
    for index, (task, reward) in enumerate(rewards.items()):
        trial = job_dir / f"trial-{index}"
        trial.mkdir()
        exception = None
        if task in error_tasks:
            exception = {"exception_type": "RuntimeError"}
        (trial / "result.json").write_text(
            json.dumps(
                {
                    "task_name": task,
                    "trial_name": f"{task}-1",
                    "started_at": "2026-08-30T12:00:00Z",
                    "finished_at": "2026-08-30T12:01:00Z",
                    "environment_setup": {
                        "started_at": "2026-08-30T12:00:00Z",
                        "finished_at": "2026-08-30T12:00:05Z",
                    },
                    "agent_execution": {
                        "started_at": "2026-08-30T12:00:05Z",
                        "finished_at": "2026-08-30T12:00:45Z",
                    },
                    "verifier_result": {"rewards": {"reward": reward}},
                    "exception_info": exception,
                    "agent_result": {
                        "n_input_tokens": 10,
                        "n_cache_tokens": 2,
                        "n_output_tokens": 3,
                    },
                }
            )
        )


def plan_args(output: pathlib.Path) -> argparse.Namespace:
    return argparse.Namespace(
        run_id="unit-run",
        attempts=1,
        concurrency=1,
        max_additional_storage_gb=64.0,
        context_size=131_072,
        max_output_tokens=32_768,
        models=None,
        output=output,
        port=18_080,
        include_tasks=None,
        n_tasks=None,
        temperature=0.7,
        timeout_multiplier=1.0,
        docker="docker",
        docker_context="test-context",
        mere_run="mere.run",
        engine="text-chat-q36",
        harbor="harbor",
        force=False,
    )


class FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode()

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *_error: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeProcess:
    def __init__(self, pid: int = 42) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.poll_count = 0

    def poll(self) -> int | None:
        self.poll_count += 1
        if self.poll_count >= 2:
            self.returncode = 0
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0


class MereTerminalBenchTests(unittest.TestCase):
    def test_manifest_declares_plan_first_local_plugin(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        self.assertEqual(manifest["name"], "mere-terminal-bench")
        commands = {item["name"] for item in manifest["commands"]}
        self.assertTrue({"manifest", "doctor", "plan", "run", "resume", "report", "cleanup"}.issubset(commands))
        self.assertFalse(manifest["security"]["createsPaidResources"])
        self.assertEqual(manifest["security"]["cleanupDefault"], "stop")

    def test_plan_is_pinned_and_never_creates_docker_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "run"
            args = plan_args(output)
            manifest = cli.planned_manifest(args)
            self.assertEqual(manifest["pins"]["harborVersion"], "0.22.0")
            self.assertEqual(manifest["dataset"]["sha256"], cli.DATASET_REF)
            self.assertEqual(manifest["dataset"]["pairCount"], 89)
            self.assertFalse(manifest["runtime"]["createsDockerRuntime"])
            self.assertEqual(manifest["runtime"]["maximumAdditionalStorageBytes"], 64 * 1024**3)
            self.assertEqual(manifest["models"], list(cli.DEFAULT_MODELS))
            self.assertEqual(manifest["server"]["memoryGuard"], "balanced")
            self.assertFalse(manifest["comparison"]["leaderboardEligible"])

    def test_plan_supports_bounded_smoke_and_leaderboard_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = plan_args(pathlib.Path(tmp) / "run")
            args.n_tasks = 1
            args.include_tasks = ["hello-world"]
            args.models = ["model-a"]
            manifest = cli.planned_manifest(args)
            self.assertEqual(manifest["dataset"]["pairCount"], 1)
            self.assertEqual(manifest["dataset"]["includeTasks"], ["terminal-bench/hello-world"])
            self.assertEqual(manifest["models"], ["model-a"])
            args.n_tasks = 89
            args.include_tasks = None
            args.attempts = 5
            eligible = cli.planned_manifest(args)
            self.assertTrue(eligible["comparison"]["leaderboardEligible"])

    def test_task_filter_preserves_fully_qualified_names(self) -> None:
        self.assertEqual(
            cli.terminal_bench_task_name("terminal-bench/regex-log"),
            "terminal-bench/regex-log",
        )

    def test_plan_rejects_unsafe_or_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = plan_args(pathlib.Path(tmp) / "run")
            args.run_id = "../../escape"
            with self.assertRaises(cli.PluginError):
                cli.planned_manifest(args)
            args.run_id = "valid"
            args.max_additional_storage_gb = 0
            with self.assertRaises(cli.PluginError):
                cli.planned_manifest(args)
            args.max_additional_storage_gb = 1
            args.models = ["duplicate", "duplicate"]
            with self.assertRaises(cli.PluginError):
                cli.planned_manifest(args)

    def test_plan_command_writes_manifest_and_requires_force_to_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "run"
            argv = ["plan", "--output", str(output), "--run-id", "cli-plan"]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(cli.main(argv), 0)
                self.assertEqual(cli.main(argv), 2)
                self.assertEqual(cli.main(argv + ["--force"]), 0)
            manifest = json.loads((output / "run.json").read_text())
            self.assertEqual(manifest["runId"], "cli-plan")

    def test_size_parser_accepts_docker_units(self) -> None:
        self.assertEqual(cli.parse_size_bytes("0B"), 0)
        self.assertEqual(cli.parse_size_bytes("1.5GB"), 1_500_000_000)
        self.assertEqual(cli.parse_size_bytes("2GiB"), 2 * 1024**3)
        with self.assertRaises(cli.PluginError):
            cli.parse_size_bytes("unknown")

    def test_docker_usage_sums_machine_readable_rows(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"Type":"Images","Size":"1GB"}\n{"Type":"Containers","Size":"2MiB"}\n',
            stderr="",
        )
        with mock.patch("mere_terminal_bench.cli.capture", return_value=completed):
            self.assertEqual(cli.docker_usage_bytes("docker", "context"), 1_000_000_000 + 2 * 1024**2)

    def test_docker_usage_retries_transient_snapshotter_failure(self) -> None:
        with (
            mock.patch(
                "mere_terminal_bench.cli.docker_usage_bytes",
                side_effect=[cli.PluginError("snapshotter race", 3), 42],
            ) as usage,
            mock.patch("mere_terminal_bench.cli.time.sleep") as sleep,
        ):
            self.assertEqual(cli.docker_usage_bytes_with_retry("docker", "bench"), 42)
        self.assertEqual(usage.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_docker_bind_mount_requires_bidirectional_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)

            def docker_round_trip(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                volume = argv[argv.index("--volume") + 1]
                mounted = pathlib.Path(volume.removesuffix(":/mere-run-probe:rw"))
                host_marker = next(mounted.glob(".mere-terminal-bench-host-probe-*"))
                docker_marker = mounted / host_marker.name.replace("host-probe", "docker-probe")
                docker_marker.write_text(host_marker.read_text())
                return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

            with mock.patch("mere_terminal_bench.cli.capture", side_effect=docker_round_trip):
                cli.validate_docker_bind_mount("docker", "bench", root)
            self.assertEqual(list(root.iterdir()), [])

            failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="mount denied")
            with mock.patch("mere_terminal_bench.cli.capture", return_value=failed):
                with self.assertRaisesRegex(cli.PluginError, "cannot read and write"):
                    cli.validate_docker_bind_mount("docker", "bench", root)
            self.assertEqual(list(root.iterdir()), [])

    def test_doctor_is_read_only_and_reports_failures(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["doctor"])
        with (
            mock.patch("mere_terminal_bench.cli.harbor_inspection", return_value={"ready": True}),
            mock.patch("mere_terminal_bench.cli.docker_inspection", return_value={"ready": False, "error": "stopped"}),
            mock.patch("mere_terminal_bench.cli.mere_run_preflight", return_value={"ready": True}),
            redirect_stdout(StringIO()) as stdout,
        ):
            self.assertEqual(cli.command_doctor(args), 3)
        report = json.loads(stdout.getvalue())
        self.assertFalse(report["ready"])
        self.assertFalse(report["mutated"])

    def test_harbor_config_is_typed_and_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = plan_args(pathlib.Path(tmp) / "run")
            args.include_tasks = ["task-a"]
            args.n_tasks = 1
            manifest = cli.planned_manifest(args)
            arm = manifest["arms"][0]
            config = cli.harbor_job_config(manifest, arm)
            self.assertEqual(config["datasets"][0]["ref"], cli.DATASET_REF)
            self.assertEqual(config["datasets"][0]["task_names"], ["terminal-bench/task-a"])
            self.assertEqual(config["agents"][0]["name"], "terminus-2")
            self.assertEqual(config["agents"][0]["kwargs"]["api_base"], "http://127.0.0.1:18080/v1")
            self.assertEqual(config["environment"], {"type": "docker", "delete": True})

    def test_endpoint_json_parses_object(self) -> None:
        with mock.patch(
            "mere_terminal_bench.cli.urllib.request.urlopen",
            return_value=FakeHTTPResponse('{"status":"ok"}'),
        ):
            self.assertEqual(cli.endpoint_json("http://127.0.0.1/health")["status"], "ok")

    def test_summarize_and_compare_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            left_dir = root / "left"
            right_dir = root / "right"
            write_job_result(left_dir, rewards={"a": 1, "b": 0, "c": 1})
            write_job_result(right_dir, rewards={"a": 1, "b": 1, "c": 0}, errors={"c"})
            left = cli.summarize_job(left_dir)
            right = cli.summarize_job(right_dir)
            self.assertEqual(left["passedTrials"], 2)
            self.assertEqual(left["durationSeconds"], 120)
            self.assertEqual(left["agentExecutionSeconds"], 120)
            self.assertEqual(left["meanAgentExecutionSeconds"], 40)
            manifest = {
                "runId": "compare",
                "pins": {},
                "dataset": {},
                "comparison": {},
                "arms": [
                    {"model": "q4", "status": "succeeded", "summary": left},
                    {"model": "q8", "status": "succeeded", "summary": right},
                ],
            }
            report = cli.comparison_report(manifest)
            self.assertEqual(report["pairwise"]["matchedTasks"], 3)
            self.assertEqual(report["pairwise"]["leftWins"], 1)
            self.assertEqual(report["pairwise"]["rightWins"], 1)
            self.assertEqual(report["pairwise"]["ties"], 1)
            self.assertEqual(report["pairwise"]["matchedTimedTasks"], 3)
            self.assertEqual(report["pairwise"]["timingTies"], 3)

    def test_incomplete_harbor_job_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = pathlib.Path(tmp) / "job"
            write_job_result(job_dir, rewards={"task": 1}, errors={"task"})
            trial_path = job_dir / "trial-0" / "result.json"
            trial = json.loads(trial_path.read_text())
            trial["verifier_result"] = None
            trial_path.write_text(json.dumps(trial))
            summary = cli.summarize_job(job_dir)
            message = cli.incomplete_job_error(summary)
            self.assertIsNotNone(message)
            self.assertIn("scored=0", message or "")

    def test_scored_harbor_errors_remain_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = pathlib.Path(tmp) / "job"
            write_job_result(
                job_dir,
                rewards={"passed-timeout": 1, "failed-timeout": 0},
                errors={"passed-timeout", "failed-timeout"},
            )
            summary = cli.summarize_job(job_dir)
            self.assertEqual(summary["completedTrials"], 2)
            self.assertEqual(summary["scoredTrials"], 2)
            self.assertEqual(summary["erroredTrials"], 2)
            self.assertEqual(summary["passedTrials"], 1)
            self.assertIsNone(cli.incomplete_job_error(summary))

    def test_cancelled_harbor_job_fails_closed(self) -> None:
        summary = {
            "totalTrials": 1,
            "completedTrials": 1,
            "scoredTrials": 1,
            "erroredTrials": 0,
            "cancelledTrials": 1,
        }
        message = cli.incomplete_job_error(summary)
        self.assertIsNotNone(message)
        self.assertIn("cancelled=1", message or "")

    def test_artifact_bundle_hashes_only_existing_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            run = root / "run.json"
            report = root / "report.json"
            config = root / "config.json"
            for path in (run, report, config):
                path.write_text("{}\n")
            manifest = {
                "artifacts": {"report": str(report), "bundle": str(root / "bundle.json")},
                "arms": [
                    {
                        "configPath": str(config),
                        "serverLogPath": str(root / "missing.log"),
                        "jobDirectory": str(root / "missing-job"),
                    }
                ],
            }
            bundle = cli.write_artifact_bundle(run, manifest)
            self.assertEqual(len(bundle["files"]), 3)
            self.assertTrue((root / "bundle.json").is_file())

    def test_artifact_bundle_includes_trial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            run = root / "run.json"
            report = root / "report.json"
            config = root / "config.json"
            server_log = root / "server.log"
            harbor_log = root / "server-harbor.log"
            job_directory = root / "job"
            trial_directory = job_directory / "task__attempt-1"
            evidence = [
                run,
                report,
                config,
                server_log,
                harbor_log,
                job_directory / "job.log",
                job_directory / "result.json",
                trial_directory / "result.json",
                trial_directory / "agent" / "trajectory.json",
                trial_directory / "verifier" / "reward.txt",
                trial_directory / "verifier" / "reward.json",
                trial_directory / "verifier" / "ctrf.json",
                trial_directory / "verifier" / "test-stdout.txt",
            ]
            for path in evidence:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n")
            manifest = {
                "artifacts": {"report": str(report), "bundle": str(root / "bundle.json")},
                "arms": [
                    {
                        "configPath": str(config),
                        "serverLogPath": str(server_log),
                        "jobDirectory": str(job_directory),
                    }
                ],
            }
            bundle = cli.write_artifact_bundle(run, manifest)
            bundled_paths = {entry["path"] for entry in bundle["files"]}
            self.assertEqual(bundled_paths, {str(path) for path in evidence})

    def test_docker_usage_baseline_survives_resume(self) -> None:
        runtime = {"baselineDockerUsageBytes": 100}
        baseline = cli.record_docker_usage(runtime, 150)
        self.assertEqual(baseline, 100)
        self.assertEqual(runtime["baselineDockerUsageBytes"], 100)
        self.assertEqual(runtime["currentDockerUsageBytes"], 150)
        self.assertEqual(runtime["additionalDockerUsageBytes"], 50)

    def test_docker_usage_records_initial_baseline(self) -> None:
        runtime: cli.JsonMap = {}
        baseline = cli.record_docker_usage(runtime, 150)
        self.assertEqual(baseline, 150)
        self.assertEqual(runtime["baselineDockerUsageBytes"], 150)
        self.assertEqual(runtime["additionalDockerUsageBytes"], 0)

    def test_cleanup_refuses_to_signal_unrelated_process(self) -> None:
        arm = {"serverPid": 42, "model": "ornith"}
        with mock.patch("mere_terminal_bench.cli.process_command", return_value="python unrelated.py"):
            with self.assertRaises(cli.PluginError):
                cli.stop_recorded_server(arm)

    def test_cleanup_signals_matching_server_only(self) -> None:
        arm = {"serverPid": 42, "model": "ornith"}
        with (
            mock.patch(
                "mere_terminal_bench.cli.process_command",
                return_value="mere.run api serve --model ornith",
            ),
            mock.patch("mere_terminal_bench.cli.os.kill") as kill,
        ):
            self.assertTrue(cli.stop_recorded_server(arm))
        kill.assert_called_once()
        self.assertIsNone(arm["serverPid"])

    def test_harbor_storage_ceiling_stops_without_pruning(self) -> None:
        process = FakeProcess()
        manifest = {
            "harbor": {"executable": "harbor"},
            "runtime": {
                "dockerExecutable": "docker",
                "dockerContext": "bench",
                "baselineDockerUsageBytes": 100,
                "maximumAdditionalStorageBytes": 10,
            },
        }
        arm = {"configPath": "/tmp/config.json", "jobName": "job"}
        with (
            mock.patch("mere_terminal_bench.cli.executable_path", side_effect=lambda value: f"/bin/{value}"),
            mock.patch("mere_terminal_bench.cli.subprocess.Popen", return_value=process),
            mock.patch("mere_terminal_bench.cli.time.sleep"),
            mock.patch("mere_terminal_bench.cli.docker_usage_bytes", return_value=111),
            mock.patch("mere_terminal_bench.cli.update_manifest") as update,
            mock.patch("mere_terminal_bench.cli.terminate_process") as terminate,
        ):
            with self.assertRaises(cli.PluginError):
                cli.run_harbor(pathlib.Path("/tmp/run.json"), manifest, arm, log_stream=StringIO(), check_interval=0)
        terminate.assert_called_once_with(process)
        update.assert_called_once()

    def test_harbor_monitor_failure_terminates_child(self) -> None:
        process = FakeProcess()
        manifest = {
            "harbor": {"executable": "harbor"},
            "runtime": {
                "dockerExecutable": "docker",
                "dockerContext": "bench",
                "baselineDockerUsageBytes": 100,
                "maximumAdditionalStorageBytes": 10,
            },
        }
        arm = {"configPath": "/tmp/config.json", "jobName": "job"}
        with (
            mock.patch("mere_terminal_bench.cli.executable_path", side_effect=lambda value: f"/bin/{value}"),
            mock.patch("mere_terminal_bench.cli.subprocess.Popen", return_value=process),
            mock.patch("mere_terminal_bench.cli.time.sleep"),
            mock.patch(
                "mere_terminal_bench.cli.docker_usage_bytes",
                side_effect=cli.PluginError("snapshotter race", 3),
            ) as usage,
            mock.patch("mere_terminal_bench.cli.terminate_process") as terminate,
        ):
            with self.assertRaisesRegex(cli.PluginError, "after 3 attempts"):
                cli.run_harbor(
                    pathlib.Path("/tmp/run.json"),
                    manifest,
                    arm,
                    log_stream=StringIO(),
                    check_interval=0,
                )
        self.assertEqual(usage.call_count, 3)
        terminate.assert_called_once_with(process)

    def test_command_report_refreshes_existing_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            args = plan_args(root)
            manifest = cli.planned_manifest(args)
            arm = manifest["arms"][0]
            write_job_result(pathlib.Path(arm["jobDirectory"]), rewards={"a": 1})
            run_path = root / "run.json"
            cli.write_json(run_path, manifest)
            with redirect_stdout(StringIO()) as stdout:
                self.assertEqual(cli.main(["report", str(run_path)]), 0)
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["arms"][0]["summary"]["passedTrials"], 1)

    def test_main_turns_plugin_errors_into_machine_safe_exit(self) -> None:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as stderr:
            exit_code = cli.main(["run", "/does/not/exist/run.json"])
        self.assertEqual(exit_code, 2)
        self.assertIn("error:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

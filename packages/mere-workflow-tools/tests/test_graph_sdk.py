from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

from mere_workflow_tools import (
    cli,
    comfy_bridge,
    graph_compiler,
    graph_conformance,
    graph_provider,
    graph_sdk,
    graph_studio,
)


class GraphSDKTests(unittest.TestCase):
    def test_canonical_parallel_graph_fixture_is_portable(self) -> None:
        fixture = (
            pathlib.Path(__file__).resolve().parents[3]
            / "contracts"
            / "fixtures"
            / "graph-v1"
            / "parallel-image-video.workflow.json"
        )
        graph = json.loads(fixture.read_text())

        self.assertEqual(graph["kind"], "mere.run/workflow-graph")
        self.assertEqual(graph["execution"]["max_parallel_nodes"], 2)
        self.assertEqual([node["id"] for node in graph["nodes"]], ["image-a", "image-b", "video"])
        self.assertEqual(graph["nodes"][2]["depends_on"], ["image-a", "image-b"])

    def test_catalog_and_event_stream_conformance(self) -> None:
        catalog = graph_provider.graph_catalog("mere-dataset-tools", "1.2.3")
        graph_sdk.validate_catalog(catalog)
        events: list[graph_sdk.JsonMap] = []
        stream = graph_sdk.GraphEventStream(events.append)

        stream.emit("progress", progress={"current": 1, "total": 1})
        stream.emit("node_result", outputs={"dataset": "artifacts/dataset"})

        self.assertEqual([item["sequence"] for item in events], [0, 1])
        self.assertEqual(events[0]["contract_version"], graph_sdk.EVENT_CONTRACT_VERSION)
        with self.assertRaisesRegex(graph_sdk.GraphProviderError, "final provider event"):
            stream.emit("metric", metric={"name": "late", "value": 1})

    def test_catalog_rejects_duplicate_node_kinds_and_invalid_traits(self) -> None:
        catalog = graph_provider.graph_catalog("mere-dataset-tools", "1.2.3")
        catalog["nodes"] = [catalog["nodes"][0], catalog["nodes"][0]]
        with self.assertRaisesRegex(graph_sdk.GraphProviderError, "duplicate graph node kind"):
            graph_sdk.validate_catalog(catalog)

        catalog = graph_provider.graph_catalog("mere-dataset-tools", "1.2.3")
        catalog["nodes"][0]["traits"]["cacheable"] = "yes"
        with self.assertRaisesRegex(graph_sdk.GraphProviderError, "cacheable must be a boolean"):
            graph_sdk.validate_catalog(catalog)

    def test_invocation_and_path_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "contract_version": graph_sdk.INVOCATION_CONTRACT_VERSION,
                        "kind": "dataset.prepare",
                        "arguments": {},
                        "outputs": {},
                    }
                )
            )
            invocation = graph_sdk.load_invocation(request, {"dataset.prepare"})

            self.assertEqual(invocation["kind"], "dataset.prepare")
            self.assertEqual(
                graph_sdk.confined_path(root, "artifacts/output.json"),
                (root / "artifacts/output.json").resolve(),
            )
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "not confined"):
                graph_sdk.confined_path(root, "../escape")
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "escapes"):
                graph_sdk.relative_path(root.parent, root)

    def test_invocation_resolves_named_secret_only_in_provider_memory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            request = pathlib.Path(raw_root) / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "contract_version": graph_sdk.INVOCATION_CONTRACT_VERSION,
                        "kind": "private.publish",
                        "arguments": {"token": {"$secret": "api-token"}},
                        "outputs": {},
                    }
                )
            )
            with mock.patch.dict("os.environ", {"MERERUN_SECRET_API_TOKEN": "value-never-persisted"}, clear=False):
                invocation = graph_sdk.load_invocation(request, {"private.publish"})

            self.assertEqual(invocation["arguments"]["token"], "value-never-persisted")
            self.assertNotIn("value-never-persisted", request.read_text())
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "configured secret is unavailable"):
                graph_sdk.resolve_secret_references({"$secret": "missing"}, {})

    def test_catalog_validates_secret_and_resource_contracts(self) -> None:
        catalog = graph_provider.graph_catalog("mere-dataset-tools", "1.2.3")
        requirements = catalog["nodes"][0]["requirements"]
        requirements["minimum_system_memory_bytes"] = 4096
        requirements["minimum_disk_bytes"] = 8192
        requirements["minimum_cpu_cores"] = 2
        requirements["network_access"] = False
        graph_sdk.validate_catalog(catalog)

        requirements["minimum_cpu_cores"] = 0
        with self.assertRaisesRegex(graph_sdk.GraphProviderError, "positive integer"):
            graph_sdk.validate_catalog(catalog)

    def test_conformance_cli_validates_catalog_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps(graph_provider.graph_catalog("mere-dataset-tools", "1.2.3")))
            stdout = io.StringIO()
            with mock.patch.object(sys, "argv", ["mere-graph-conformance", "--catalog", str(catalog), "--json"]):
                with contextlib.redirect_stdout(stdout):
                    exit_code = graph_conformance.main()

            result = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["node_kinds"], ["dataset.prepare"])

    def test_conformance_cli_reports_invalid_provider_output(self) -> None:
        completed = mock.Mock(returncode=0, stdout="not-json", stderr="")
        stderr = io.StringIO()
        with mock.patch("mere_workflow_tools.graph_conformance.subprocess.run", return_value=completed):
            with mock.patch.object(sys, "argv", ["mere-graph-conformance", "--provider", "fixture"]):
                with contextlib.redirect_stderr(stderr):
                    exit_code = graph_conformance.main()

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid catalog JSON", stderr.getvalue())

    def test_comfy_api_prompt_imports_as_native_image_graph(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            workflow = root / "portrait-workflow.json"
            graph = root / "graph.json"
            inputs = root / "inputs.json"
            workflow.write_text(json.dumps(comfy_api_prompt()))
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = cli.main_for(
                    "dataset",
                    [
                        "graph",
                        "comfy",
                        "import",
                        str(workflow),
                        "--model",
                        "image-krea2-turbo",
                        "--output",
                        str(graph),
                        "--inputs-output",
                        str(inputs),
                        "--json",
                    ],
                )

            result = json.loads(stdout.getvalue())
            graph_value = json.loads(graph.read_text())
            input_value = json.loads(inputs.read_text())
            arguments = graph_value["nodes"][0]["arguments"]
            self.assertEqual(exit_code, 0)
            self.assertEqual(result["status"], "imported")
            self.assertEqual(graph_value["kind"], "mere.run/workflow-graph")
            self.assertEqual(graph_value["name"], "portrait-workflow")
            self.assertEqual(arguments["model"], "image-krea2-turbo")
            self.assertEqual(arguments["width"], 1024)
            self.assertEqual(arguments["cfg_scale"], 4.5)
            self.assertEqual(input_value["prompt"], "cinematic portrait")
            self.assertEqual(graph_value["metadata"]["comfy_checkpoint"], "flux.safetensors")
            self.assertEqual(len(result["report"]["warnings"]), 2)

    def test_comfy_ui_workflow_is_inspectable_but_not_importable(self) -> None:
        report = comfy_bridge.inspect_workflow(
            {
                "version": 0.4,
                "nodes": [
                    {"id": 1, "type": "KSampler"},
                    {"id": 2, "type": "CustomMagicNode"},
                ],
                "links": [],
            }
        )

        self.assertEqual(report["format"], "ui")
        self.assertFalse(report["importable"])
        self.assertEqual(report["unsupported_class_types"], ["CustomMagicNode"])
        with self.assertRaisesRegex(comfy_bridge.ComfyBridgeError, "API prompt format"):
            comfy_bridge.import_workflow(
                {"version": 0.4, "nodes": [{"id": 1, "type": "KSampler"}]},
                model_id="image-krea2-turbo",
                source_name="fixture.json",
                asset_root=None,
            )

    def test_native_graph_templates_are_listed_and_exported(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            output = pathlib.Path(raw_root) / "workflow.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cli.main_for(
                    "dataset",
                    [
                        "graph",
                        "templates",
                        "export",
                        "lora-train-sample",
                        "--output",
                        str(output),
                        "--json",
                    ],
                )

            result = json.loads(stdout.getvalue())
            graph = json.loads(output.read_text())
            self.assertEqual(exit_code, 0)
            self.assertEqual(result["status"], "exported")
            self.assertEqual(graph["metadata"]["template_id"], "lora-train-sample")
            self.assertEqual(graph["nodes"][0]["provider"], "mere-dataset-tools")

    def test_workflow_compiler_expands_modules_map_branch_and_parallel_policy(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            source = root / "program.json"
            source.write_text(json.dumps(workflow_program()))

            graph, report = graph_compiler.compile_file(source)
            repeated, repeated_report = graph_compiler.compile_file(source)

            self.assertEqual(graph, repeated)
            self.assertEqual(report["graph_sha256"], repeated_report["graph_sha256"])
            self.assertEqual(graph["execution"], {"max_parallel_nodes": 2})
            self.assertEqual(
                [node["id"] for node in graph["nodes"]],
                ["batch-000-image", "batch-001-image", "finish-video"],
            )
            self.assertEqual(
                graph["nodes"][2]["arguments"]["image"],
                {"$ref": "nodes.batch-001-image.outputs.image"},
            )
            self.assertEqual(graph["outputs"]["video"], {"$ref": "nodes.finish-video.outputs.video"})
            self.assertFalse(report["steps"][1]["included"])
            self.assertEqual(report["node_count"], 3)

    def test_workflow_compiler_supports_confined_imports_and_variable_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            modules = root / "modules"
            modules.mkdir()
            (modules / "sample.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": graph_compiler.MODULE_KIND,
                        "parameters": ["prompt"],
                        "nodes": [
                            {
                                "id": "image",
                                "kind": "image.generate",
                                "arguments": {"prompt": {"$param": "prompt"}},
                            }
                        ],
                        "outputs": {"image": {"$ref": "nodes.image.outputs.image"}},
                    }
                )
            )
            program = workflow_program()
            program["modules"] = {}
            program["imports"] = {"sample": "modules/sample.json"}
            program["variables"] = {"prompts": ["original"], "mode": "preview"}
            program["steps"] = [
                {
                    "id": "one",
                    "module": "sample",
                    "arguments": {"prompt": {"$var": "selected"}},
                }
            ]
            program["outputs"] = {"image": {"$ref": "steps.one.outputs.image"}}
            source = root / "program.json"
            source.write_text(json.dumps(program))

            graph, _report = graph_compiler.compile_file(source, {"selected": "override"})

            self.assertEqual(graph["nodes"][0]["arguments"]["prompt"], "override")
            program["imports"] = {"sample": "../escape.json"}
            source.write_text(json.dumps(program))
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "not confined"):
                graph_compiler.compile_file(source, {"selected": "override"})

    def test_workflow_compiler_rejects_ambiguous_mapped_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            source = pathlib.Path(raw_root) / "program.json"
            program = workflow_program()
            program["outputs"] = {"image": {"$ref": "steps.batch.outputs.image"}}
            source.write_text(json.dumps(program))

            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "requires an instance index"):
                graph_compiler.compile_file(source)

    def test_dataset_graph_compile_command_writes_graph_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            source = root / "program.json"
            output = root / "workflow.json"
            report = root / "compile.json"
            source.write_text(json.dumps(workflow_program()))
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = cli.main_for(
                    "dataset",
                    [
                        "graph",
                        "compile",
                        str(source),
                        "--output",
                        str(output),
                        "--report-output",
                        str(report),
                        "--json",
                    ],
                )

            result = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(result["status"], "compiled")
            self.assertEqual(json.loads(output.read_text())["kind"], graph_compiler.GRAPH_KIND)
            self.assertEqual(json.loads(report.read_text())["contract_version"], graph_compiler.REPORT_CONTRACT_VERSION)

    def test_graph_studio_round_trips_graph_inputs_and_separate_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            service = graph_studio.GraphStudioService(root, "/fixture/mere.run", lambda _command: graph_studio.CommandResult(0, "{}", ""))
            graph = {"schema_version": 1, "kind": "mere.run/workflow-graph", "name": "fixture", "inputs": {}, "nodes": [], "outputs": {}}
            sidecar = graph_studio.default_sidecar()
            sidecar["nodes"] = {"image": {"x": 12, "y": 34}}

            saved = service.save_project({
                "path": "workflows/shot.v1",
                "graph": graph,
                "inputs": {"prompt": "fixture"},
                "sidecar": sidecar,
            })
            loaded = service.load_project("workflows/shot.v1")

            self.assertEqual(saved["status"], "saved")
            self.assertEqual(loaded["graph"], graph)
            self.assertEqual(loaded["inputs"], {"prompt": "fixture"})
            self.assertEqual(loaded["sidecar"], sidecar)
            self.assertTrue((root / "workflows/shot.v1.workflow.json").is_file())
            self.assertTrue((root / "workflows/shot.v1.studio.json").is_file())
            self.assertNotIn("viewport", json.dumps(loaded["graph"]))
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "invalid project path"):
                service.save_project({"path": "../escape", "graph": graph})

    def test_graph_studio_invokes_only_public_catalog_and_preflight_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            commands: list[list[str]] = []

            def run(command: list[str]) -> graph_studio.CommandResult:
                commands.append(command)
                return graph_studio.CommandResult(0, json.dumps({"status": "ok"}), "diagnostic")

            service = graph_studio.GraphStudioService(pathlib.Path(raw_root), "/fixture/mere.run", run)
            service.catalog()
            result = service.check({
                "mode": "preflight",
                "executor": "relay:fleet",
                "graph": {"kind": "mere.run/workflow-graph"},
                "inputs": {},
            })

            self.assertEqual(commands[0], ["/fixture/mere.run", "graph", "catalog", "--json"])
            self.assertEqual(commands[1][0:3], ["/fixture/mere.run", "graph", "preflight"])
            self.assertIn("--executor", commands[1])
            self.assertIn("relay:fleet", commands[1])
            self.assertEqual(result["result"], {"status": "ok"})

    def test_graph_studio_submits_remote_graph_and_discovers_reference(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            executable = root / "fake-mere-run"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "print(json.dumps({'result': {'remote_reference': 'relay://fleet/job-123'}, 'argv': sys.argv[1:]}))\n"
            )
            executable.chmod(0o755)
            service = graph_studio.GraphStudioService(root, str(executable))
            started = service.start_run({
                "executor": "relay:fleet",
                "graph": {"schema_version": 1, "kind": "mere.run/workflow-graph", "name": "fixture", "inputs": {}, "nodes": [], "outputs": {}},
                "inputs": {},
            })
            deadline = time.monotonic() + 2
            inspected = service.inspect_run(str(started["id"]))
            while inspected["state"] in {"starting", "submitting"} and time.monotonic() < deadline:
                time.sleep(0.01)
                inspected = service.inspect_run(str(started["id"]))

            self.assertEqual(inspected["state"], "queued")
            self.assertEqual(inspected["remote_reference"], "relay://fleet/job-123")
            self.assertIn("submit", inspected["result"]["argv"])

    def test_graph_studio_utilities_confine_paths_and_find_remote_references(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            executable = root / "mere.run"
            executable.write_text("fixture")
            self.assertEqual(graph_studio.resolve_mere_run(str(executable)), str(executable))
            self.assertEqual(
                graph_studio.find_remote_reference({"nested": [{"reference": "ssh://gpu/job-9"}]}),
                "ssh://gpu/job-9",
            )
            events = root / "events.jsonl"
            events.write_text('{"type":"one"}\nnot-json\n{"type":"two"}\n')
            self.assertEqual(graph_studio.read_json_lines(events, 10), [{"type": "one"}, {"type": "two"}])


def workflow_program() -> graph_sdk.JsonMap:
    return {
        "schema_version": 1,
        "kind": graph_compiler.PROGRAM_KIND,
        "name": "mapped-generation",
        "inputs": {},
        "variables": {"prompts": ["first", "second"], "mode": "preview"},
        "execution": {"max_parallel_nodes": 2},
        "modules": {
            "sample": {
                "parameters": ["prompt", "seed"],
                "nodes": [
                    {
                        "id": "image",
                        "kind": "image.generate",
                        "arguments": {"prompt": {"$param": "prompt"}, "seed": {"$param": "seed"}},
                    }
                ],
                "outputs": {"image": {"$ref": "nodes.image.outputs.image"}},
            },
            "animate": {
                "parameters": ["image"],
                "nodes": [
                    {
                        "id": "video",
                        "kind": "video.generate",
                        "arguments": {
                            "prompt": "animate",
                            "image": {"$param": "image"},
                            "seed": 7,
                        },
                    }
                ],
                "outputs": {"video": {"$ref": "nodes.video.outputs.video"}},
            },
        },
        "steps": [
            {
                "id": "batch",
                "module": "sample",
                "map": {"item": "prompt", "values": {"$var": "prompts"}},
                "arguments": {"prompt": {"$item": "prompt"}, "seed": 42},
            },
            {
                "id": "production-only",
                "module": "sample",
                "when": {"equals": [{"$var": "mode"}, "production"]},
                "arguments": {"prompt": "production", "seed": 43},
            },
            {
                "id": "finish",
                "module": "animate",
                "arguments": {"image": {"$ref": "steps.batch.1.outputs.image"}},
            },
        ],
        "outputs": {"video": {"$ref": "steps.finish.outputs.video"}},
        "metadata": {"compiled_from": "fixture", "mode": {"$var": "mode"}},
    }


def comfy_api_prompt() -> graph_sdk.JsonMap:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "cinematic portrait", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 768, "batch_size": 1}},
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": 42,
                "steps": 20,
                "cfg": 4.5,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "ComfyUI"}},
    }


if __name__ == "__main__":
    unittest.main()

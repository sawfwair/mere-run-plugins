from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from mere_workflow_tools import (
    cli,
    comfy_bridge,
    graph_compiler,
    graph_conformance,
    graph_provider,
    graph_provider_init,
    graph_sdk,
    graph_templates,
)


class GraphSDKTests(unittest.TestCase):
    def test_editor_sidecar_keeps_graph_output_positions_non_executable(self) -> None:
        contract_root = pathlib.Path(__file__).resolve().parents[3] / "contracts"
        schema = json.loads((contract_root / "workflow-editor-sidecar.v1.schema.json").read_text())

        self.assertEqual(schema["properties"]["outputs"], schema["properties"]["nodes"])
        graph_schema = json.loads((contract_root / "workflow-graph.v1.schema.json").read_text())
        self.assertNotIn("position", json.dumps(graph_schema))

    def test_canonical_parallel_graph_fixture_is_portable(self) -> None:
        fixture_root = (
            pathlib.Path(__file__).resolve().parents[3]
            / "contracts"
            / "fixtures"
            / "graph-v1"
        )
        compatibility = json.loads((fixture_root / "graph-compatibility.v1.json").read_text())
        canonical = compatibility["canonical_fixture"]
        graph = json.loads((fixture_root / canonical["graph"]).read_text())
        inputs = json.loads((fixture_root / canonical["inputs"]).read_text())
        assets = json.loads((fixture_root / canonical["assets"]).read_text())

        self.assertEqual(compatibility["kind"], "mere.run/graph-compatibility")
        self.assertEqual(graph["kind"], "mere.run/workflow-graph")
        self.assertEqual(graph["execution"]["max_parallel_nodes"], 2)
        self.assertEqual([node["id"] for node in graph["nodes"]], ["image-a", "image-b", "video"])
        self.assertEqual(graph["nodes"][2]["depends_on"], ["image-a", "image-b"])
        self.assertEqual(graph_compiler.canonical_digest(graph), canonical["graph_fingerprint"])
        self.assertEqual(
            graph_compiler.canonical_digest({"inputs": inputs, "assets": assets}),
            canonical["input_fingerprint"],
        )

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

    def test_preflight_and_execution_documents_are_validated_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            artifact = root / "artifacts" / "result.txt"
            artifact.parent.mkdir()
            artifact.write_text("result\n")
            invocation = {
                "outputs": {"artifact": {"type": "asset", "path": "artifacts/result.txt"}},
            }
            preflight = {
                "contract_version": graph_sdk.PREFLIGHT_CONTRACT_VERSION,
                "status": "ok",
                "diagnostics": [],
                "actions": [],
                "requirements": {"model_ids": [], "accelerator_backends": ["cpu"]},
            }
            events = [
                graph_sdk.event(0, "progress", progress={"current": 1, "total": 1}),
                graph_sdk.event(1, "node_result", outputs={"artifact": "artifacts/result.txt"}),
            ]

            graph_sdk.validate_preflight(preflight)
            graph_sdk.validate_event_stream(events, invocation, root)

            preflight["status"] = "blocked"
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "blocker diagnostic"):
                graph_sdk.validate_preflight(preflight)
            events[-1]["outputs"] = {"unknown": "result"}
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "missing declared outputs"):
                graph_sdk.validate_event_stream(events, invocation, root)

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

    def test_conformance_cli_executes_fixture_and_verifies_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = pathlib.Path(raw_root)
            provider = root / "fixture-provider"
            provider.write_text(
                "#!/usr/bin/env python3\n"
                "import datetime, json, pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "if args[1] == 'catalog':\n"
                " print(json.dumps({'contract_version':'mere.run/plugin-graph-provider.v1','provider_id':'mere-fixture','provider_version':'1.0.0','nodes':[{'kind':'fixture.write','title':'Write','description':'Write fixture','inputs':[{'name':'text','type':'string','required':True}],'outputs':[{'name':'artifact','type':'asset','optional':False}],'requirements':{'model_ids':[],'accelerator_backends':['cpu'],'minimum_accelerator_memory_bytes':None},'traits':{'deterministic':True,'cacheable':True,'side_effects':'none','supports_progress':True,'supports_previews':False}}]}))\n"
                "elif args[1] == 'preflight':\n"
                " print(json.dumps({'contract_version':'mere.run/plugin-graph-preflight.v1','status':'ok','diagnostics':[],'actions':[],'requirements':{'model_ids':[],'accelerator_backends':['cpu']}}))\n"
                "else:\n"
                " request = json.loads(pathlib.Path(args[args.index('--request')+1]).read_text())\n"
                " run = pathlib.Path(args[args.index('--run-dir')+1]); output = run / request['outputs']['artifact']['path']; output.parent.mkdir(parents=True, exist_ok=True); output.write_text('fixture\\n')\n"
                " base = {'contract_version':'mere.run/plugin-graph-event.v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
                " print(json.dumps({**base,'sequence':0,'type':'progress'})); print(json.dumps({**base,'sequence':1,'type':'node_result','outputs':{'artifact':request['outputs']['artifact']['path']}}))\n"
            )
            provider.chmod(0o755)
            invocation = root / "invocation.json"
            invocation.write_text(json.dumps({
                "contract_version": graph_sdk.INVOCATION_CONTRACT_VERSION,
                "kind": "fixture.write",
                "arguments": {"text": "fixture"},
                "outputs": {"artifact": {"type": "asset", "path": "artifacts/result.txt"}},
            }))
            stdout = io.StringIO()
            with mock.patch.object(sys, "argv", [
                "mere-graph-conformance",
                "--provider", str(provider),
                "--invocation", str(invocation),
                "--run-dir", str(root / "run"),
                "--execute",
                "--json",
            ]):
                with contextlib.redirect_stdout(stdout):
                    exit_code = graph_conformance.main()

            result = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(result["checks"], ["catalog", "preflight", "execution"])
            self.assertEqual(result["fixture"]["event_count"], 2)
            self.assertTrue((root / "run/artifacts/result.txt").is_file())

    def test_provider_initializer_creates_safe_typed_starter(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            destination = pathlib.Path(raw_root) / "provider"
            graph_provider_init.create_provider(destination, "mere-example-tools", "example.write")
            cli_source = (destination / "src/mere_example_tools/cli.py").read_text()

            compile(cli_source, "generated-provider-cli.py", "exec")
            self.assertIn("mere-graph-conformance", (destination / "README.md").read_text())
            self.assertIn("example.write", cli_source)
            self.assertTrue((destination / "tests/test_provider.py").is_file())
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "not empty"):
                graph_provider_init.create_provider(destination, "mere-example-tools", "example.write")

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
        self.assertEqual(report["recommended_export"], "Save (API Format)")
        self.assertEqual(report["source_nodes"][0]["disposition"], "unsupported")
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

            catalog = graph_templates.catalog()
            template_ids = {item["id"] for item in catalog["templates"]}
            self.assertIn("image-variants", template_ids)

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

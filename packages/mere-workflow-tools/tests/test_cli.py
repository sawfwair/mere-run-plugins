from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from importlib.metadata import PackageNotFoundError
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image

from mere_workflow_tools import anydoc_backend, cli, doc_graph_provider, graph_provider, graph_sdk


class FakeConvertError(Exception):
    pass


class FakeNeedsOcrError(FakeConvertError):
    pass


@contextmanager
def fake_anydoc(markdown: str = "# Résumé\n\nAlice Smith, alice@example.com\n") -> Iterator[Mock]:
    convert = Mock(return_value=markdown)
    module = SimpleNamespace(to_markdown=convert, ConvertError=FakeConvertError, NeedsOcrError=FakeNeedsOcrError)
    with (
        patch.object(anydoc_backend.sys, "version_info", (3, 12)),
        patch.object(anydoc_backend, "version", return_value="0.2.4"),
        patch.object(anydoc_backend.importlib, "import_module", return_value=module),
    ):
        yield convert


def invoke_doc(argv: list[str]) -> tuple[int, str, str]:
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cli.main_for("doc", argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def document_invocation(source: pathlib.Path) -> graph_sdk.JsonMap:
    fixture = pathlib.Path(__file__).resolve().parents[3] / "examples/documents/convert.invocation.json"
    invocation = json.loads(fixture.read_text())
    invocation["arguments"]["input"] = str(source)
    return invocation


def validate_contract(name: str, payload: graph_sdk.JsonMap) -> None:
    schema_path = pathlib.Path(__file__).resolve().parents[3] / "contracts" / name
    Draft202012Validator(json.loads(schema_path.read_text()), format_checker=FormatChecker()).validate(payload)


def write_png(path: pathlib.Path, color: tuple[int, int, int] = (120, 140, 220)) -> None:
    Image.new("RGB", (32, 24), color).save(path)


def write_fake_mere_run(path: pathlib.Path) -> None:
    path.write_text(
        "import argparse, json, pathlib, sys\n"
        "from PIL import Image\n"
        "argv = sys.argv[1:]\n"
        "def value(flag, default=None):\n"
        "    return argv[argv.index(flag)+1] if flag in argv else default\n"
        "def outputs_after(flag):\n"
        "    out = []\n"
        "    if flag not in argv:\n"
        "        return out\n"
        "    start = argv.index(flag) + 2\n"
        "    for item in argv[start:]:\n"
        "        if item.startswith('--'):\n"
        "            continue\n"
        "        out.append(item)\n"
        "    return out\n"
        "if argv[:2] == ['vision', 'ocr']:\n"
        "    out_dir = pathlib.Path(value('--output-dir'))\n"
        "    out_dir.mkdir(parents=True, exist_ok=True)\n"
        "    images = [pathlib.Path(item) for item in argv if pathlib.Path(item).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}]\n"
        "    for image in images:\n"
        "        (out_dir / f'{image.stem}.txt').write_text('Alice Smith, alice@example.com, 555-1234')\n"
        "elif argv[:2] == ['text', 'anonymize']:\n"
        "    out = pathlib.Path(value('--output'))\n"
        "    out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    text = sys.stdin.read() or 'Alice Smith, alice@example.com'\n"
        "    redacted = text.replace('Alice Smith', '[NAME]').replace('alice@example.com', '[EMAIL]').replace('555-1234', '[PHONE]')\n"
        "    if '--json' in argv:\n"
        "        out.write_text(json.dumps({'redactedText': redacted, 'spans': [{'label': 'EMAIL'}]}))\n"
        "    else:\n"
        "        out.write_text(redacted)\n"
        "elif argv[:2] == ['vision', 'caption']:\n"
        "    out_dir = pathlib.Path(value('--output-dir'))\n"
        "    out_dir.mkdir(parents=True, exist_ok=True)\n"
        # Mirror mere.run's ArgumentParser semantics: --focus is greedy up to the
        # next option, so bare arguments after it never reach the positional list.
        "    positional = []\n"
        "    greedy = False\n"
        "    skip_value = False\n"
        "    for item in argv[2:]:\n"
        "        if skip_value:\n"
        "            skip_value = False\n"
        "        elif item.split('=', 1)[0] == '--focus':\n"
        "            greedy = True\n"
        "        elif item.startswith('--'):\n"
        "            greedy = False\n"
        "            skip_value = '=' not in item\n"
        "        elif not greedy:\n"
        "            positional.append(item)\n"
        "    images = [pathlib.Path(item) for item in positional if pathlib.Path(item).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}]\n"
        "    if not images:\n"
        "        raise SystemExit('Provide at least one image path.')\n"
        "    trigger = value('--trigger-token', '')\n"
        "    for image in images:\n"
        "        prefix = (trigger + ', ') if trigger else ''\n"
        "        (out_dir / f'{image.stem}.txt').write_text(prefix + 'a training image with clean details')\n"
        "elif argv[:2] == ['speech', 'transcribe']:\n"
        "    out = pathlib.Path(value('--output'))\n"
        "    out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    out.write_text('Alice Smith discusses a project at alice@example.com')\n"
        "elif argv[:2] == ['image', 'generate']:\n"
        "    out = pathlib.Path(value('--output'))\n"
        "    out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    Image.new('RGB', (32, 32), (30, 180, 120)).save(out)\n"
        "else:\n"
        "    raise SystemExit('unsupported fake mere.run argv: ' + ' '.join(argv))\n"
    )


class MereWorkflowToolsTests(unittest.TestCase):
    def test_manifests_have_common_commands(self) -> None:
        for _kind, spec in cli.TOOLS.items():
            manifest = cli.plugin_manifest(spec)
            self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
            self.assertEqual(manifest["name"], spec.plugin_name)
            names = {command["name"] for command in manifest["commands"]}
            self.assertTrue({"manifest", "doctor", "plan", "run", "resume", "cleanup", spec.one_shot}.issubset(names))
            self.assertEqual(manifest["security"]["cleanupDefault"], "none")
            if spec.kind in {"doc", "dataset"}:
                self.assertIn("graph", names)
                self.assertIn("graph-node-provider-v1", manifest["capabilities"])
                self.assertEqual(
                    manifest["graphProvider"]["contractVersion"],
                    graph_provider.CONTRACT_VERSION,
                )

    def test_dataset_graph_catalog_exposes_rich_typed_node(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            exit_code = cli.main_for("dataset", ["graph", "catalog", "--json"])
        self.assertEqual(exit_code, 0)
        catalog = json.loads(stdout.getvalue())
        self.assertEqual(catalog["contract_version"], graph_provider.CONTRACT_VERSION)
        self.assertEqual(catalog["provider_id"], "mere-dataset-tools")
        node = catalog["nodes"][0]
        self.assertEqual(node["kind"], "dataset.prepare")
        self.assertTrue(node["traits"]["cacheable"])
        self.assertEqual(
            {output["name"]: output["type"] for output in node["outputs"]},
            {
                "dataset": "asset_directory",
                "manifest": "asset",
                "contact_sheet": "asset",
                "stats": "json",
            },
        )

    def test_document_graph_catalog_and_template_are_discoverable(self) -> None:
        code, stdout, stderr = invoke_doc(["graph", "catalog", "--json"])
        self.assertEqual((code, stderr), (0, ""))
        catalog = json.loads(stdout)
        graph_sdk.validate_catalog(catalog)
        validate_contract("graph-node-provider.v1.schema.json", catalog)
        self.assertEqual(catalog["provider_id"], "mere-doc-tools")
        node = catalog["nodes"][0]
        self.assertEqual(node["kind"], "document.convert")
        self.assertEqual({output["name"]: output["type"] for output in node["outputs"]}, doc_graph_provider.OUTPUT_TYPES)
        self.assertFalse(node["traits"]["cacheable"])
        self.assertFalse(node["requirements"]["network_access"])
        code, stdout, stderr = invoke_doc(["graph", "templates", "list", "--json"])
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("document-to-markdown", stdout)

    def test_document_graph_preflight_execute_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc() as convert:
            root = pathlib.Path(tmp).resolve()
            source = root / "report.csv"
            source.write_text("item,quantity\nNotebook,3\n")
            invocation = document_invocation(source)
            validate_contract("graph-node-invocation.v1.schema.json", invocation)
            request = root / "invocation.json"
            request.write_text(json.dumps(invocation))
            run_dir = root / "node"
            code, stdout, stderr = invoke_doc(["graph", "preflight", "--request", str(request), "--run-dir", str(run_dir), "--json"])
            self.assertEqual((code, stderr), (0, ""))
            preflight = json.loads(stdout)
            graph_sdk.validate_preflight(preflight)
            validate_contract("graph-node-preflight.v1.schema.json", preflight)
            self.assertEqual(preflight["status"], "ok")
            convert.assert_not_called()
            self.assertFalse(run_dir.exists())

            def convert_with_receipt(path: str, *, ocr: str) -> str:
                self.assertEqual((path, ocr), (str(source), "reject"))
                pending = json.loads((run_dir / "artifacts/run.json").read_text())
                self.assertEqual(pending["status"], "running")
                return "# Résumé\n\nalice@example.com\n"

            convert.side_effect = convert_with_receipt
            code, stdout, stderr = invoke_doc(["graph", "execute", "--request", str(request), "--run-dir", str(run_dir), "--json-stream"])
            self.assertEqual((code, stderr), (0, ""))
            events = [json.loads(line) for line in stdout.splitlines()]
            graph_sdk.validate_event_stream(events, invocation, run_dir)
            for event in events:
                validate_contract("graph-node-event.v1.schema.json", event)
            result = events[-1]["outputs"]
            markdown = run_dir / result["markdown"]
            self.assertEqual(result["text"], markdown.read_text(encoding="utf-8"))
            self.assertIn("alice@example.com", result["text"])
            self.assertEqual(result["stats"]["input_sha256"], doc_graph_provider.file_sha256(source))
            self.assertEqual(result["stats"]["markdown_sha256"], doc_graph_provider.file_sha256(markdown))
            manifest_path = run_dir / result["manifest"]
            manifest = json.loads(manifest_path.read_text())
            validate_contract("run-manifest.v1.schema.json", manifest)
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["tool"]["backendVersion"], "0.2.4")
            self.assertFalse(manifest["tool"]["redact"])
            # Graph receipts remain usable by the regular lifecycle commands.
            for command in ("resume", "run", "cleanup"):
                code, stdout, stderr = invoke_doc([command, str(manifest_path)])
                self.assertEqual((code, stderr), (0, ""))
            self.assertEqual(convert.call_count, 2)
            self.assertEqual(source.read_text(), "item,quantity\nNotebook,3\n")

    def test_document_graph_rejects_unsafe_invocations_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc() as convert:
            root = pathlib.Path(tmp).resolve()
            source = root / "report.csv"
            source.write_text("item,quantity\nNotebook,3\n")
            node = root / "node"
            node.mkdir()
            (node / "escape").symlink_to(root, target_is_directory=True)
            os.link(source, node / "source-alias.md")
            cases = []
            for path in ("../report.csv", str(source), "escape/report.csv", "source-alias.md", "./out.md", "a//out.md", "a\\out.md", ""):
                invocation = document_invocation(source)
                invocation["outputs"]["markdown"]["path"] = path
                cases.append(invocation)
            for path in ("artifacts/document.md", "artifacts/document.md/child"):
                invocation = document_invocation(source)
                invocation["outputs"]["manifest"]["path"] = path
                cases.append(invocation)
            for arguments in ({"input": str(source), "ocr": "hosted"}, {"input": str(root / "missing")}, {"input": 1}):
                invocation = document_invocation(source)
                invocation["arguments"] = arguments
                cases.append(invocation)
            for name, value in (("job_id", "not-a-uuid"), ("node_id", "../escape"), ("kind", "dataset.prepare")):
                invocation = document_invocation(source)
                invocation[name] = value
                cases.append(invocation)
            invocation = document_invocation(source)
            invocation["outputs"]["text"]["path"] = "text.txt"
            cases.append(invocation)
            invocation = document_invocation(source)
            invocation["outputs"]["markdown"]["type"] = "string"
            cases.append(invocation)
            invocation = document_invocation(source)
            del invocation["outputs"]["stats"]
            cases.append(invocation)
            for invocation in cases:
                with self.subTest(invocation=invocation):
                    result = doc_graph_provider.graph_preflight(invocation, node)
                    graph_sdk.validate_preflight(result)
                    self.assertEqual(result["status"], "blocked")
            convert.assert_not_called()
            self.assertFalse((node / "artifacts").exists())
            self.assertEqual(source.read_text(), "item,quantity\nNotebook,3\n")

    def test_document_graph_missing_backend_and_conversion_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc() as convert:
            root = pathlib.Path(tmp)
            source = root / "report.csv"
            source.write_text("item,quantity\nNotebook,3\n")
            invocation = document_invocation(source)
            request = root / "invocation.json"
            request.write_text(json.dumps(invocation))
            node = root / "node"
            with patch.object(anydoc_backend, "version", side_effect=PackageNotFoundError("firecrawl-anydoc")):
                result = doc_graph_provider.graph_preflight(invocation, node)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["diagnostics"][0]["id"], "anydoc_unavailable")
                with self.assertRaises(graph_sdk.GraphProviderError):
                    doc_graph_provider.graph_execute(invocation, node, Mock())
            self.assertFalse(node.exists())
            convert.side_effect = FakeNeedsOcrError("scanned page")
            code, stdout, stderr = invoke_doc(["graph", "execute", "--request", str(request), "--run-dir", str(node), "--json-stream"])
            self.assertEqual(code, 1)
            self.assertIn("Hosted OCR is disabled", stderr)
            events = [json.loads(line) for line in stdout.splitlines()]
            self.assertEqual(events[-1]["type"], "diagnostic")
            self.assertNotIn("node_result", [event["type"] for event in events])
            manifest = json.loads((node / "artifacts/run.json").read_text())
            validate_contract("run-manifest.v1.schema.json", manifest)
            self.assertEqual(manifest["status"], "failed")
            self.assertFalse((node / "artifacts/document.md").exists())
            convert.side_effect = None
            events = []
            doc_graph_provider.graph_execute(invocation, node, events.append)
            graph_sdk.validate_event_stream(events, invocation, node)
            manifest = json.loads((node / "artifacts/run.json").read_text())
            self.assertEqual(manifest["status"], "succeeded")
            self.assertNotIn("error", manifest)

    def test_document_graph_detects_source_changes_during_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc() as convert:
            root = pathlib.Path(tmp)
            source = root / "report.csv"
            source.write_text("item,quantity\nNotebook,3\n")
            invocation = document_invocation(source)

            def change_source(path: str, *, ocr: str) -> str:
                self.assertEqual(ocr, "reject")
                pathlib.Path(path).write_text("Changed during conversion")
                return "# Original content"

            convert.side_effect = change_source
            with self.assertRaisesRegex(graph_sdk.GraphProviderError, "changed during conversion"):
                doc_graph_provider.graph_execute(invocation, root / "node", Mock())
            manifest = json.loads((root / "node/artifacts/run.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["artifacts"]["files"], [])

    def test_graph_template_publish_writes_confined_portable_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            graph = root / "source.workflow.json"
            inputs = root / "source.inputs.json"
            graph.write_text(json.dumps({
                "schema_version": 1,
                "kind": "mere.run/workflow-graph",
                "name": "Fixture",
                "inputs": {"prompt": {"type": "string"}},
                "nodes": [],
                "outputs": {},
            }))
            inputs.write_text('{"prompt":"published"}')
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main_for("dataset", [
                    "graph", "templates", "publish",
                    "--graph", str(graph),
                    "--inputs-json", str(inputs),
                    "--output-dir", str(root / "templates"),
                    "--template-id", "fixture-template",
                    "--title", "Fixture template",
                    "--description", "A deterministic fixture template.",
                    "--tag", "fixture",
                    "--json",
                ])

            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["package"]["contract_version"], "mere.run/graph-template-package.v1")
            self.assertTrue((root / "templates/fixture-template.workflow.json").is_file())
            self.assertEqual(
                json.loads((root / "templates/fixture-template.inputs.json").read_text()),
                {"prompt": "published"},
            )

    def test_dataset_graph_preflight_and_execute_stream_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source"
            source.mkdir()
            write_png(source / "b.png", (20, 40, 80))
            write_png(source / "a.png", (80, 40, 20))
            (source / "a.txt").write_text("first caption\n")
            (source / "b.txt").write_text("second caption\n")
            node_run = root / "node"
            invocation = {
                "contract_version": graph_provider.INVOCATION_VERSION,
                "job_id": "11111111-2222-3333-4444-555555555555",
                "node_id": "prepare-data",
                "kind": "dataset.prepare",
                "arguments": {
                    "data": str(source),
                    "trigger_token": "STYLE",
                    "contact_sheet": True,
                },
                "outputs": {
                    "dataset": {"type": "asset_directory", "path": "artifacts/dataset"},
                    "manifest": {"type": "asset", "path": "artifacts/dataset-manifest.json"},
                    "contact_sheet": {
                        "type": "asset",
                        "path": "artifacts/contact-sheet.jpg",
                        "optional": True,
                    },
                    "stats": {"type": "json"},
                },
            }
            request = root / "invocation.json"
            request.write_text(json.dumps(invocation))

            preflight_stdout = StringIO()
            with redirect_stdout(preflight_stdout), redirect_stderr(StringIO()):
                exit_code = cli.main_for(
                    "dataset",
                    ["graph", "preflight", "--request", str(request), "--run-dir", str(node_run), "--json"],
                )
            self.assertEqual(exit_code, 0)
            preflight = json.loads(preflight_stdout.getvalue())
            self.assertEqual(preflight["status"], "ok")
            self.assertEqual(preflight["requirements"]["model_ids"], [])

            execute_stdout = StringIO()
            with redirect_stdout(execute_stdout), redirect_stderr(StringIO()):
                exit_code = cli.main_for(
                    "dataset",
                    [
                        "graph",
                        "execute",
                        "--request",
                        str(request),
                        "--run-dir",
                        str(node_run),
                        "--json-stream",
                    ],
                )
            self.assertEqual(exit_code, 0)
            events = [json.loads(line) for line in execute_stdout.getvalue().splitlines()]
            self.assertEqual([event["sequence"] for event in events], list(range(len(events))))
            self.assertEqual(events[-1]["type"], "node_result")
            self.assertEqual(events[-1]["outputs"]["stats"]["pair_count"], 2)
            self.assertEqual(events[-1]["outputs"]["dataset"], "artifacts/dataset")
            self.assertTrue((node_run / "artifacts/dataset/a.png").is_file())
            self.assertEqual((node_run / "artifacts/dataset/a.txt").read_text(), "STYLE, first caption\n")
            self.assertTrue((node_run / "artifacts/dataset-manifest.json").is_file())
            self.assertTrue((node_run / "artifacts/contact-sheet.jpg").is_file())

    def test_dataset_graph_preflight_blocks_missing_caption_and_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "source"
            source.mkdir()
            write_png(source / "frame.png")
            invocation = {
                "contract_version": graph_provider.INVOCATION_VERSION,
                "job_id": "11111111-2222-3333-4444-555555555555",
                "node_id": "prepare-data",
                "kind": "dataset.prepare",
                "arguments": {"data": str(source)},
                "outputs": {
                    "dataset": {"type": "asset_directory", "path": "../escape"},
                    "manifest": {"type": "asset", "path": "artifacts/manifest.json"},
                    "contact_sheet": {"type": "asset", "optional": True},
                    "stats": {"type": "json"},
                },
            }
            preflight = graph_provider.graph_preflight(invocation, root / "node")
            self.assertEqual(preflight["status"], "blocked")
            identifiers = {item["id"] for item in preflight["diagnostics"]}
            self.assertEqual(identifiers, {"dataset_caption_missing", "output_invalid"})

    def test_anydoc_plan_and_dry_run_do_not_load_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(anydoc_backend, "load_backend") as load:
            root = pathlib.Path(tmp)
            source = root / "report.csv"
            source.write_text("name,value\nexample,42\n")
            for command in ("plan", "process"):
                output = root / command
                args = [
                    command, "--input", str(source), "--output-dir", str(output),
                    "--extractor", "anydoc", "--no-redact", "--replacement", "<{label}>",
                    "--mere-run-command", "missing-mere-run",
                ]
                if command == "process":
                    args.append("--dry-run")
                code, stdout, stderr = invoke_doc(args)
                self.assertEqual(code, 0, stderr)
                manifest = json.loads(stdout)
                self.assertEqual(manifest["status"], "planned")
                self.assertEqual(manifest["recipe"]["id"], "doc-anydoc-markdown")
                self.assertEqual(manifest["tool"]["backend"], "anydoc")
                self.assertEqual(manifest["steps"], [{
                    "name": "convert-markdown", "python": "anydoc-markdown",
                    "inputs": [str(source.resolve())],
                    "outputs": {"markdown": str(output.resolve() / "report.md")},
                }])
                recorded = cli.build_parser(cli.TOOLS["doc"]).parse_args(manifest["command"][1:])
                self.assertEqual(recorded.extractor, "anydoc")
                self.assertFalse(recorded.redact)
                self.assertEqual(recorded.replacement, "<{label}>")
                manifest_path = output / "run.json"
                self.assertEqual(json.loads(manifest_path.read_text()), manifest)
                code, stdout, stderr = invoke_doc(["run", str(manifest_path), "--dry-run"])
                self.assertEqual(code, 0, stderr)
                self.assertEqual(json.loads(stdout), manifest)
                self.assertFalse((output / "report.md").exists())
            load.assert_not_called()

    def test_anydoc_conversion_lifecycle_hashes_and_local_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc() as convert:
            root = pathlib.Path(tmp)
            source = root / "report.docx"
            source.write_bytes(b"synthetic document handled by fake backend")
            output = root / "out"
            manifest_path = output / "run.json"

            def convert_after_manifest(path: str, *, ocr: str) -> str:
                self.assertEqual(path, str(source.resolve()))
                self.assertEqual(ocr, "reject")
                self.assertEqual(json.loads(manifest_path.read_text())["status"], "running")
                return "# Résumé\n\nLocal document.\n"

            convert.side_effect = convert_after_manifest
            with patch.object(cli, "run_mere_step") as mere_step:
                code, stdout, stderr = invoke_doc([
                    "process", "--input", str(source), "--output-dir", str(output),
                    "--extractor", "anydoc", "--no-redact", "--mere-run-command", "missing-mere-run",
                ])
                self.assertEqual(code, 0, stderr)
                mere_step.assert_not_called()
            manifest = json.loads(stdout)
            markdown = output / "report.md"
            self.assertEqual(markdown.read_text(encoding="utf-8"), "# Résumé\n\nLocal document.\n")
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["tool"]["backendVersion"], "0.2.4")
            self.assertEqual(manifest["artifacts"]["sha256"], {str(markdown.resolve()): cli.file_sha256(markdown)})
            self.assertEqual(manifest["artifacts"]["files"], [str(markdown.resolve())])
            with patch.object(anydoc_backend, "load_backend") as load:
                code, stdout, stderr = invoke_doc(["resume", str(manifest_path)])
                self.assertEqual(code, 0, stderr)
                self.assertEqual(json.loads(stdout)["status"], "succeeded")
                for _ in range(2):
                    code, stdout, stderr = invoke_doc(["cleanup", str(manifest_path)])
                    self.assertEqual(code, 0, stderr)
                    self.assertEqual(json.loads(stdout)["cleanup"]["status"], "skipped")
                load.assert_not_called()
            self.assertTrue(markdown.is_file())
            self.assertEqual(source.read_bytes(), b"synthetic document handled by fake backend")

    def test_anydoc_redaction_stays_on_native_mere_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc() as convert:
            root = pathlib.Path(tmp)
            source = root / "report.docx"
            source.write_bytes(b"fake document")
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            output = root / "out"
            code, stdout, stderr = invoke_doc([
                "process", "--input", str(source), "--output-dir", str(output), "--extractor", "anydoc",
                "--mere-run-command", f"{sys.executable} {fake}",
            ])
            self.assertEqual(code, 0, stderr)
            convert.assert_called_once_with(str(source.resolve()), ocr="reject")
            manifest = json.loads(stdout)
            self.assertEqual([step["name"] for step in manifest["steps"]], ["convert-markdown", "redact-text", "redact-json"])
            self.assertIn("alice@example.com", (output / "report.md").read_text())
            self.assertIn("[EMAIL]", (output / "report.redacted.md").read_text())
            self.assertEqual(json.loads((output / "report.pii.json").read_text())["spans"], [{"label": "EMAIL"}])
            self.assertEqual(len(manifest["artifacts"]["sha256"]), 3)

    def test_anydoc_missing_dependency_records_failure_and_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc():
            root = pathlib.Path(tmp)
            source = root / "report.csv"
            source.write_text("column\nvalue\n")
            output = root / "out"
            manifest_path = output / "run.json"
            with patch.object(anydoc_backend, "version", side_effect=PackageNotFoundError("firecrawl-anydoc")):
                code, stdout, stderr = invoke_doc([
                    "process", "--input", str(source), "--output-dir", str(output),
                    "--extractor", "anydoc", "--no-redact",
                ])
            self.assertEqual(code, 3)
            self.assertEqual(stdout, "")
            self.assertIn("pipx inject", stderr)
            self.assertEqual(json.loads(manifest_path.read_text())["status"], "failed")
            self.assertFalse((output / "report.md").exists())
            code, stdout, stderr = invoke_doc(["run", str(manifest_path)])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout)["status"], "succeeded")
            self.assertNotIn("error", json.loads(manifest_path.read_text()))

    def test_anydoc_failures_do_not_fall_back_to_hosted_or_native_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc() as convert:
            root = pathlib.Path(tmp)
            source = root / "scan.pdf"
            source.write_bytes(b"synthetic scanned PDF")
            for index, error in enumerate((FakeNeedsOcrError("page 1"), FakeConvertError("encrypted"), OSError("unreadable"))):
                with self.subTest(error=error), patch.object(cli, "run_mere_step") as mere_step:
                    convert.side_effect = error
                    output = root / str(index)
                    code, stdout, stderr = invoke_doc([
                        "process", "--input", str(source), "--output-dir", str(output),
                        "--extractor", "anydoc", "--no-redact",
                    ])
                    self.assertEqual(code, 1)
                    self.assertEqual(stdout, "")
                    self.assertIn(str(error), stderr)
                    if isinstance(error, FakeNeedsOcrError):
                        self.assertIn("Hosted OCR is disabled", stderr)
                    self.assertEqual(json.loads((output / "run.json").read_text())["status"], "failed")
                    self.assertFalse((output / "scan.md").exists())
                    mere_step.assert_not_called()
                    self.assertEqual(convert.call_args.kwargs, {"ocr": "reject"})

    def test_anydoc_doctor_checks_only_selected_dependencies(self) -> None:
        with fake_anydoc() as convert, patch.object(cli, "command_available", return_value=False):
            code, stdout, stderr = invoke_doc(["doctor", "--extractor", "anydoc", "--no-redact"])
            self.assertEqual(code, 0, stderr)
            self.assertEqual([check["name"] for check in json.loads(stdout)["checks"]], ["python", "anydoc"])
            for args in (["doctor"], ["doctor", "--extractor", "anydoc"]):
                code, stdout, stderr = invoke_doc(args)
                self.assertEqual(code, 3, stderr)
                self.assertFalse(json.loads(stdout)["ok"])
                self.assertEqual(json.loads(stdout)["checks"][-1]["name"], "mere.run")
            with patch.object(anydoc_backend, "version", side_effect=PackageNotFoundError("firecrawl-anydoc")):
                code, stdout, stderr = invoke_doc(["doctor", "--extractor", "anydoc", "--no-redact"])
                self.assertEqual(code, 3, stderr)
                self.assertIn("Python 3.10+", json.loads(stdout)["checks"][-1]["detail"])
            convert.assert_not_called()

    def test_anydoc_backend_rejects_unsupported_runtime_or_module(self) -> None:
        with fake_anydoc():
            with patch.object(anydoc_backend.sys, "version_info", (3, 9)):
                with self.assertRaisesRegex(anydoc_backend.AnyDocError, "Python 3.10"):
                    anydoc_backend.load_backend()
            with patch.object(anydoc_backend.importlib, "import_module", return_value=SimpleNamespace()):
                with self.assertRaisesRegex(anydoc_backend.AnyDocError, "incompatible"):
                    anydoc_backend.load_backend()

    def test_anydoc_does_not_write_invalid_markdown_or_overwrite_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, fake_anydoc() as convert:
            root = pathlib.Path(tmp)
            source = root / "document.md"
            source.write_text("source must survive")
            for markdown in ("", "  \n", None):
                convert.return_value = markdown
                with self.assertRaisesRegex(anydoc_backend.AnyDocError, "no Markdown"):
                    anydoc_backend.convert(source, root / "out.md")
                self.assertFalse((root / "out.md").exists())
            with self.assertRaisesRegex(anydoc_backend.AnyDocError, "overwrite"):
                anydoc_backend.convert(source, source)
            alias = root / "source-alias.md"
            os.link(source, alias)
            with self.assertRaisesRegex(anydoc_backend.AnyDocError, "overwrite"):
                anydoc_backend.convert(source, alias)
            for args in (
                ["--output-dir", str(root)],
                ["--output-dir", str(root / "out"), "--manifest", str(source)],
                ["--output-dir", str(root / "out"), "--manifest", str(alias)],
            ):
                code, stdout, stderr = invoke_doc([
                    "plan", "--input", str(source), "--extractor", "anydoc", "--no-redact", *args,
                ])
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("overwrite", stderr)
                self.assertEqual(source.read_text(), "source must survive")
            code, stdout, stderr = invoke_doc([
                "plan", "--input", str(source), "--extractor", "anydoc", "--no-redact",
                "--output-dir", str(root / "out"), "--manifest", str(root / "out" / "document.md"),
            ])
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("distinct", stderr)
            out = root / "out"
            out.mkdir()
            (out / "document.md").write_text("previous output")
            os.link(out / "document.md", out / "run.json")
            code, stdout, stderr = invoke_doc([
                "plan", "--input", str(source), "--extractor", "anydoc", "--no-redact", "--output-dir", str(out),
            ])
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("distinct", stderr)

    def test_anydoc_step_requires_one_input_and_markdown_output(self) -> None:
        for inputs, outputs in (([], {"markdown": "out.md"}), (["a", "b"], {"markdown": "out.md"}), (["a"], {})):
            with self.subTest(inputs=inputs, outputs=outputs):
                with self.assertRaisesRegex(cli.PluginError, "one input"):
                    cli.run_anydoc_step({}, {"inputs": inputs, "outputs": outputs})

    def test_all_workflows_execute_with_fake_mere_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            command = f"{sys.executable} {fake}"

            image = root / "doc.png"
            write_png(image)
            media = root / "media"
            media.mkdir()
            write_png(media / "a.png")
            write_png(media / "b.png", (200, 100, 80))
            audio = root / "clip.wav"
            audio.write_bytes(b"fake wav")
            jobs = root / "jobs.jsonl"
            batch_output = root / "batch" / "redacted.txt"
            jobs.write_text(json.dumps({
                "argv": ["text", "anonymize", "--output", str(batch_output)],
                "outputs": {"redacted": str(batch_output)},
            }) + "\n")

            cases = [
                ("doc", ["process", "--input", str(image), "--output-dir", str(root / "doc-out")]),
                ("media", ["scrub", "--input", str(media), "--output-dir", str(root / "media-out")]),
                (
                    "dataset",
                    [
                        "caption",
                        "--input",
                        str(media),
                        "--output-dir",
                        str(root / "dataset-out"),
                        "--trigger-token",
                        "TESTSTYLE",
                        "--focus",
                        "card border",
                        "--focus",
                        "printed title",
                        "--ocr",
                    ],
                ),
                ("transcript", ["transcribe", "--input", str(audio), "--output-dir", str(root / "transcript-out")]),
                (
                    "image_compose",
                    [
                        "generate",
                        "--prompt",
                        "a polished local image",
                        "--output-dir",
                        str(root / "image-out"),
                        "--seed",
                        "42",
                    ],
                ),
                ("batch", ["run-jobs", "--jobs", str(jobs), "--output-dir", str(root / "batch-out")]),
            ]

            for kind, args in cases:
                stdout = StringIO()
                full_args = args + ["--mere-run-command", command, "--run-id", f"unit-{kind}"]
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    exit_code = cli.main_for(kind, full_args)
                self.assertEqual(exit_code, 0, kind)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["status"], "succeeded", kind)
                self.assertGreater(len(payload["artifacts"]["files"]), 0, kind)
                self.assertEqual(payload["cleanup"]["default"], "none", kind)

    def test_dataset_caption_step_keeps_image_paths_before_focus(self) -> None:
        # Regression: --focus is variadic in mere.run (up to next option), so any
        # image path emitted after it is swallowed and captioning exits 64.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            media = root / "media"
            media.mkdir()
            write_png(media / "a.png")
            write_png(media / "b.png")
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main_for("dataset", [
                    "plan",
                    "--input",
                    str(media),
                    "--output-dir",
                    str(root / "out"),
                    "--trigger-token",
                    "TESTSTYLE",
                    "--focus",
                    "card border",
                    "--focus",
                    "printed title",
                    "--mere-run-command",
                    "missing-mere-run",
                    "--run-id",
                    "unit-focus",
                ])
            self.assertEqual(exit_code, 0)
            manifest = json.loads(stdout.getvalue())
            caption_step = next(step for step in manifest["steps"] if step["name"] == "caption")
            argv = caption_step["argv"]
            focus_indexes = [index for index, item in enumerate(argv) if item.startswith("--focus")]
            self.assertEqual(
                [argv[index] for index in focus_indexes],
                ["--focus=card border", "--focus=printed title"],
            )
            image_indexes = [index for index, item in enumerate(argv) if item.endswith(".png")]
            self.assertEqual(len(image_indexes), 2)
            self.assertLess(max(image_indexes), min(focus_indexes))
            # Nothing may trail the focus flags, or the greedy parser would eat it.
            self.assertTrue(all(item.startswith("--focus=") for item in argv[min(focus_indexes):]))

    def test_plan_does_not_require_mere_run_command_to_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "doc.png"
            write_png(source)
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main_for("doc", [
                    "plan",
                    "--input",
                    str(source),
                    "--output-dir",
                    str(root / "out"),
                    "--mere-run-command",
                    "missing-mere-run",
                    "--run-id",
                    "unit-plan",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["tool"]["backend"], "mere.run")


if __name__ == "__main__":
    unittest.main()

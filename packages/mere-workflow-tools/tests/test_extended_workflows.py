from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from mere_workflow_tools import cli, doc_graph_provider, graph_sdk, structured_documents, transcript_formats


def invoke(kind: str, arguments: list[str]) -> tuple[int, dict[str, object], str]:
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        status = cli.main_for(kind, arguments)
    return status, json.loads(stdout.getvalue() or "{}"), stderr.getvalue()


class ExtendedWorkflowTests(unittest.TestCase):
    def test_workflow_command_uses_the_configured_runtime_without_path(self) -> None:
        executable = "/some directory/Contents/Helpers/mere.run"
        with patch.dict(os.environ, {"MERE_RUN_EXECUTABLE": executable, "PATH": ""}, clear=True):
            arguments = cli.normalize_args(argparse.Namespace(mere_run_command=None))
        self.assertEqual(shlex.split(arguments.mere_run_command), [executable])

    def test_batch_captions_keep_source_identity_and_never_export_raw_redacted_cues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "recordings"
            source.mkdir()
            (source / "same.wav").touch()
            (source / "same.mp3").touch()
            runtime = root / "fake.py"
            runtime.write_text(
                "import json, pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "output = pathlib.Path(args[args.index('--output') + 1])\n"
                "if args[:2] == ['speech', 'transcribe']:\n"
                "    assert args[args.index('--backend') + 1] == 'nemotron' and '--timestamps' in args\n"
                "    output.write_text('Alice Example\\n\\n[00:00.100 --> 00:00.900] Alice Example\\n')\n"
                "elif args[:2] == ['speech', 'diarize']:\n"
                "    output.write_text(json.dumps({'segments': [{'start_seconds':0,'end_seconds':1,'speaker_index':0}]}))\n"
                "else:\n"
                "    output.write_text(sys.stdin.read().replace('Alice Example', '[NAME]'))\n"
            )
            output = root / "runs"
            result, manifest, stderr = invoke("transcript", [
                "transcribe", "--input", str(source), "--output-dir", str(output),
                "--mere-run-command", f"{sys.executable} {runtime}", "--backend", "nemotron",
                "--diarize", "--subtitles", "both",
            ])
            self.assertEqual(result, 0, stderr)
            self.assertEqual(manifest["status"], "succeeded")
            for extension in ("wav", "mp3"):
                srt = (output / f"same.{extension}" / "same.redacted.srt").read_text()
                self.assertIn("00:00:00,100 --> 00:00:00,900\nSpeaker 1: [NAME]", srt)
                self.assertNotIn("Alice", srt)
                self.assertIn("WEBVTT", (output / f"same.{extension}" / "same.redacted.vtt").read_text())

    def test_caption_generation_refuses_missing_timing_or_redaction_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "subtitle.vtt"
            output.write_text("Plain transcript")
            with self.assertRaisesRegex(ValueError, "no timed alignment"):
                transcript_formats.read_cues(output)
            with self.assertRaisesRegex(ValueError, "no longer align"):
                transcript_formats.write_subtitles(output, [transcript_formats.Cue(0, 10, "Alice")], [], [])

    def test_doc_extraction_routes_only_reviewable_fields_and_protects_csv_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "invoice.pdf"
            source.write_bytes(b"PDF fixture")
            fields = root / "fields.json"
            fields.write_text(json.dumps({"vendor": {"type": "text"}}))
            tasks = root / "tasks.json"
            tasks.write_text(json.dumps([{"name": "queue", "labels": ["finance", "other"]}]))
            request = {"truncated": False, "answers": {"vendor": {"value": "=VENDOR", "valid": True, "complete": True}}}
            heads = {"heads": {"queue": {"labels": ["finance"], "probabilities": {"finance": 0.9}}}}
            def fake_native(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                payload = json.loads(str(kwargs["input"]))
                if "extract" in args:
                    self.assertEqual(payload["documents"], [str(source.resolve())])
                    value = request
                else:
                    self.assertEqual(json.loads(payload["text"]), {"vendor": "=VENDOR"})
                    value = heads
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps(value), stderr="")

            output = root / "fields"
            with patch.object(structured_documents.subprocess, "run", side_effect=fake_native) as native:
                result, manifest, stderr = invoke("doc", [
                    "extract-fields", "--input", str(source), "--fields-json", str(fields),
                    "--classify-json", str(tasks), "--output-dir", str(output),
                ])
                self.assertEqual(result, 0, stderr)
                self.assertEqual(manifest["status"], "succeeded")
                self.assertEqual(native.call_count, 2)
                review = json.loads((output / "review.json").read_text())
                self.assertEqual(review["classification_status"], "completed")
                with (output / "fields.csv").open(newline="") as handle:
                    self.assertEqual(list(csv.reader(handle))[1][0], "'=VENDOR")
                request["truncated"] = True
                native.reset_mock()
                result, _, stderr = invoke("doc", [
                    "run", str(output / "run.json"),
                ])
                self.assertEqual(result, 0, stderr)
                self.assertEqual(native.call_count, 1)
                review = json.loads((output / "review.json").read_text())
                self.assertEqual(review["needs_review"], ["vendor"])
                self.assertEqual(review["classification_status"], "awaiting_review")

    def test_structured_graph_preflight_and_execution_emit_all_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "invoice.txt"
            source.write_text("Total: 12")
            invocation = {
                "contract_version": graph_sdk.INVOCATION_CONTRACT_VERSION,
                "kind": "document.extract", "job_id": "8fd84952-e9ca-4f14-9e77-32380a576d8b", "node_id": "extract",
                "arguments": {"input": str(source), "fields": {"total": {"type": "number"}}},
                "outputs": {name: {"type": "asset", "path": str(path), "optional": False} for name, path in
                            {"csv": "fields.csv", "review": "review.json", "manifest": "manifest.json"}.items()},
            }
            request_path = root / "invocation.json"
            request_path.write_text(json.dumps(invocation))
            invocation = doc_graph_provider.load_invocation(request_path)
            events: list[dict[str, object]] = []
            with patch.object(structured_documents, "native_request", return_value={
                "truncated": False, "answers": {"total": {"value": 12, "valid": True, "complete": True}},
            }) as native:
                preflight = doc_graph_provider.graph_preflight(invocation, root)
                self.assertEqual(preflight["status"], "ok")
                self.assertTrue(native.call_args.kwargs["preflight"])
                doc_graph_provider.graph_execute(invocation, root, events.append)
            self.assertEqual(events[-1]["type"], "node_result")
            self.assertEqual(events[-1]["outputs"], {"review": "review.json", "csv": "fields.csv", "manifest": "manifest.json"})

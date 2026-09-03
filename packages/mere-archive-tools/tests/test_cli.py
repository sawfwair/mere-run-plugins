from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from jsonschema import Draft202012Validator

from mere_archive_tools import benchmark, cli, extractors, runtime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def write_fake_mere_run(path: pathlib.Path) -> None:
    path.write_text(
        "import json, math, os, pathlib, re, sys\n"
        "args = sys.argv[1:]\n"
        "log = os.environ.get('FAKE_MERE_RUN_LOG')\n"
        "if log:\n"
        "    with open(log, 'a') as handle: handle.write(json.dumps(args) + '\\n')\n"
        "if args and args[-1] == '--help': raise SystemExit(0)\n"
        "if args[:2] == ['text', 'anonymize']:\n"
        "    text = sys.stdin.read()\n"
        "    text = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+', '[EMAIL]', text)\n"
        "    text = re.sub(r'800-555-[0-9]{4}', '[PHONE]', text)\n"
        "    print(text)\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['vision', 'caption']:\n"
        "    output = pathlib.Path(args[args.index('--output-dir') + 1])\n"
        "    image = pathlib.Path(args[-1])\n"
        "    output.mkdir(parents=True, exist_ok=True)\n"
        "    (output / (image.stem + '.txt')).write_text('Blue pump in Halifax owned by dana@example.com')\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['vision', 'ocr']:\n"
        "    print('Service label 800-555-0199')\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['vision', 'embed']:\n"
        "    dimensions = int(args[args.index('--dimensions') + 1])\n"
        "    records = json.loads(sys.stdin.read())['inputs']\n"
        "    data = []\n"
        "    for index, record in enumerate(records):\n"
        "        value = (record.get('text') or record.get('image') or '').lower()\n"
        "        vector = [0.0] * dimensions\n"
        "        vector[0] = 1.0 if 'halifax' in value else 0.05\n"
        "        if dimensions > 1: vector[1] = 1.0 if 'pump' in value else 0.05\n"
        "        if dimensions > 2: vector[2] = 1.0 if 'warehouse' in value else 0.05\n"
        "        if dimensions > 3: vector[3] = 1.0 if record.get('image') else 0.05\n"
        "        norm = math.sqrt(sum(item * item for item in vector)) or 1.0\n"
        "        vector = [item / norm for item in vector]\n"
        "        data.append({'index': index, 'embedding': vector})\n"
        "    print(json.dumps({'object': 'list', 'dimensions': dimensions, 'data': data}))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit('unexpected mere.run command: ' + repr(args))\n"
    )


def invoke(arguments: list[str]) -> tuple[int, dict[str, object], str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = cli.main(arguments)
    payload = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
    return exit_code, payload, stderr.getvalue()


class MereArchiveToolsCLITests(unittest.TestCase):
    def test_common_identifier_reduction_catches_classifier_misses(self) -> None:
        source = "Contact dana@example.com or 800-555-0199; backup: (902) 555-0142."
        reduced = runtime.reduce_common_identifiers(source, "[{label}]")
        self.assertEqual(
            reduced,
            "Contact [private_email] or [private_phone]; backup: [private_phone].",
        )

    def test_manifest_has_required_commands_and_security_contract(self) -> None:
        manifest = cli.plugin_manifest()
        names = {command["name"] for command in manifest["commands"]}
        required = {
            "manifest",
            "doctor",
            "plan",
            "run",
            "resume",
            "cleanup",
            "index",
            "search",
            "stats",
            "benchmark",
        }
        self.assertTrue(required.issubset(names))
        self.assertIn("pii-reduction", manifest["capabilities"])
        self.assertEqual(manifest["security"]["createsPaidResources"], False)

    def test_plan_defaults_to_safe_content_and_rejects_source_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "shared"
            source.mkdir()
            (source / "proposal.txt").write_text("Proposal")
            exit_code, payload, _ = invoke(
                [
                    "plan",
                    "--source",
                    str(source),
                    "--database",
                    str(root / "archive.sqlite3"),
                    "--output-dir",
                    str(root / "run"),
                    "--run-id",
                    "unit-plan",
                    "--mere-run-command",
                    "fake-mere-run",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["settings"]["storageTier"], "safe-content")
            self.assertEqual(payload["privacy"]["piiReduction"], "required-before-persistence")
            self.assertTrue((root / "run" / "run.json").is_file())

            exit_code, _, stderr = invoke(
                [
                    "plan",
                    "--source",
                    str(source),
                    "--database",
                    str(source / "archive.sqlite3"),
                    "--output-dir",
                    str(root / "other-run"),
                ]
            )
            self.assertEqual(exit_code, 2)
            self.assertIn("outside the read-only source tree", stderr)

            copied_manifest = source / "run.json"
            copied_manifest.write_bytes((root / "run" / "run.json").read_bytes())
            original_manifest = copied_manifest.read_bytes()
            exit_code, _, stderr = invoke(["run", str(copied_manifest)])
            self.assertEqual(exit_code, 2)
            self.assertIn("run manifest must be outside", stderr)
            self.assertEqual(copied_manifest.read_bytes(), original_manifest)

            exit_code, _, stderr = invoke(["cleanup", str(copied_manifest)])
            self.assertEqual(exit_code, 2)
            self.assertIn("run manifest must be outside", stderr)
            self.assertEqual(copied_manifest.read_bytes(), original_manifest)

    def test_full_content_indexes_deduplicates_searches_and_preserves_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "shared"
            source.mkdir()
            sensitive = "Halifax blue pump owner dana@example.com"
            first = source / "proposal.txt"
            duplicate = source / "proposal-copy.txt"
            image = source / "pump.jpg"
            first.write_text(sensitive)
            duplicate.write_text(sensitive)
            image.write_bytes(b"synthetic-image")
            original = {path: path.read_bytes() for path in (first, duplicate, image)}
            fake = root / "fake_mere_run.py"
            log = root / "mere-run.log"
            write_fake_mere_run(fake)
            database_path = root / "archive.sqlite3"
            command = f"{sys.executable} {fake}"
            with patch.dict(os.environ, {"FAKE_MERE_RUN_LOG": str(log)}):
                exit_code, payload, _ = invoke(
                    [
                        "index",
                        "--source",
                        str(source),
                        "--database",
                        str(database_path),
                        "--output-dir",
                        str(root / "run"),
                        "--storage-tier",
                        "full-content",
                        "--image-index",
                        "visual",
                        "--dimensions",
                        "8",
                        "--run-id",
                        "unit-full",
                        "--mere-run-command",
                        command,
                    ]
                )
                self.assertEqual(exit_code, 0)
                self.assertEqual(payload["status"], "succeeded")
                self.assertEqual(payload["artifacts"]["stats"]["files"], 3)
                self.assertEqual(payload["artifacts"]["stats"]["contents"], 2)
                self.assertEqual(payload["artifacts"]["stats"]["duplicates"], 1)

                exit_code, search, _ = invoke(
                    [
                        "search",
                        "--database",
                        str(database_path),
                        "--query",
                        "Halifax dana@example.com",
                        "--mere-run-command",
                        command,
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(search["query"], "Halifax [EMAIL]")
            self.assertEqual(search["results"][0]["paths"][0]["available"], True)
            self.assertNotIn("dana@example.com", json.dumps(search))
            with sqlite3.connect(database_path) as connection:
                stored = " ".join(
                    str(value)
                    for row in connection.execute("SELECT display_text, keywords_json FROM contents")
                    for value in row
                )
                chunk_text = " ".join(
                    str(row[0]) for row in connection.execute("SELECT text FROM chunks")
                )
                self.assertNotIn("dana@example.com", stored + chunk_text)
                self.assertNotIn("800-555-0199", stored + chunk_text)
                self.assertIn("[EMAIL]", stored + chunk_text)
                self.assertGreater(connection.execute("SELECT COUNT(*) FROM content_fts").fetchone()[0], 0)
            for path, contents in original.items():
                self.assertEqual(path.read_bytes(), contents)
            commands = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertTrue(any(command_args[:2] == ["vision", "caption"] for command_args in commands))
            self.assertTrue(any(command_args[:2] == ["vision", "ocr"] for command_args in commands))
            visual_calls = [
                command_args
                for command_args in commands
                if command_args[:2] == ["vision", "embed"]
            ]
            self.assertGreaterEqual(len(visual_calls), 3)
            self.assertTrue(
                all(
                    command_args[command_args.index("--model") + 1]
                    == "vision-embed-qwen3-vl-2b"
                    for command_args in visual_calls
                )
            )

            exit_code, resumed, _ = invoke(["resume", str(root / "run" / "run.json")])
            self.assertEqual(exit_code, 0)
            self.assertEqual(resumed["status"], "succeeded")

    def test_safe_content_discards_complete_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "shared"
            source.mkdir()
            tail = "NONPII-PRIVATE-TAIL-MARKER"
            (source / "notes.txt").write_text("Halifax overview " + ("context " * 300) + tail)
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            database_path = root / "archive.sqlite3"
            exit_code, payload, _ = invoke(
                [
                    "index",
                    "--source",
                    str(source),
                    "--database",
                    str(database_path),
                    "--output-dir",
                    str(root / "run"),
                    "--storage-tier",
                    "safe-content",
                    "--dimensions",
                    "8",
                    "--mere-run-command",
                    f"{sys.executable} {fake}",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["artifacts"]["stats"]["fullTextRecords"], 1)
            with sqlite3.connect(database_path) as connection:
                display = connection.execute("SELECT display_text FROM contents").fetchone()[0]
                texts = connection.execute("SELECT text FROM chunks").fetchall()
                fts = connection.execute("SELECT body FROM content_fts").fetchone()[0]
            self.assertNotIn(tail, display)
            self.assertNotIn(tail, fts)
            self.assertTrue(all(row[0] is None for row in texts))

    def test_pointers_store_vectors_without_searchable_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "shared"
            source.mkdir()
            (source / "warehouse.txt").write_text("Warehouse plan for Halifax")
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            database_path = root / "archive.sqlite3"
            exit_code, payload, _ = invoke(
                [
                    "index",
                    "--source",
                    str(source),
                    "--database",
                    str(database_path),
                    "--output-dir",
                    str(root / "run"),
                    "--storage-tier",
                    "pointers",
                    "--dimensions",
                    "8",
                    "--mere-run-command",
                    f"{sys.executable} {fake}",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["artifacts"]["stats"]["fullTextRecords"], 0)
            with sqlite3.connect(database_path) as connection:
                content = connection.execute("SELECT display_text, keywords_json FROM contents").fetchone()
                chunk = connection.execute("SELECT text, length(embedding) FROM chunks").fetchone()
            self.assertEqual(content, (None, None))
            self.assertIsNone(chunk[0])
            self.assertEqual(chunk[1], 8 * 4)

            exit_code, search, _ = invoke(
                [
                    "search",
                    "--database",
                    str(database_path),
                    "--query",
                    "warehouse Halifax",
                    "--mere-run-command",
                    f"{sys.executable} {fake}",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertIsNone(search["results"][0]["snippet"])
            self.assertEqual(search["storageTier"], "pointers")

    def test_database_settings_cannot_change_between_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "shared"
            source.mkdir()
            (source / "notes.txt").write_text("Halifax")
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            common = [
                "--source",
                str(source),
                "--database",
                str(root / "archive.sqlite3"),
                "--output-dir",
                str(root / "run"),
                "--dimensions",
                "8",
                "--mere-run-command",
                f"{sys.executable} {fake}",
            ]
            self.assertEqual(invoke(["index", *common, "--storage-tier", "safe-content"])[0], 0)
            exit_code, _, stderr = invoke(["index", *common, "--storage-tier", "pointers"])
            self.assertEqual(exit_code, 1)
            self.assertIn("create a separate database", stderr)

    def test_limited_run_preserves_unscanned_files_and_source_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "shared"
            source.mkdir()
            (source / "one.txt").write_text("Halifax warehouse one")
            (source / "two.txt").write_text("Halifax warehouse two")
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            database_path = root / "archive.sqlite3"
            command = f"{sys.executable} {fake}"
            base_arguments = [
                "--source",
                str(source),
                "--database",
                str(database_path),
                "--storage-tier",
                "safe-content",
                "--dimensions",
                "8",
                "--mere-run-command",
                command,
            ]
            exit_code, payload, _ = invoke(
                ["index", *base_arguments, "--output-dir", str(root / "full-run")]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["artifacts"]["stats"]["files"], 2)

            exit_code, payload, _ = invoke(
                [
                    "index",
                    *base_arguments,
                    "--output-dir",
                    str(root / "limited-run"),
                    "--limit",
                    "1",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["artifacts"]["stats"]["files"], 2)
            self.assertEqual(payload["progress"]["removed"], 0)

            search_output = source / "search.json"
            exit_code, _, stderr = invoke(
                [
                    "search",
                    "--database",
                    str(database_path),
                    "--query",
                    "Halifax",
                    "--output",
                    str(search_output),
                    "--mere-run-command",
                    command,
                ]
            )
            self.assertEqual(exit_code, 2)
            self.assertIn("--output must be outside", stderr)
            self.assertFalse(search_output.exists())

    def test_benchmark_prepares_and_mutates_deterministic_gauntlet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / "gauntlet"
            exit_code, payload, _ = invoke(["benchmark", "prepare", "--output-dir", str(output)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["dataset"]["id"], benchmark.SYNTHETIC_DATASET_ID)
            self.assertEqual(payload["sourceFiles"], 18)
            self.assertEqual(payload["queries"], 16)
            manifest_path = output / "benchmark.json"
            manifest = benchmark.load_manifest(manifest_path)
            manifest_schema = json.loads(
                (REPO_ROOT / "contracts/archive-benchmark.v1.schema.json").read_text()
            )
            self.assertEqual(list(Draft202012Validator(manifest_schema).iter_errors(manifest)), [])
            source = benchmark.source_root(manifest_path, manifest)
            phase_name, _, exact = benchmark.detect_phase(manifest, source)
            self.assertEqual((phase_name, exact), ("baseline", True))
            first = source / "Operations/Halifax/2022/pump-installation.md"
            copy = source / "Old Backups/Halifax/pump-installation-copy.md"
            self.assertEqual(first.read_bytes(), copy.read_bytes())
            self.assertTrue((source / "Photos/Halifax/2022/blue-pump-204.png").read_bytes().startswith(b"\x89PNG"))

            second_output = root / "gauntlet-copy"
            self.assertEqual(
                invoke(["benchmark", "prepare", "--output-dir", str(second_output)])[0],
                0,
            )
            first_hashes = {
                str(path.relative_to(source)): path.read_bytes()
                for path in source.rglob("*")
                if path.is_file()
            }
            second_source = second_output / "source"
            second_hashes = {
                str(path.relative_to(second_source)): path.read_bytes()
                for path in second_source.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_hashes, second_hashes)

            exit_code, _, stderr = invoke(["benchmark", "prepare", "--output-dir", str(output)])
            self.assertEqual(exit_code, 1)
            self.assertIn("output already exists", stderr)

            exit_code, mutation, _ = invoke(["benchmark", "mutate", str(manifest_path)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(mutation["phase"], "mutated")
            self.assertFalse(copy.exists())
            self.assertTrue((source / "Recovered/Halifax/pump-installation-copy.md").is_file())
            self.assertTrue((source / "Incoming/2026/bridge-crane-inspection.txt").is_file())
            phase_name, _, exact = benchmark.detect_phase(manifest, source)
            self.assertEqual((phase_name, exact), ("mutated", True))

    def test_benchmark_prepares_connected_harbourline_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "harbourline"
            exit_code, payload, _ = invoke(
                [
                    "benchmark",
                    "prepare",
                    "--dataset",
                    benchmark.HARBOURLINE_DATASET_ID,
                    "--output-dir",
                    str(output),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["dataset"]["id"], benchmark.HARBOURLINE_DATASET_ID)
            self.assertGreaterEqual(payload["sourceFiles"], 55)
            self.assertEqual(payload["queries"], 30)
            manifest_path = output / "benchmark.json"
            manifest = benchmark.load_manifest(manifest_path)
            manifest_schema = json.loads(
                (REPO_ROOT / "contracts/archive-benchmark.v1.schema.json").read_text()
            )
            self.assertEqual(list(Draft202012Validator(manifest_schema).iter_errors(manifest)), [])
            source = benchmark.source_root(manifest_path, manifest)
            phase_name, _, exact = benchmark.detect_phase(manifest, source)
            self.assertEqual((phase_name, exact), ("baseline", True))
            self.assertEqual(
                (source / "Finance/Accounts Payable/Northshore Refrigeration/2024/INV-8841.pdf").read_bytes(),
                (source / "Old Backups/Email Attachments/2024/INV-8841-copy.pdf").read_bytes(),
            )

    def test_benchmark_evaluates_custody_privacy_deduplication_and_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / "gauntlet"
            self.assertEqual(invoke(["benchmark", "prepare", "--output-dir", str(output)])[0], 0)
            source = output / "source"
            database_path = root / "archive.sqlite3"
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            command = f"{sys.executable} {fake}"

            def fake_document_extraction(path: pathlib.Path) -> tuple[str, str, str | None]:
                kind = extractors.file_kind(path)
                if kind == "text":
                    return path.read_text(encoding="utf-8"), kind, None
                return f"Converted document {path.stem.replace('-', ' ')}", kind, "test-anydoc"

            common = [
                "--source",
                str(source),
                "--database",
                str(database_path),
                "--storage-tier",
                "full-content",
                "--dimensions",
                "8",
                "--mere-run-command",
                command,
            ]
            with patch.object(cli.extractors, "extract_text", side_effect=fake_document_extraction):
                exit_code, indexed, _ = invoke(
                    ["index", *common, "--output-dir", str(root / "baseline-run")]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(indexed["artifacts"]["stats"]["duplicates"], 1)

            evaluation = [
                "benchmark",
                "evaluate",
                str(output / "benchmark.json"),
                "--database",
                str(database_path),
                "--mere-run-command",
                command,
            ]
            exit_code, report, _ = invoke(evaluation)
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["phase"], "baseline")
            self.assertEqual(report["retrieval"]["queryCount"], 16)
            self.assertTrue(report["passed"])
            report_schema = json.loads(
                (REPO_ROOT / "contracts/archive-benchmark-report.v1.schema.json").read_text()
            )
            self.assertEqual(list(Draft202012Validator(report_schema).iter_errors(report)), [])
            checks = {item["name"]: item for item in report["checks"]}
            self.assertTrue(checks["source-integrity"]["passed"])
            self.assertTrue(checks["content-deduplication"]["passed"])
            self.assertEqual(checks["exact-pii-canary-scan"]["detail"]["leaks"], [])

            self.assertEqual(invoke(["benchmark", "mutate", str(output / "benchmark.json")])[0], 0)
            with patch.object(cli.extractors, "extract_text", side_effect=fake_document_extraction):
                exit_code, indexed, _ = invoke(
                    ["index", *common, "--output-dir", str(root / "mutated-run")]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(indexed["progress"]["removed"], 2)
            exit_code, report, _ = invoke(evaluation)
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["phase"], "mutated")
            self.assertEqual(report["retrieval"]["queryCount"], 18)

            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    "UPDATE contents SET display_text = display_text || ' dana@example.com' WHERE id = 1"
                )
                connection.commit()
            exit_code, report, _ = invoke(evaluation)
            self.assertEqual(exit_code, 4)
            self.assertFalse(report["passed"])
            checks = {item["name"]: item for item in report["checks"]}
            self.assertEqual(checks["exact-pii-canary-scan"]["detail"]["leaks"], ["dana@example.com"])

    def test_benchmark_sources_are_pinned_without_bundling_public_data(self) -> None:
        exit_code, payload, _ = invoke(["benchmark", "sources"])
        self.assertEqual(exit_code, 0)
        datasets = payload["datasets"]
        self.assertEqual(
            datasets[benchmark.VIDORE_DATASET_ID]["revision"],
            "91cf66572d89c9cccac0661de227acaf04b44f64",
        )
        self.assertEqual(
            datasets[benchmark.GOVDOCS_DATASET_ID]["archiveSha1"],
            "c444d5b3c916183543027a4a1270bef294ba79f5",
        )


if __name__ == "__main__":
    unittest.main()

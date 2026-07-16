from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from PIL import Image

from mere_face_tools import cli


def write_image(path: pathlib.Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (32, 24), color).save(path)


def write_fake_mere_run(path: pathlib.Path) -> None:
    path.write_text(
        "import argparse, json, math, pathlib, sys\n"
        "def vector(score):\n"
        "    values = [0.0] * 512\n"
        "    values[0] = score\n"
        "    values[1] = math.sqrt(max(0.0, 1.0 - score * score))\n"
        "    return values\n"
        "def face(image):\n"
        "    name = pathlib.Path(image).stem\n"
        "    score = {'scott': 1.0, 'possible': 0.5, 'review': 0.4}.get(name, 0.0)\n"
        "    return {'index': 0, 'embedding': vector(score), 'detection': {\n"
        "        'score': 0.9, 'boundingBox': {'x': 2, 'y': 3, 'width': 12, 'height': 14},\n"
        "        'landmarks': [{'x': 4, 'y': 6}] * 5}}\n"
        "if sys.argv[1:4] == ['vision', 'face', '--help']:\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:4] == ['vision', 'face', 'batch']:\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--input-list', required=True)\n"
        "    parser.add_argument('--include-embeddings', action='store_true')\n"
        "    parser.add_argument('--model')\n"
        "    parser.add_argument('--execution-provider')\n"
        "    parser.add_argument('--score-threshold')\n"
        "    parser.add_argument('--jsonl-output', required=True)\n"
        "    args = parser.parse_args(sys.argv[4:])\n"
        "    images = pathlib.Path(args.input_list).read_text().splitlines()\n"
        "    records = [{'ok': True, 'image': image, 'result': {\n"
        "        'image': image, 'faces': [face(image)]}} for image in images]\n"
        "    pathlib.Path(args.jsonl_output).write_text(''.join(json.dumps(record) + '\\n' for record in records))\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:4] == ['vision', 'face', 'embed']:\n"
        "    image = sys.argv[4]\n"
        "    print(json.dumps({'image': image, 'face': face(image)}))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit('unexpected mere.run command: ' + repr(sys.argv[1:]))\n"
    )


class MereFaceToolsCLITests(unittest.TestCase):
    def test_manifest_has_required_commands(self) -> None:
        manifest = cli.plugin_manifest()
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        names = {command["name"] for command in manifest["commands"]}
        required = {"manifest", "doctor", "plan", "run", "resume", "cleanup", "index", "search"}
        self.assertTrue(required.issubset(names))
        self.assertEqual(manifest["security"]["cleanupDefault"], "none")
        self.assertIn("face-search", manifest["capabilities"])

    def test_plan_writes_resumable_index_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            photos = root / "photos"
            photos.mkdir()
            write_image(photos / "scott.jpg", (10, 20, 30))
            write_image(photos / "ignore.gif", (30, 20, 10))
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "plan", "--photos", str(photos), "--database", str(root / "faces.sqlite3"),
                    "--output-dir", str(root / "run"), "--run-id", "unit-face-plan",
                    "--mere-run-command", "fake-mere-run",
                ])
            self.assertEqual(exit_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "planned")
            self.assertEqual(payload["dataset"]["pairCount"], 1)
            self.assertEqual(payload["tool"]["backend"], "mere.run/vision-face-batch")
            self.assertTrue((root / "run" / "run.json").is_file())

    def test_index_resume_search_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            photos = root / "photos"
            photos.mkdir()
            for name, color in (
                ("scott.jpg", (100, 10, 10)),
                ("possible.jpg", (10, 100, 10)),
                ("review.jpg", (10, 10, 100)),
                ("other.jpg", (50, 50, 50)),
            ):
                write_image(photos / name, color)
            reference = root / "scott.jpg"
            write_image(reference, (100, 10, 10))
            fake = root / "fake_mere_run.py"
            write_fake_mere_run(fake)
            database = root / "faces.sqlite3"
            run_dir = root / "index"
            mere_run = f"{sys.executable} {fake}"
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "index", "--photos", str(photos), "--database", str(database),
                    "--output-dir", str(run_dir), "--batch-size", "2", "--run-id", "unit-face-index",
                    "--mere-run-command", mere_run,
                ])
            self.assertEqual(exit_code, 0)
            indexed = json.loads(stdout.getvalue())
            self.assertEqual(indexed["status"], "succeeded")
            self.assertEqual(indexed["artifacts"]["stats"], {"photos": 4, "complete": 4, "errors": 0, "faces": 4})
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM faces").fetchone()[0], 4)
                self.assertEqual(connection.execute("SELECT embedding_dim FROM faces LIMIT 1").fetchone()[0], 512)

            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(cli.main(["resume", str(run_dir / "run.json")]), 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "succeeded")

            search_dir = root / "search"
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "search", "--database", str(database), "--reference", str(reference),
                    "--output-dir", str(search_dir), "--run-id", "unit-face-search",
                    "--mere-run-command", mere_run,
                ])
            self.assertEqual(exit_code, 0)
            search_run = json.loads(stdout.getvalue())
            self.assertEqual(search_run["artifacts"]["counts"], {"strong": 1, "likely": 1, "review": 1})
            matches = json.loads((search_dir / "matches.json").read_text())["matches"]
            self.assertEqual([match["category"] for match in matches], ["strong", "likely", "review"])
            self.assertTrue(pathlib.Path(matches[0]["exportPath"]).is_symlink())
            self.assertTrue((search_dir / "matches.csv").is_file())
            self.assertTrue((search_dir / "contact-sheet.jpg").is_file())

            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(cli.main(["cleanup", str(run_dir / "run.json")]), 0)
            self.assertEqual(json.loads(stdout.getvalue())["cleanup"]["status"], "skipped")

    def test_invalid_search_threshold_order_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            database = root / "faces.sqlite3"
            database.touch()
            reference = root / "reference.jpg"
            write_image(reference, (0, 0, 0))
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = cli.main([
                    "search", "--database", str(database), "--reference", str(reference),
                    "--output-dir", str(root / "search"), "--strong-threshold", "0.3",
                    "--likely-threshold", "0.5",
                ])
            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()

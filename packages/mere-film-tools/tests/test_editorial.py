from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import validate
from test_cli import run_cli

from mere_film_tools.common import JsonMap, PluginError, file_sha256, load_json, write_json
from mere_film_tools.retake import RetakeRequest, create_retake
from mere_film_tools.state import add_artifact, load_state, save
from mere_film_tools.timeline import export_timeline

PROBED_MEDIA: JsonMap = {
    "streams": [
        {"codec_type": "video", "width": 256, "height": 256, "r_frame_rate": "24/1",
         "avg_frame_rate": "24/1", "nb_frames": "25"},
        {"codec_type": "audio", "duration_ts": 96_000, "time_base": "1/48000"},
    ],
}


class FilmEditorialTests(unittest.TestCase):
    def test_retakes_and_editable_timeline_preserve_shot_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            code, status, error = run_cli(["plan", "--idea", "An animated beacon", "--output-dir", str(root / "film")])
            self.assertEqual(code, 0, error)
            paths, project, run = load_state(Path(json.loads(status)["status"]["runManifest"]))
            shots = [{"id": "a", "durationSeconds": 1}, {"id": "b", "durationSeconds": 1}]
            write_json(paths.production, {"shots": shots, "target": {"fps": 24, "width": 256, "height": 256}})
            for shot in shots:
                path = paths.clips / f"{shot['id']}.mp4"
                path.write_bytes(str(shot["id"]).encode())
                add_artifact(paths, project, run, path, "shot-clip", "video/mp4")
            dialogue = paths.audio / "voices.wav"
            dialogue.write_bytes(b"dialogue")
            add_artifact(paths, project, run, dialogue, "dialogue", "audio/wav")
            project["jobs"] = [
                {"id": f"voice-{index}", "kind": "dialogue", "subject": "a", "status": "succeeded",
                 "startSeconds": start, "output": "audio/voices.wav"}
                for index, start in enumerate((0.125, 0.5), 1)
            ]
            save(paths, project, run)
            state_before = paths.project.read_bytes()
            source = paths.clips / "a.mp4"

            def native(command: list[str], cwd: Path, log: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                self.assertEqual(cwd, paths.root)
                self.assertEqual(timeout, 120)
                self.assertIn("--preserve-audio", command)
                self.assertEqual(command[-2:], ["--", "Turn around"])
                self.assertEqual(float(command[command.index("--start-time") + 1]), 4 / 24)
                self.assertEqual(float(command[command.index("--end-time") + 1]), 9 / 24)
                snapshot = Path(command[command.index("--source") + 1])
                self.assertNotEqual(snapshot, source)
                self.assertEqual(snapshot.read_bytes(), b"a")
                Path(command[command.index("--output") + 1]).write_bytes(b"candidate")
                log.write_text("fixture")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch("mere_film_tools.retake.probe_media", return_value=PROBED_MEDIA),
                patch("mere_film_tools.retake.run_child", side_effect=native),
            ):
                result = create_retake(paths, project, RetakeRequest(
                    "a", 4, 9, "Turn around", "video-ltx25-distilled-bf16", None, "diffusion", "video", 10, 120,
                ), root / "candidate")
            receipt_path = Path(str(result["receipt"]))
            schema_path = Path(__file__).resolve().parents[3] / "contracts" / "film-retake.v1.schema.json"
            validate(load_json(receipt_path), load_json(schema_path))
            self.assertEqual(source.read_bytes(), b"a")
            self.assertEqual(load_json(receipt_path)["sourceSha256"], file_sha256(source))
            self.assertFalse((receipt_path.parent / "source.mp4").exists())

            with patch("mere_film_tools.timeline.probe_media", return_value=PROBED_MEDIA):
                code, response, error = run_cli([
                    "export-timeline", str(paths.run), "--retake", str(receipt_path), "--output-dir", str(root / "edit"),
                ])
                self.assertEqual(code, 0, error)
                timeline = load_json(Path(json.loads(response)["timeline"]))
                tracks = timeline["tracks"]["children"]
                self.assertEqual([track["name"] for track in tracks], [
                    "Picture", "Production audio", "Dialogue 1", "Dialogue 2",
                ])
                picture = tracks[0]["children"]
                self.assertEqual([item["name"] for item in picture], ["a", "a retake", "a", "b"])
                self.assertEqual([item["source_range"]["duration"]["value"] for item in picture], [4, 5, 15, 24])
                self.assertEqual([item["name"] for item in tracks[1]["children"]], ["a", "b"])
                self.assertEqual(tracks[2]["children"][0]["source_range"]["duration"]["value"], 3)
                self.assertEqual(len(list((root / "edit" / "media").iterdir())), 4)

                with self.assertRaisesRegex(PluginError, "overlapping"):
                    export_timeline(paths, project, root / "overlap", [receipt_path, receipt_path])
                self.assertFalse((root / "overlap").exists())
                data = load_json(receipt_path)
                data["sourceSha256"] = "sha256:" + "0" * 64
                write_json(receipt_path, data)
                with self.assertRaisesRegex(PluginError, "stale"):
                    export_timeline(paths, project, root / "stale", [receipt_path])
                self.assertFalse((root / "stale").exists())
            self.assertEqual(paths.project.read_bytes(), state_before)
            shutil.rmtree(paths.clips)
            self.assertTrue((root / "edit" / "media" / "0001-a.mp4").is_file())

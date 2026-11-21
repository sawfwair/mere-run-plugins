from __future__ import annotations

import json
import math
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from mere_workflow_tools import audio_post, cli
from mere_workflow_tools.graph_sdk import GraphProviderError


class AudioPostTests(unittest.TestCase):
    def test_plan_records_models_and_refuses_to_replace_an_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "scene.mov"
            source.touch()
            output = root / "post"
            flags = ["--input", str(source), "--output-dir", str(output), "--task", "foley",
                     "--prompt", "Footsteps on gravel"]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()), patch.object(audio_post, "run_command") as launch:
                self.assertEqual(cli.main_for("audio_post", ["plan", *flags]), 0)
                self.assertEqual(cli.main_for("audio_post", ["plan", *flags]), 2)
            launch.assert_not_called()
            plan = json.loads((output / "run.json").read_text())
            self.assertEqual(plan["tool"]["requiredModels"], [audio_post.FOLEY_MODEL, audio_post.SYNC_MODEL])
            self.assertIn("Footsteps on gravel", plan["command"])
            self.assertFalse((output / "audio").exists())

    def test_missing_model_stops_before_media_processing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "mix.wav"
            source.touch()
            job = audio_post.Job(source, "stems", "two", None)
            response = subprocess.CompletedProcess([], 0, '{"inventory":{"rows":[]}}', "")
            with patch.object(audio_post, "ffmpeg_executable", return_value="ffmpeg"), \
                    patch.object(audio_post, "run_command", return_value=response) as launch:
                with self.assertRaisesRegex(GraphProviderError, audio_post.STEM_MODELS["two"]):
                    audio_post.finish(job, ["mere.run"], root / "delivery")
            launch.assert_called_once_with(["mere.run", "model", "list", "--json"])
            self.assertFalse((root / "delivery").exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is available for WAV delivery tests")
    def test_real_wav_export_and_loudness_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            source = root / "Recording with spaces.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
                audio.writeframes(b"".join(
                    struct.pack("<h", round(math.sin(i * math.tau * 440 / 16000) * 3000)) for i in range(32_000)
                ))
            output = root / "post"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(cli.main_for("audio_post", ["process", "--input", str(source), "--output-dir", str(output)]), 0)
                self.assertEqual(cli.main_for("audio_post", ["run", str(output / "run.json")]), 0)
            report = json.loads((output / "audio" / "loudness.json").read_text())
            receipt = json.loads((output / "run.json").read_text())
            self.assertEqual(report["sample_rate_hz"], 48000)
            self.assertEqual(report["measurements"][0]["file"], "source.wav")
            self.assertLess(report["measurements"][0]["integrated_lufs"], -10)
            self.assertLess(report["measurements"][0]["true_peak_dbtp"], 0)
            self.assertEqual(receipt["status"], "succeeded")
            self.assertTrue(receipt["artifacts"]["sha256"][str(output / "audio" / "source.wav")].startswith("sha256:"))

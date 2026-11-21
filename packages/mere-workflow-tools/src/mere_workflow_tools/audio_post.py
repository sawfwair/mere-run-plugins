"""Local audio finishing, delivery, and loudness measurement."""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .graph_sdk import GraphProviderError, JsonMap, as_map

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".aif", ".aiff", ".ogg", ".opus"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".mkv", ".webm"}
STEM_NAMES = {"two": ("vocals", "instrumental"), "four": ("drums", "bass", "other", "vocals")}
STEM_MODELS = {
    "two": "music-separate-bs-roformer-viperx-1297",
    "four": "music-separate-bs-roformer-4stem",
}
RESTORATION = {"denoise": "dry", "dereverb": "noreverb"}
MIDI_MODEL = "music-muscriptor-medium"
FOLEY_MODEL = "sfx-woosh-dvflow-8s"
SYNC_MODEL = "sfx-woosh-synchformer"
TASKS = ("prepare", "denoise", "dereverb", "stems", "midi", "foley")
LOUDNESS_KEYS = {
    "integrated_lufs": "input_i",
    "true_peak_dbtp": "input_tp",
    "loudness_range_lu": "input_lra",
}


@dataclass(frozen=True)
class Job:
    source: pathlib.Path
    task: str
    stems: str
    prompt: str | None

    def validate(self) -> None:
        if self.task not in TASKS or self.stems not in STEM_NAMES:
            raise GraphProviderError("Choose a supported Audio Post task and stem layout.")
        extensions = VIDEO_EXTENSIONS if self.task == "foley" else AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
        if not self.source.is_file() or self.source.suffix.lower() not in extensions:
            raise GraphProviderError("Choose a local video file for Foley or a local audio or video file for other tasks.")
        if self.task == "foley" and not (self.prompt or "").strip():
            raise GraphProviderError("Supply a sound description with --prompt for Foley.")
        if self.task != "foley" and self.prompt is not None:
            raise GraphProviderError("Use --prompt with --task foley.")
        if self.task != "stems" and self.stems != "four":
            raise GraphProviderError("Use --stems with --task stems.")

    def models(self) -> tuple[str, ...]:
        if self.task in RESTORATION:
            return (f"music-separate-mel-roformer-{self.task}",)
        if self.task == "stems":
            return (STEM_MODELS[self.stems],)
        if self.task == "midi":
            return (MIDI_MODEL,)
        if self.task == "foley":
            return (FOLEY_MODEL, SYNC_MODEL)
        return ()


def add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", type=pathlib.Path, required=True, help="Local audio file or video clip.")
    parser.add_argument("--task", choices=TASKS, default="prepare", help="Finishing task. Defaults to WAV export and measurement.")
    parser.add_argument("--stems", choices=tuple(STEM_NAMES), default="four", help="Stem layout for --task stems.")
    parser.add_argument("--prompt", help="Sound description for --task foley.")


def ffmpeg_executable() -> str | None:
    if executable := shutil.which("ffmpeg"):
        return executable
    for executable in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if found := shutil.which(executable):
            return found
    return None


@contextmanager
def run_lock(manifest_path: pathlib.Path) -> Iterator[None]:
    import fcntl

    descriptor = os.open(manifest_path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GraphProviderError("Another Audio Post command is running in this manifest directory.") from None
        yield
    finally:
        os.close(descriptor)


def run_command(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise GraphProviderError(f"Could not start {pathlib.Path(arguments[0]).name}: {exc.strerror}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = " ".join(detail[-5:])[:700]
        raise GraphProviderError(f"{pathlib.Path(arguments[0]).name} exited with status {result.returncode}. {message}".strip())
    return result


def check_models(runtime: list[str], models: tuple[str, ...]) -> None:
    if not models:
        return
    inventory = as_map(json.loads(run_command([*runtime, "model", "list", "--json"]).stdout), "model list")
    rows = as_map(inventory.get("inventory"), "model inventory").get("rows")
    if not isinstance(rows, list):
        raise GraphProviderError("mere.run did not return its model inventory.")
    installed = {
        row.get("id") for row in rows if isinstance(row, dict) and row.get("status") == "installed"
    }
    if missing := [model for model in models if model not in installed]:
        raise GraphProviderError("Install the required models before running Audio Post: " + ", ".join(missing))


def media_args(ffmpeg: str, source: pathlib.Path) -> list[str]:
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-protocol_whitelist", "file,pipe",
        "-format_whitelist", "wav,mp3,mov,flac,aac,aiff,ogg,matroska", "-i", str(source), "-map", "0:a:0",
    ]


def export_wav(ffmpeg: str, source: pathlib.Path, destination: pathlib.Path) -> None:
    run_command([*media_args(ffmpeg, source), "-loglevel", "error", "-c:a", "pcm_f32le", "-ar", "48000",
                 "-n", str(destination)])


def measure(ffmpeg: str, source: pathlib.Path) -> JsonMap:
    result = run_command([*media_args(ffmpeg, source), "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    match = re.search(r'\{\s*"input_i"[^}]+\}', result.stderr)
    if match is None:
        raise GraphProviderError(f"FFmpeg did not report loudness for {source.name}.")
    stats = json.loads(match[0])
    values: JsonMap = {}
    for name, field in LOUDNESS_KEYS.items():
        value = float(stats[field])
        values[name] = value if math.isfinite(value) else None
    return {"file": source.name, **values}


def finish(job: Job, runtime: list[str], destination: pathlib.Path) -> None:
    job.validate()
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        raise GraphProviderError("Install FFmpeg and run Audio Post doctor before continuing.")
    if destination.exists() or destination.is_symlink():
        raise GraphProviderError(f"Audio Post output already exists at {destination}. Choose a fresh output directory.")
    models = job.models()
    check_models(runtime, models)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".audio-post-", dir=destination.parent) as scratch:
        workspace = pathlib.Path(scratch)
        delivery = workspace / "delivery"
        delivery.mkdir()
        if job.task == "foley":
            raw = workspace / "foley.wav"
            run_command([*runtime, "sfx", "video", "generate", "--model", FOLEY_MODEL,
                         "--synchformer-model", SYNC_MODEL, "--output", str(raw), "--", job.prompt or "", str(job.source)])
            export_wav(ffmpeg, raw, delivery / "foley.wav")
        else:
            source = delivery / "source.wav"
            export_wav(ffmpeg, job.source, source)
            if job.task == "midi":
                midi = delivery / "music.mid"
                context = delivery / "musical-context.json"
                run_command([*runtime, "music", "transcribe", str(source), "--model", MIDI_MODEL,
                             "--output", str(midi), "--context-output", str(context)])
                with midi.open("rb") as stream:
                    if stream.read(4) != b"MThd":
                        raise GraphProviderError("MuScriptor did not produce a valid MIDI header.")
                as_map(json.loads(context.read_bytes()), "musical context")
            elif job.task in RESTORATION or job.task == "stems":
                raw = workspace / "native"
                run_command([*runtime, "music", "separate", str(source), "--model", models[0], "--output-dir", str(raw)])
                names = STEM_NAMES[job.stems] if job.task == "stems" else (RESTORATION[job.task],)
                for name in names:
                    output = f"{name}.wav" if job.task == "stems" else f"{job.task}.wav"
                    export_wav(ffmpeg, raw / f"{name}.wav", delivery / output)
        report = {
            "source": str(job.source), "task": job.task, "models": list(models), "sample_rate_hz": 48000,
            "measurements": [measure(ffmpeg, path) for path in sorted(delivery.glob("*.wav"))],
        }
        (delivery / "loudness.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        delivery.rename(destination)

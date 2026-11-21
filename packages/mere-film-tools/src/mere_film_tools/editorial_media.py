"""Media verification and staging for retakes and editorial exports."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from .common import JsonMap, PluginError, as_list, as_map, as_number, as_string, file_sha256
from .production import clip_output, matching_artifact
from .state import ProjectPaths


def source_digest(paths: ProjectPaths, project: JsonMap, path: Path, kind: str) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(paths.root) or not matching_artifact(paths, project, path, kind):
        raise PluginError(f"missing or changed {kind}: {path}", 2)
    for raw in as_list(project.get("artifacts"), "project.artifacts"):
        artifact = as_map(raw, "project.artifact")
        if artifact.get("path") == str(resolved.relative_to(paths.root)) and artifact.get("kind") == kind:
            return as_string(artifact.get("sha256"), "artifact.sha256")
    raise PluginError(f"missing {kind} record: {path}", 2)


def shot_media(paths: ProjectPaths, project: JsonMap, shot_id: str) -> tuple[Path, str]:
    path = clip_output(paths, shot_id).resolve()
    return path, source_digest(paths, project, path, "shot-clip")


def fraction(value: object) -> Fraction:
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def shot_duration(shot: JsonMap) -> Fraction:
    duration = fraction(as_number(shot.get("durationSeconds"), "shot.durationSeconds"))
    if duration <= 0:
        raise PluginError("shot duration must be finite and positive", 2)
    return duration


def stream_of_type(probe: JsonMap, kind: str) -> JsonMap:
    for raw in as_list(probe.get("streams"), "ffprobe streams"):
        stream = as_map(raw, "ffprobe stream")
        if stream.get("codec_type") == kind and as_map(stream.get("disposition", {}), "stream disposition").get(
            "attached_pic"
        ) != 1:
            return stream
    return {}


def stream_duration(stream: JsonMap) -> Fraction:
    ticks = fraction(stream.get("duration_ts")) * fraction(stream.get("time_base"))
    return ticks if ticks > 0 else fraction(stream.get("duration"))


@dataclass(frozen=True)
class VideoTiming:
    rate: Fraction
    frames: int
    width: int
    height: int

    @property
    def duration(self) -> Fraction:
        return self.frames / self.rate

    @property
    def rate_text(self) -> str:
        return f"{self.rate.numerator}/{self.rate.denominator}"


def video_timing(probe: JsonMap) -> VideoTiming:
    stream = stream_of_type(probe, "video")
    rate = fraction(stream.get("avg_frame_rate"))
    frames = fraction(stream.get("nb_frames"))
    width = fraction(stream.get("width"))
    height = fraction(stream.get("height"))
    if rate <= 0 or any(value <= 0 or value.denominator != 1 for value in (frames, width, height)):
        raise PluginError("video must report its frame rate, frame count, and dimensions", 2)
    return VideoTiming(rate, int(frames), int(width), int(height))


def verify_bytes(path: Path, digest: str, label: str) -> None:
    if not path.is_file() or file_sha256(path) != digest:
        raise PluginError(f"{label} bytes do not match the recorded SHA-256", 2)


@contextmanager
def staged_output(destination: Path) -> Iterator[Path]:
    if destination.exists() or destination.is_symlink():
        raise PluginError(f"output directory already exists: {destination}", 2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent, prefix=".film-export-") as location:
        staging = Path(location)
        yield staging
        destination.mkdir(mode=0o700)
        try:
            staging.replace(destination)
        except OSError:
            destination.rmdir()
            raise

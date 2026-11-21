"""Generate immutable, source-bound candidates for a film shot region."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .common import JsonMap, PluginError, as_int, as_map, as_string, file_sha256, now_iso, write_json
from .editorial_media import (
    fraction,
    shot_duration,
    shot_media,
    staged_output,
    stream_of_type,
    verify_bytes,
    video_timing,
)
from .production import command_value, probe_media, production_plan, run_child, shot_items
from .state import ProjectPaths

CONTRACT_VERSION = "mere.run/film-retake.v1"
MODELS = ("video-ltx25-distilled-bf16", "video-ltx25-full-bf16")
MODALITIES = ("video", "audio", "both")


@dataclass(frozen=True)
class RetakeRequest:
    shot_id: str
    start_frame: int
    end_frame: int
    prompt: str
    model: str
    model_root: Path | None
    decoder: str
    modality: str
    seed: int
    timeout: int


def create_retake(paths: ProjectPaths, project: JsonMap, request: RetakeRequest, output: Path) -> JsonMap:
    plan = production_plan(paths)
    shot = next((entry for entry in shot_items(plan) if entry.get("id") == request.shot_id), None)
    if shot is None:
        raise PluginError(f"unknown shot: {request.shot_id}", 2)
    if not request.prompt.strip() or not 0 <= request.start_frame < request.end_frame:
        raise PluginError("provide a prompt and a nonempty half-open frame range starting at zero or later", 2)
    if request.seed < 0 or request.timeout <= 0:
        raise PluginError("--seed must be nonnegative and --media-timeout must be positive", 2)
    if request.model_root is not None and not request.model_root.is_dir():
        raise PluginError(f"model root does not exist: {request.model_root}", 2)
    source, digest = shot_media(paths, project, request.shot_id)
    ffprobe = command_value(project, "ffprobe")

    with staged_output(output) as staging:
        snapshot = staging / "source.mp4"
        shutil.copyfile(source, snapshot)
        verify_bytes(snapshot, digest, "retake source snapshot")
        source_info = probe_media(snapshot, ffprobe)
        timing = video_timing(source_info)
        video = stream_of_type(source_info, "video")
        if timing.rate != fraction(video.get("r_frame_rate")):
            raise PluginError("retake requires a constant-frame-rate source", 2)
        if timing.frames < 9 or timing.frames % 8 != 1 or timing.width % 32 or timing.height % 32:
            raise PluginError("LTX retake requires 8n+1 source frames and dimensions divisible by 32", 2)
        if request.end_frame > timing.frames or request.end_frame / timing.rate > shot_duration(shot):
            raise PluginError("retake range exceeds the selected clip or its planned shot duration", 2)

        # The runtime rejects preserve-audio for a silent source. Discard its
        # generated audio in that case so the review clip stays silent.
        source_audio = bool(stream_of_type(source_info, "audio"))
        discard_audio = request.modality == "video" and not source_audio
        candidate = staging / "retake.mp4"
        native_output = staging / "native.mp4" if discard_audio else candidate
        command = [
            command_value(project, "mereRun"), "video", "retake",
            "--source", str(snapshot),
            "--start-time", format(float(request.start_frame / timing.rate), ".17g"),
            "--end-time", format(float(request.end_frame / timing.rate), ".17g"),
            "--seed", str(request.seed), "--model", request.model,
            "--video-decoder", request.decoder, "--output", str(native_output),
        ]
        if request.model_root is not None:
            command.extend(["--model-root", str(request.model_root)])
        if request.modality == "audio":
            command.append("--preserve-video")
        if request.modality == "video" and source_audio:
            command.append("--preserve-audio")
        command.extend(["--", request.prompt])
        run_child(command, paths.root, staging / "runtime.log", request.timeout)
        if discard_audio:
            run_child([
                command_value(project, "ffmpeg"), "-v", "error", "-i", str(native_output),
                "-map", "0:v:0", "-c:v", "copy", str(candidate),
            ], paths.root, staging / "remux.log", 120)
            native_output.unlink()
        result = probe_media(candidate, ffprobe)
        if video_timing(result) != timing:
            raise PluginError("native retake changed the frame count, dimensions, or frame rate")
        expected_audio = request.modality != "video" or source_audio
        if bool(stream_of_type(result, "audio")) != expected_audio:
            raise PluginError("native retake returned an unexpected audio stream layout")
        verify_bytes(source, digest, "project source")
        snapshot.unlink()
        (staging / ".source.mp4.ffprobe.log").unlink(missing_ok=True)
        receipt: JsonMap = {
            "contractVersion": CONTRACT_VERSION,
            "createdAt": now_iso(),
            "projectId": as_string(project.get("projectId"), "project.projectId"),
            "shotId": request.shot_id,
            "sourceSha256": digest,
            "region": {"startFrame": request.start_frame, "endFrame": request.end_frame},
            "frameRate": timing.rate_text,
            "frameCount": timing.frames,
            "modality": request.modality,
            "prompt": request.prompt,
            "seed": request.seed,
            "requestedModel": request.model,
            "decoder": request.decoder,
            "candidate": {"path": candidate.name, "bytes": candidate.stat().st_size, "sha256": file_sha256(candidate)},
        }
        write_json(staging / "retake.json", receipt)
    return {"receipt": str(output / "retake.json"), "clip": str(output / "retake.mp4"), "retake": receipt}


def read_candidate(receipt: JsonMap, directory: Path) -> tuple[Path, str, int, int, str]:
    candidate = as_map(receipt.get("candidate"), "retake.candidate")
    region = as_map(receipt.get("region"), "retake.region")
    start = as_int(region.get("startFrame"), "retake.startFrame")
    end = as_int(region.get("endFrame"), "retake.endFrame")
    modality = as_string(receipt.get("modality"), "retake.modality")
    if not 0 <= start < end or modality not in MODALITIES or candidate.get("path") != "retake.mp4":
        raise PluginError("invalid retake receipt range, modality, or media path", 2)
    path = directory / "retake.mp4"
    digest = as_string(candidate.get("sha256"), "retake.candidate.sha256")
    if path.is_symlink() or not path.is_file() or candidate.get("bytes") != path.stat().st_size:
        raise PluginError(f"retake candidate is missing or changed: {path}", 2)
    return path, digest, start, end, modality

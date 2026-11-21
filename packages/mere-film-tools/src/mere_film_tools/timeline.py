"""Export a media-backed, editable OpenTimelineIO project."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .common import JsonMap, PluginError, as_int, as_map, as_string, file_sha256, load_json, slug, write_json
from .editorial_media import (
    fraction,
    shot_duration,
    shot_media,
    source_digest,
    staged_output,
    stream_duration,
    stream_of_type,
    verify_bytes,
    video_timing,
)
from .production import (
    command_value,
    dialogue_jobs_for_shot,
    output_path,
    probe_media,
    production_plan,
    shot_items,
    sound_effect_jobs_for_shot,
)
from .retake import CONTRACT_VERSION as RETAKE_CONTRACT
from .retake import read_candidate
from .state import ProjectPaths


@dataclass(frozen=True)
class Media:
    url: str
    sha256: str
    probe: JsonMap


@dataclass(frozen=True)
class Region:
    start: int
    end: int
    modality: str
    media: Media


@dataclass(frozen=True)
class Cue:
    start: int
    end: int
    item: JsonMap


class MediaCopies:
    def __init__(self, staging: Path, destination: Path, ffprobe: str) -> None:
        self.staging = staging
        self.destination = destination
        self.ffprobe = ffprobe
        self.copies: dict[Path, Media] = {}
        (staging / "media").mkdir()

    def copy(self, source: Path, digest: str) -> Media:
        resolved = source.resolve()
        if resolved in self.copies:
            media = self.copies[resolved]
            if media.sha256 != digest:
                raise PluginError(f"conflicting media checksums for {source}", 2)
            return media
        relative = Path("media") / f"{len(self.copies) + 1:04d}-{slug(source.stem)}{source.suffix.lower()}"
        target = self.staging / relative
        shutil.copyfile(resolved, target)
        verify_bytes(target, digest, "timeline media copy")
        probe = probe_media(target, self.ffprobe)
        (target.parent / f".{target.name}.ffprobe.log").unlink(missing_ok=True)
        media = Media((self.destination / relative).as_uri(), digest, probe)
        self.copies[resolved] = media
        return media


def rational_time(value: int, fps: int) -> JsonMap:
    return {"OTIO_SCHEMA": "RationalTime.1", "value": value, "rate": fps}


def time_range(start: int, length: int, fps: int) -> JsonMap:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": rational_time(start, fps),
        "duration": rational_time(length, fps),
    }


def item_base(schema: str, name: str, source_range: JsonMap | None) -> JsonMap:
    return {
        "OTIO_SCHEMA": schema,
        "name": name,
        "source_range": source_range,
        "metadata": {},
        "effects": [],
        "markers": [],
        "enabled": True,
        "color": None,
    }


def gap(length: int, fps: int) -> JsonMap:
    return item_base("Gap.1", "", time_range(0, length, fps))


def track(name: str, kind: str, children: list[JsonMap]) -> JsonMap:
    return {**item_base("Track.1", name, None), "kind": kind, "children": children}


def clip(media: Media, name: str, start: int, length: int, available: int, fps: int) -> JsonMap:
    return {
        **item_base("Clip.2", name, time_range(start, length, fps)),
        "media_references": {
            "DEFAULT_MEDIA": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "name": name,
                "metadata": {"mere.run": {"sha256": media.sha256}},
                "available_range": time_range(0, available, fps),
                "available_image_bounds": None,
                "target_url": media.url,
            },
        },
        "active_media_reference_key": "DEFAULT_MEDIA",
    }


def stream_frames(media: Media, kind: str, fps: int) -> int:
    if kind == "video":
        return int(video_timing(media.probe).duration * fps)
    return max(0, int(stream_duration(stream_of_type(media.probe, "audio")) * fps))


def track_shot(
    source: Media, regions: list[Region], shot_id: str, length: int, fps: int, kind: str,
) -> list[JsonMap]:
    spans = []
    cursor = 0
    for region in sorted(regions, key=lambda item: item.start):
        if region.modality not in (kind, "both"):
            continue
        if region.start < cursor or region.end > length:
            raise PluginError(f"overlapping or out-of-range {kind} retakes for {shot_id}", 2)
        spans.extend([(cursor, region.start, source, shot_id), (region.start, region.end, region.media, f"{shot_id} retake")])
        cursor = region.end
    spans.append((cursor, length, source, shot_id))

    items: list[JsonMap] = []
    for start, end, media, name in spans:
        if start == end:
            continue
        available = stream_frames(media, kind, fps)
        if media is not source and available < end:
            raise PluginError(f"retake {kind} stream cannot cover its selected range for {shot_id}", 2)
        trimmed = max(0, min(end, available) - start)
        if trimmed:
            items.append(clip(media, name, start, trimmed, available, fps))
        if trimmed < end - start:
            items.append(gap(end - start - trimmed, fps))
    return items


def audio_tracks(cues: list[Cue], label: str, fps: int) -> list[JsonMap]:
    lanes: list[list[JsonMap]] = []
    ends: list[int] = []
    for cue in sorted(cues, key=lambda entry: entry.start):
        lane = next((index for index, end in enumerate(ends) if end <= cue.start), len(ends))
        if lane == len(ends):
            lanes.append([])
            ends.append(0)
        if ends[lane] < cue.start:
            lanes[lane].append(gap(cue.start - ends[lane], fps))
        lanes[lane].append(cue.item)
        ends[lane] = cue.end
    return [
        track(label if len(lanes) == 1 else f"{label} {index}", "Audio", items)
        for index, items in enumerate(lanes, 1)
    ]


def shot_cues(
    paths: ProjectPaths, project: JsonMap, copies: MediaCopies, members: list[JsonMap], kind: str,
    offset: int, length: int, fps: int,
) -> list[Cue]:
    cues = []
    for job in members:
        name = as_string(job.get("id"), "audio job.id")
        source = output_path(paths, job)
        if job.get("status") != "succeeded":
            raise PluginError(f"cannot export incomplete audio cue: {name}", 2)
        media = copies.copy(source, source_digest(paths, project, source, kind))
        available = stream_frames(media, "audio", fps)
        if not available:
            raise PluginError(f"audio cue is shorter than one timeline frame: {name}", 2)
        start = round(fraction(job.get("startSeconds")) * fps)
        if not 0 <= start < length:
            raise PluginError(f"audio cue starts outside its planned shot: {name}", 2)
        duration = min(available, length - start)
        cues.append(Cue(
            offset + start, offset + start + duration,
            clip(media, str(job.get("speaker") or name), 0, duration, available, fps),
        ))
    return cues


def selected_regions(
    project: JsonMap, copies: MediaCopies, selections: list[Path],
    selected_sources: dict[str, Media], fps: int,
) -> dict[str, list[Region]]:
    regions: dict[str, list[Region]] = {}
    for path in selections:
        receipt = load_json(path)
        if receipt.get("contractVersion") != RETAKE_CONTRACT or receipt.get("projectId") != project.get("projectId"):
            raise PluginError(f"retake receipt belongs to another project or has an unsupported schema: {path}", 2)
        shot = as_string(receipt.get("shotId"), "retake.shotId")
        source = selected_sources.get(shot)
        if source is None or receipt.get("sourceSha256") != source.sha256:
            raise PluginError(f"retake receipt is stale for selected shot {shot}", 2)
        timing = video_timing(source.probe)
        if timing.rate != fps or receipt.get("frameRate") != timing.rate_text or receipt.get("frameCount") != timing.frames:
            raise PluginError(f"retake source rate or frame count differs from the timeline for {shot}", 2)
        candidate, digest, start, end, modality = read_candidate(receipt, path.parent)
        media = copies.copy(candidate, digest)
        if video_timing(media.probe) != timing or end > timing.frames:
            raise PluginError(f"candidate media timing does not match selected shot {shot}", 2)
        regions.setdefault(shot, []).append(Region(start, end, modality, media))
    return regions


def export_timeline(paths: ProjectPaths, project: JsonMap, output: Path, selections: list[Path]) -> JsonMap:
    plan = production_plan(paths)
    shots = shot_items(plan)
    if not shots:
        raise PluginError("the production plan has no scheduled shots", 2)
    target = as_map(plan.get("target"), "productionPlan.target")
    fps = as_int(target.get("fps"), "productionPlan.target.fps")
    if fps <= 0:
        raise PluginError("timeline frame rate must be positive", 2)

    with staged_output(output) as staging:
        copies = MediaCopies(staging, output, command_value(project, "ffprobe"))
        selected_sources = {}
        for shot in shots:
            shot_id = as_string(shot.get("id"), "shot.id")
            source, digest = shot_media(paths, project, shot_id)
            selected_sources[shot_id] = copies.copy(source, digest)
        retakes = selected_regions(project, copies, selections, selected_sources, fps)

        picture: list[JsonMap] = []
        production_audio: list[JsonMap] = []
        dialogue: list[Cue] = []
        effects: list[Cue] = []
        cursor = 0
        for shot in shots:
            shot_id = as_string(shot.get("id"), "shot.id")
            duration = round(shot_duration(shot) * fps)
            if not duration:
                raise PluginError(f"planned shot is shorter than one timeline frame: {shot_id}", 2)
            media = selected_sources[shot_id]
            regions = retakes.get(shot_id, [])
            picture.extend(track_shot(media, regions, shot_id, duration, fps, "video"))
            production_audio.extend(track_shot(media, regions, shot_id, duration, fps, "audio"))
            dialogue.extend(shot_cues(paths, project, copies, dialogue_jobs_for_shot(project, shot_id),
                                     "dialogue", cursor, duration, fps))
            effects.extend(shot_cues(paths, project, copies, sound_effect_jobs_for_shot(project, shot_id),
                                    "sound-effect", cursor, duration, fps))
            cursor += duration

        tracks = [track("Picture", "Video", picture), track("Production audio", "Audio", production_audio)]
        tracks.extend(audio_tracks(dialogue, "Dialogue", fps))
        tracks.extend(audio_tracks(effects, "Sound effects", fps))
        score_path = paths.audio / "score.wav"
        if score_path.is_file():
            score = copies.copy(score_path, source_digest(paths, project, score_path, "score"))
            available = stream_frames(score, "audio", fps)
            if not available:
                raise PluginError("score is shorter than one timeline frame", 2)
            tracks.append(track("Score", "Audio", [
                clip(score, "Score", 0, min(available, cursor - start), available, fps)
                for start in range(0, cursor, available)
            ]))
        timeline = staging / "film.otio"
        write_json(timeline, {
            "OTIO_SCHEMA": "Timeline.1",
            "name": as_string(project.get("title"), "project.title"),
            "global_start_time": rational_time(0, fps),
            "metadata": {"mere.run": {"projectId": project.get("projectId"), "fps": fps,
                                       "width": target.get("width"), "height": target.get("height")}},
            "tracks": {**item_base("Stack.1", "tracks", None), "children": tracks},
        })
        digest = file_sha256(timeline)
    return {"timeline": str(output / "film.otio"), "sha256": digest, "frames": cursor,
            "fps": fps, "tracks": len(tracks), "retakes": len(selections), "media": len(copies.copies)}

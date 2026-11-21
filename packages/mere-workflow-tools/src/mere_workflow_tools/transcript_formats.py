"""Read native speech alignment and write subtitle files."""
from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

CLOCK = r"(?:[0-9]{2,}:)?[0-9]{2}:[0-9]{2}\.[0-9]{3}"
ALIGNMENT = re.compile(rf"^\[({CLOCK}) --> ({CLOCK})\] ", re.MULTILINE)


@dataclass(frozen=True)
class Cue:
    start: int
    end: int
    text: str


class Speaker(NamedTuple):
    start: int
    end: int
    number: int


def milliseconds(clock: str) -> int:
    time, fraction = clock.split(".")
    whole = 0
    for part in time.split(":"):
        whole = whole * 60 + int(part)
    return whole * 1000 + int(fraction)


def read_cues(path: Path) -> tuple[str, list[Cue]]:
    text = path.read_text(encoding="utf-8")
    headings = list(ALIGNMENT.finditer(text))
    if not headings or not text[:headings[0].start()].endswith("\n\n"):
        raise ValueError("The selected ASR backend returned no timed alignment for this file.")
    cues: list[Cue] = []
    for index, match in enumerate(headings):
        limit = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        start, end = milliseconds(match[1]), milliseconds(match[2])
        caption = " ".join(text[match.end():limit].split())
        if end > start and caption:
            cues.append(Cue(start, end, caption))
    if not cues:
        raise ValueError("The ASR alignment contains no usable timed captions.")
    return text[:headings[0].start()].strip(), sorted(cues, key=lambda cue: cue.start)


def read_speakers(path: Path) -> list[Speaker]:
    result = json.loads(path.read_text(encoding="utf-8"))
    segments = result.get("segments") if isinstance(result, dict) else None
    if not isinstance(segments, list):
        raise ValueError("Native diarization did not return a speaker segment list.")
    speakers = []
    for segment in segments:
        start, end, index = segment["start_seconds"], segment["end_seconds"], segment["speaker_index"]
        if math.isfinite(start) and math.isfinite(end) and 0 <= start < end and isinstance(index, int) and index >= 0:
            speakers.append(Speaker(round(start * 1000), round(end * 1000), index + 1))
    return speakers


def timestamp(ms: int, separator: str) -> str:
    seconds, fraction = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{fraction:03}"


def write_subtitles(path: Path, cues: list[Cue], texts: list[str], speakers: list[Speaker]) -> None:
    if len(cues) != len(texts) or any(not text.strip() for text in texts):
        raise ValueError("Redacted captions no longer align with the timed cues.")
    vtt = path.suffix == ".vtt"
    separator = "." if vtt else ","
    blocks = ["WEBVTT"] if vtt else []
    for index, (cue, text) in enumerate(zip(cues, texts), start=1):
        by_overlap = max(
            ((min(cue.end, speaker.end) - max(cue.start, speaker.start), speaker.number) for speaker in speakers),
            default=(0, 0),
        )
        label = f"Speaker {by_overlap[1]}: " if by_overlap[0] > 0 else ""
        line = html.escape(label + text, quote=False)
        times = f"{timestamp(cue.start, separator)} --> {timestamp(cue.end, separator)}"
        blocks.append(f"{index}\n{times}\n{line}")
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")

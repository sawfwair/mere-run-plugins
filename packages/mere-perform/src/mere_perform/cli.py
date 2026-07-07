from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import functools
import hashlib
import html
import http.server
import json
import os
import pathlib
import re
import shlex
import shutil
import socketserver
import subprocess
import sys
import threading
import time
from typing import NoReturn, TextIO, cast

from . import __version__

JsonMap = dict[str, object]
JsonList = list[object]

PLUGIN_NAME = "mere-perform"
DEFAULT_MERE_RUN = "mere.run"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PALETTE = ["#ff2fb3", "#84f3ed", "#ffc23c", "#7fb2ff", "#ae5cff", "#ff4c8d", "#7c89ff", "#81d5fa"]
PROMPT_MODES = {"jam", "solo"}
PROMPT_ROLES = {"texture", "groove", "lead", "space", "room", "rhythm", "scene", "control"}
DEFAULT_PROMPT_STRATEGY: JsonMap = {
    "shape": "short musical anchors: genre, instrumentation, texture/production, energy",
    "blendModel": "inverse-distance prompt palette",
    "blendFalloff": 2.0,
    "promptDebounceMs": 400,
    "resetAfterPrompt": True,
}


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def eprint(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def print_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_json(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def fail(message: str, exit_code: int = 1) -> NoReturn:
    raise PluginError(message, exit_code)


def as_map(value: object, context: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    fail(f"{context} must be a JSON object", 2)


def as_list(value: object, context: str) -> JsonList:
    if isinstance(value, list):
        return value
    fail(f"{context} must be a JSON array", 2)


def string_field(mapping: JsonMap, key: str, context: str) -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    fail(f"{context}.{key} must be a string", 2)


def optional_string(mapping: JsonMap, key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) else None


def bool_value(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def float_value(value: object, default: float) -> float:
    if isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, float):
        return value
    return default


def int_value(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def clamped_int(value: object, default: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int_value(value, default)))


def normalize_label(value: object, default: str, allowed: set[str]) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized:
            return normalized if not allowed or normalized in allowed else default
    return default


def runtime_prompt_text(prompt: str, mode: str) -> str:
    if mode == "solo" and not prompt.lower().startswith("solo "):
        return "SOLO " + prompt
    return prompt


def runtime_scene_prompt(scene: JsonMap) -> str:
    return runtime_prompt_text(string_field(scene, "prompt", "scene"), optional_string(scene, "mode") or "jam")


def split_command(command: str) -> list[str]:
    parts = shlex.split(command)
    if not parts:
        fail("mere.run command cannot be empty", 2)
    return parts


def command_available(command: list[str]) -> bool:
    executable = command[0]
    if os.sep in executable:
        return pathlib.Path(executable).is_file()
    return shutil.which(executable) is not None


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        fail("--run-id must start with a letter or digit and contain only letters, digits, '.', '_', or '-'", 2)


def default_run_id() -> str:
    return "perform-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def payload_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def read_json(path: pathlib.Path) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), f"JSON file {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}", 2)


def update_manifest(path: pathlib.Path, manifest: JsonMap, **updates: object) -> None:
    manifest.update(updates)
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def plugin_manifest() -> JsonMap:
    commands = [
        {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
        {"name": "doctor", "description": "Check local realtime performance readiness.", "stdout": "json"},
        {"name": "plan", "description": "Write a performance run manifest without executing mere.run.", "stdout": "json"},
        {"name": "run", "description": "Execute a planned performance manifest.", "stdout": "json"},
        {"name": "resume", "description": "Inspect a recorded performance manifest.", "stdout": "json"},
        {"name": "cleanup", "description": "Mark local performance cleanup as skipped.", "stdout": "json"},
        {"name": "stage", "description": "Export or serve the magenta-heart stage UI for a run manifest.", "stdout": "json"},
        {"name": "devices", "description": "List realtime MIDI devices through mere.run.", "stdout": "json"},
        {"name": "show-template", "description": "Print a starter performance show file.", "stdout": "json"},
        {"name": "perform", "description": "Plan and run a performance in one command.", "stdout": "json"},
    ]
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": "mere-perform",
        "description": "Realtime audio-visual performance orchestration for local mere.run workflows.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-perform",
        "commands": commands,
        "capabilities": [
            "performance",
            "realtime-audio",
            "magenta-rt2",
            "midi",
            "stage-ui",
            "prompt-blending",
            "artifact-capture",
            "local-runner",
        ],
        "stdout": {
            "machineReadableByDefault": True,
            "diagnostics": "stderr",
        },
        "security": {
            "usesUserCredentials": False,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def template_show() -> JsonMap:
    return {
        "contractVersion": "mere.run/perform-show.v1",
        "title": "Magenta Heart Session",
        "durationSeconds": 30,
        "model": "music-magenta-rt2-small",
        "promptStrategy": {
            **DEFAULT_PROMPT_STRATEGY,
            "notes": [
                "Write compact musical anchors, not prose requests.",
                "Use roles so the stage can read the palette at a glance.",
                "Use solo mode for note-following leads; jam mode for full accompaniment.",
            ],
        },
        "audio": {
            "play": True,
            "capture": "live.wav",
        },
        "midi": {
            "input": None,
            "channel": "all",
            "noteOffset": 0,
            "keyboard": {
                "enabled": True,
                "baseNote": 60,
                "octaveRange": 2,
                "layout": "ableton",
            },
            "gate": {
                "enabled": True,
                "releaseMs": 900,
                "idleStopSeconds": 30,
            },
            "cc": ["1=temp:0.2:1.4", "2=drums:0:2", "3=mc:1:5"],
            "pads": [
                {"id": "pad-1", "label": "1", "sceneId": "ignite", "target": "scene"},
                {"id": "pad-2", "label": "2", "sceneId": "tilt", "target": "scene"},
                {"id": "pad-3", "label": "3", "sceneId": "cut", "target": "scene"},
                {"id": "pad-4", "label": "4", "sceneId": "afterglow", "target": "scene"},
            ],
            "activity": {
                "demoNotes": [60, 64, 67],
            },
        },
        "heart": {
            "x": 0.5,
            "y": 0.5,
            "color": "#ff2fb3",
        },
        "prompts": [
            {
                "id": "pulse",
                "role": "texture",
                "mode": "jam",
                "text": "drumless glassy arpeggios with soft tape hiss",
                "x": 0.50,
                "y": 0.16,
                "color": "#ff2fb3",
                "cfgMusicCoCa": 2.4,
                "resetAfterPrompt": True,
            },
            {
                "id": "rhythm",
                "role": "groove",
                "mode": "jam",
                "text": "afrobeat band with horns and complex drums",
                "x": 0.83,
                "y": 0.46,
                "color": "#84f3ed",
                "cfgMusicCoCa": 3.0,
                "resetAfterPrompt": True,
            },
            {
                "id": "lead",
                "role": "lead",
                "mode": "solo",
                "text": "distorted cello lead with long tremolo swells",
                "x": 0.52,
                "y": 0.84,
                "color": "#ffc23c",
                "cfgMusicCoCa": 3.5,
                "unmaskWidth": 127,
                "resetAfterPrompt": True,
            },
            {
                "id": "space",
                "role": "space",
                "mode": "jam",
                "text": "cavernous endless reverb electric guitar swells",
                "x": 0.18,
                "y": 0.48,
                "color": "#7fb2ff",
                "cfgMusicCoCa": 2.0,
                "resetAfterPrompt": True,
            },
        ],
        "scenes": [
            {"id": "ignite", "title": "Ignite", "durationSeconds": 8, "promptId": "pulse", "temperature": 0.92, "drumless": True},
            {"id": "tilt", "title": "Tilt", "durationSeconds": 8, "promptId": "rhythm", "temperature": 1.08},
            {"id": "cut", "title": "Cut", "durationSeconds": 7, "promptId": "lead", "temperature": 0.86},
            {"id": "afterglow", "title": "Afterglow", "durationSeconds": 7, "promptId": "space", "temperature": 0.78, "drumless": True},
        ],
    }


def load_show(path: pathlib.Path | None) -> JsonMap:
    if path is None:
        return template_show()
    show = read_json(path)
    if "contractVersion" in show and show["contractVersion"] != "mere.run/perform-show.v1":
        fail(f"{path}: unsupported show contractVersion", 2)
    return show


def normalize_prompt_nodes(show: JsonMap) -> list[JsonMap]:
    raw_prompts = show.get("prompts")
    if not isinstance(raw_prompts, list) or not raw_prompts:
        raw_prompt = optional_string(show, "prompt") or "drumless glassy arpeggios with soft tape hiss"
        raw_prompts = [{"id": "pulse", "text": raw_prompt, "x": 0.5, "y": 0.5}]
    prompts: list[JsonMap] = []
    for index, raw_prompt in enumerate(raw_prompts):
        if isinstance(raw_prompt, str):
            prompt: JsonMap = {"id": f"prompt-{index + 1}", "text": raw_prompt}
        else:
            prompt = as_map(raw_prompt, "show.prompts[]").copy()
        text = string_field(prompt, "text", "show prompt")
        prompt_id = optional_string(prompt, "id") or f"prompt-{index + 1}"
        mode = normalize_label(prompt.get("mode"), "jam", PROMPT_MODES)
        role = normalize_label(prompt.get("role"), "texture" if index == 0 else "control", PROMPT_ROLES)
        normalized: JsonMap = {
            "id": prompt_id,
            "role": role,
            "mode": mode,
            "text": text,
            "runtimeText": runtime_prompt_text(text, mode),
            "x": max(0.04, min(0.96, float_value(prompt.get("x"), 0.5))),
            "y": max(0.06, min(0.94, float_value(prompt.get("y"), 0.5))),
            "color": optional_string(prompt, "color") or PALETTE[index % len(PALETTE)],
            "weight": max(0.0, float_value(prompt.get("weight"), 1.0)),
        }
        for key in ("cfgMusicCoCa", "cfgNotes", "cfgDrums", "unmaskWidth"):
            if key in prompt:
                normalized[key] = float_value(prompt[key], 0.0)
        if mode == "solo" and "unmaskWidth" not in normalized:
            normalized["unmaskWidth"] = 127.0
        if "resetAfterPrompt" in prompt:
            normalized["resetAfterPrompt"] = bool_value(prompt["resetAfterPrompt"], False)
        if "promptDebounceMs" in prompt:
            normalized["promptDebounceMs"] = max(0, int_value(prompt["promptDebounceMs"], 0))
        prompts.append(normalized)
    return prompts


def prompt_by_id(prompts: list[JsonMap], prompt_id: str | None) -> JsonMap | None:
    if prompt_id is None:
        return None
    for prompt in prompts:
        if optional_string(prompt, "id") == prompt_id:
            return prompt
    fail(f"show.scenes[].promptId references unknown prompt id: {prompt_id}", 2)


def normalize_prompt_strategy(show: JsonMap) -> JsonMap:
    raw = show.get("promptStrategy")
    strategy = dict(DEFAULT_PROMPT_STRATEGY)
    if isinstance(raw, dict):
        raw_strategy = as_map(raw, "show.promptStrategy")
        if "shape" in raw_strategy:
            strategy["shape"] = string_field(raw_strategy, "shape", "show.promptStrategy")
        if "blendModel" in raw_strategy:
            strategy["blendModel"] = string_field(raw_strategy, "blendModel", "show.promptStrategy")
        if "blendFalloff" in raw_strategy:
            strategy["blendFalloff"] = max(0.1, float_value(raw_strategy["blendFalloff"], 2.0))
        if "promptDebounceMs" in raw_strategy:
            strategy["promptDebounceMs"] = max(0, int_value(raw_strategy["promptDebounceMs"], 400))
        if "resetAfterPrompt" in raw_strategy:
            strategy["resetAfterPrompt"] = bool_value(raw_strategy["resetAfterPrompt"], True)
        if isinstance(raw_strategy.get("notes"), list):
            strategy["notes"] = [str(item) for item in as_list(raw_strategy["notes"], "show.promptStrategy.notes")]
    return strategy


def normalize_midi_pads(raw_pads: object, scenes: list[JsonMap]) -> list[JsonMap]:
    scene_ids = {string_field(scene, "id", "scene") for scene in scenes}
    source_pads = raw_pads if isinstance(raw_pads, list) and raw_pads else [
        {"id": f"pad-{index + 1}", "label": str(index + 1), "sceneId": scene.get("id"), "target": "scene"}
        for index, scene in enumerate(scenes[:8])
    ]
    pads: list[JsonMap] = []
    for index, raw_pad in enumerate(source_pads):
        pad = as_map(raw_pad, "show.midi.pads[]").copy() if isinstance(raw_pad, dict) else {"label": str(raw_pad)}
        pad_id = optional_string(pad, "id") or f"pad-{index + 1}"
        label = optional_string(pad, "label") or str(index + 1)
        target = normalize_label(pad.get("target"), "scene", {"scene", "prompt", "control"})
        scene_id = optional_string(pad, "sceneId")
        if target == "scene" and scene_id is not None and scene_id not in scene_ids:
            fail(f"show.midi.pads[].sceneId references unknown scene id: {scene_id}", 2)
        normalized: JsonMap = {
            "id": pad_id,
            "label": label[:8],
            "target": target,
        }
        if scene_id is not None:
            normalized["sceneId"] = scene_id
        prompt_id = optional_string(pad, "promptId")
        if prompt_id is not None:
            normalized["promptId"] = prompt_id
        if "cc" in pad:
            normalized["cc"] = clamped_int(pad["cc"], 0, 0, 127)
        pads.append(normalized)
    return pads


def normalize_demo_notes(raw_notes: object) -> list[int]:
    if not isinstance(raw_notes, list):
        return [60, 64, 67]
    notes: list[int] = []
    for raw_note in raw_notes[:16]:
        notes.append(clamped_int(raw_note, 60, 0, 127))
    return notes


def normalize_midi_control(midi: JsonMap, scenes: list[JsonMap], args: argparse.Namespace) -> JsonMap:
    midi_cc = [str(item) for item in as_list(midi.get("cc"), "show.midi.cc")] if isinstance(midi.get("cc"), list) else []
    midi_cc.extend(args.midi_cc or [])
    keyboard = as_map(midi.get("keyboard"), "show.midi.keyboard") if isinstance(midi.get("keyboard"), dict) else {}
    gate = as_map(midi.get("gate"), "show.midi.gate") if isinstance(midi.get("gate"), dict) else {}
    activity = as_map(midi.get("activity"), "show.midi.activity") if isinstance(midi.get("activity"), dict) else {}
    note_offset = args.midi_note_offset if args.midi_note_offset is not None else int_value(midi.get("noteOffset"), 0)
    return {
        "input": args.midi_input or optional_string(midi, "input"),
        "channel": args.midi_channel or optional_string(midi, "channel") or "all",
        "noteOffset": max(-48, min(48, note_offset)),
        "cc": midi_cc,
        "keyboard": {
            "enabled": bool_value(keyboard.get("enabled"), True),
            "baseNote": clamped_int(keyboard.get("baseNote"), 60, 0, 127),
            "octaveRange": clamped_int(keyboard.get("octaveRange"), 2, 1, 4),
            "layout": optional_string(keyboard, "layout") or "ableton",
        },
        "gate": {
            "enabled": bool_value(gate.get("enabled"), True),
            "releaseMs": clamped_int(gate.get("releaseMs"), 900, 0, 10000),
            "idleStopSeconds": clamped_int(gate.get("idleStopSeconds"), 30, 0, 600),
        },
        "pads": normalize_midi_pads(midi.get("pads"), scenes),
        "activity": {
            "demoNotes": normalize_demo_notes(activity.get("demoNotes")),
        },
    }


def normalize_scenes(show: JsonMap, prompts: list[JsonMap], duration: float) -> list[JsonMap]:
    raw_scenes = show.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        return [{
            "id": "live",
            "title": "Live",
            "durationSeconds": duration,
            "prompt": string_field(prompts[0], "text", "prompt"),
            "promptId": optional_string(prompts[0], "id"),
            "role": optional_string(prompts[0], "role") or "texture",
            "mode": optional_string(prompts[0], "mode") or "jam",
            "runtimePrompt": string_field(prompts[0], "runtimeText", "prompt"),
        }]
    scenes: list[JsonMap] = []
    default_duration = max(0.1, duration / max(1, len(raw_scenes)))
    for index, raw_scene in enumerate(raw_scenes):
        scene = as_map(raw_scene, "show.scenes[]").copy()
        scene_id = optional_string(scene, "id") or f"scene-{index + 1}"
        scene_title = optional_string(scene, "title") or scene_id
        scene_prompt_id = optional_string(scene, "promptId")
        source_prompt = prompt_by_id(prompts, scene_prompt_id)
        if source_prompt is None and not optional_string(scene, "prompt"):
            source_prompt = prompts[min(index, len(prompts) - 1)]
            scene_prompt_id = optional_string(source_prompt, "id")
        prompt = optional_string(scene, "prompt")
        if prompt is None and source_prompt is not None:
            prompt = string_field(source_prompt, "text", "prompt")
        elif prompt is None:
            prompt = string_field(prompts[min(index, len(prompts) - 1)], "text", "prompt")
        role = normalize_label(scene.get("role"), optional_string(source_prompt or {}, "role") or "scene", PROMPT_ROLES)
        mode = normalize_label(scene.get("mode"), optional_string(source_prompt or {}, "mode") or "jam", PROMPT_MODES)
        normalized: JsonMap = {
            "id": scene_id,
            "title": scene_title,
            "durationSeconds": max(0.1, float_value(scene.get("durationSeconds"), default_duration)),
            "promptId": scene_prompt_id,
            "role": role,
            "mode": mode,
            "prompt": prompt,
            "runtimePrompt": runtime_prompt_text(prompt, mode),
        }
        for key in ("temperature", "topK", "cfgMusicCoCa", "cfgNotes", "cfgDrums", "unmaskWidth"):
            if key in scene:
                normalized[key] = float_value(scene[key], 0.0)
            elif source_prompt is not None and key in source_prompt:
                normalized[key] = float_value(source_prompt[key], 0.0)
        if mode == "solo" and "unmaskWidth" not in normalized:
            normalized["unmaskWidth"] = 127.0
        if "drumless" in scene:
            normalized["drumless"] = bool_value(scene["drumless"], False)
        if "resetAfterPrompt" in scene:
            normalized["resetAfterPrompt"] = bool_value(scene["resetAfterPrompt"], False)
        elif source_prompt is not None and "resetAfterPrompt" in source_prompt:
            normalized["resetAfterPrompt"] = bool_value(source_prompt["resetAfterPrompt"], False)
        if "promptDebounceMs" in scene:
            normalized["promptDebounceMs"] = max(0, int_value(scene["promptDebounceMs"], 0))
        elif source_prompt is not None and "promptDebounceMs" in source_prompt:
            normalized["promptDebounceMs"] = max(0, int_value(source_prompt["promptDebounceMs"], 0))
        scenes.append(normalized)
    return scenes


def normalize_show(show: JsonMap, args: argparse.Namespace) -> JsonMap:
    duration = args.duration if args.duration is not None else float_value(show.get("durationSeconds"), 30.0)
    if duration <= 0:
        fail("--duration must be greater than 0", 2)
    prompts = normalize_prompt_nodes(show)
    scenes = normalize_scenes(show, prompts, duration)
    prompt_strategy = normalize_prompt_strategy(show)
    audio = as_map(show.get("audio"), "show.audio") if isinstance(show.get("audio"), dict) else {}
    midi = as_map(show.get("midi"), "show.midi") if isinstance(show.get("midi"), dict) else {}
    heart = as_map(show.get("heart"), "show.heart") if isinstance(show.get("heart"), dict) else {}
    title = optional_string(show, "title") or "Magenta Heart Session"
    return {
        "contractVersion": "mere.run/perform-show.v1",
        "title": title,
        "durationSeconds": duration,
        "model": args.model or optional_string(show, "model") or "music-magenta-rt2-small",
        "promptStrategy": prompt_strategy,
        "audio": {
            "play": not args.no_play if args.no_play else bool_value(audio.get("play"), True),
            "capture": args.capture or optional_string(audio, "capture") or "live.wav",
        },
        "midi": normalize_midi_control(midi, scenes, args),
        "heart": {
            "x": max(0.04, min(0.96, float_value(heart.get("x"), 0.5))),
            "y": max(0.06, min(0.94, float_value(heart.get("y"), 0.5))),
            "color": optional_string(heart, "color") or "#ff2fb3",
        },
        "prompts": prompts,
        "scenes": scenes,
    }


def initial_prompt(show: JsonMap) -> str:
    scenes = as_list(show["scenes"], "show.scenes")
    if scenes:
        return string_field(as_map(scenes[0], "scene"), "prompt", "scene")
    prompts = as_list(show["prompts"], "show.prompts")
    return string_field(as_map(prompts[0], "prompt"), "text", "prompt")


def initial_runtime_prompt(show: JsonMap) -> str:
    scenes = as_list(show["scenes"], "show.scenes")
    if scenes:
        return runtime_scene_prompt(as_map(scenes[0], "scene"))
    prompts = as_list(show["prompts"], "show.prompts")
    prompt = as_map(prompts[0], "prompt")
    return runtime_prompt_text(string_field(prompt, "text", "prompt"), optional_string(prompt, "mode") or "jam")


def manifest_paths(args: argparse.Namespace, show: JsonMap) -> JsonMap:
    output_dir = args.output_dir
    manifest_path = args.manifest or output_dir / "run.json"
    capture_name = string_field(as_map(show["audio"], "show.audio"), "capture", "show.audio")
    capture_path = pathlib.Path(capture_name)
    if not capture_path.is_absolute():
        capture_path = output_dir / capture_path
    stage_dir = output_dir / "stage"
    return {
        "outputDirectory": str(output_dir),
        "runManifest": str(manifest_path),
        "audioCapture": str(capture_path),
        "eventsJsonl": str(output_dir / "events.jsonl"),
        "stageDirectory": str(stage_dir),
        "stageHtml": str(stage_dir / "index.html"),
        "stageState": str(stage_dir / "state.json"),
        "showJson": str(output_dir / "show.json"),
    }


def command_for_manifest(manifest: JsonMap) -> list[str]:
    runtime = as_map(manifest["runtime"], "runtime")
    show = as_map(as_map(manifest["performance"], "performance")["show"], "performance.show")
    audio = as_map(show["audio"], "show.audio")
    midi = as_map(show["midi"], "show.midi")
    paths = as_map(manifest["local"], "local")
    command = [
        *as_list(runtime["mereRunCommand"], "runtime.mereRunCommand"),
        "music",
        "realtime",
        initial_runtime_prompt(show),
        "--model",
        string_field(show, "model", "show"),
        "--duration",
        str(float_value(show.get("durationSeconds"), 30.0)),
        "--output",
        string_field(paths, "audioCapture", "local"),
        "--interactive",
    ]
    command.append("--play" if bool_value(audio.get("play"), True) else "--no-play")
    midi_input = optional_string(midi, "input")
    if midi_input:
        command.extend(["--midi-input", midi_input])
    midi_channel = optional_string(midi, "channel")
    if midi_channel:
        command.extend(["--midi-channel", midi_channel])
    note_offset = int_value(midi.get("noteOffset"), 0)
    if note_offset:
        command.extend(["--midi-note-offset", str(note_offset)])
    for raw_cc in as_list(midi.get("cc"), "show.midi.cc") if isinstance(midi.get("cc"), list) else []:
        command.extend(["--midi-cc", str(raw_cc)])
    return [str(part) for part in command]


def make_manifest(args: argparse.Namespace) -> JsonMap:
    raw_show = load_show(args.show)
    show = normalize_show(raw_show, args)
    paths = manifest_paths(args, show)
    created = now_iso()
    dataset_path = str(args.show) if args.show else str(args.output_dir)
    manifest: JsonMap = {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {"id": "magenta-heart-performance", "family": "realtime-performance", "title": "Magenta Heart performance"},
        "status": "planned",
        "createdAt": created,
        "updatedAt": created,
        "dataset": {
            "path": dataset_path,
            "pairCount": max(1, len(as_list(show["prompts"], "show.prompts")) + len(as_list(show["scenes"], "show.scenes"))),
            "sha256": payload_sha256(raw_show),
        },
        "command": [],
        "local": paths,
        "runtime": {
            "backend": "mere.run/music-realtime",
            "mereRunCommand": split_command(args.mere_run_command),
        },
        "performance": {
            "mode": "magenta-heart",
            "initialPrompt": initial_prompt(show),
            "initialRuntimePrompt": initial_runtime_prompt(show),
            "show": show,
            "stage": {
                "host": args.stage_host,
                "port": args.stage_port,
                "entrypoint": str(paths["stageHtml"]),
            },
        },
        "artifacts": {
            "localDirectory": str(args.output_dir),
            "audioCapture": str(paths["audioCapture"]),
            "eventsJsonl": str(paths["eventsJsonl"]),
            "stageDirectory": str(paths["stageDirectory"]),
            "stageHtml": str(paths["stageHtml"]),
            "stageState": str(paths["stageState"]),
            "showJson": str(paths["showJson"]),
            "files": [],
            "items": [],
            "sha256": {},
        },
        "cleanup": {"default": "none", "status": "not-started"},
    }
    manifest["command"] = command_for_manifest(manifest)
    return manifest


def append_event(manifest: JsonMap, event: JsonMap) -> None:
    paths = as_map(manifest["local"], "local")
    events_path = pathlib.Path(string_field(paths, "eventsJsonl", "local"))
    events_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"at": now_iso(), "runId": manifest.get("runId"), **event}
    with events_path.open("a") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def stage_html(manifest: JsonMap) -> str:
    state = json.dumps(stage_state(manifest), sort_keys=True)
    escaped_state = html.escape(state, quote=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>mere.perform</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: oklch(0.145 0.018 314);
      --ink: oklch(0.955 0.012 314);
      --muted: oklch(0.72 0.028 314);
      --rail: oklch(0.205 0.024 314);
      --line: oklch(0.38 0.04 314);
      --heart: oklch(0.69 0.31 342);
      --cyan: oklch(0.86 0.15 190);
      --amber: oklch(0.83 0.16 82);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; background: var(--bg); color: var(--ink); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }}
    body {{ overflow: hidden; }}
    .shell {{ height: 100%; display: grid; grid-template-columns: minmax(0, 1fr) 320px; }}
    .stage {{ position: relative; min-width: 0; min-height: 0; background:
      radial-gradient(circle at 50% 48%, oklch(0.22 0.048 326) 0%, transparent 38%),
      linear-gradient(145deg, oklch(0.16 0.026 292), oklch(0.12 0.022 336)); }}
    canvas {{ width: 100%; height: 100%; }}
    .brand {{ position: absolute; left: 28px; top: 22px; display: flex; flex-direction: column; gap: 6px; pointer-events: none; }}
    .brand strong {{ font-size: 13px; letter-spacing: 0.16em; text-transform: uppercase; }}
    .brand span {{ color: var(--muted); font-size: 13px; max-width: 62ch; }}
    .rail {{ border-left: 1px solid var(--line); background: color-mix(in oklch, var(--rail) 86%, var(--bg)); padding: 20px; display: grid; grid-template-rows: auto auto minmax(0, 1fr) minmax(0, 0.85fr) auto; gap: 18px; min-width: 0; min-height: 0; overflow: hidden; }}
    .section {{ display: flex; flex-direction: column; gap: 12px; min-width: 0; min-height: 0; }}
    .kicker {{ color: var(--muted); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; }}
    h1 {{ font-size: 22px; line-height: 1.15; margin: 0; font-weight: 650; letter-spacing: 0; }}
    .readout {{ display: grid; grid-template-columns: 1fr auto; gap: 8px 12px; font-size: 13px; color: var(--muted); }}
    .readout b {{ color: var(--ink); font-weight: 600; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .scene-list, .prompt-list {{ display: flex; flex-direction: column; gap: 10px; overflow: auto; padding-right: 2px; }}
    .scene {{ border: 1px solid color-mix(in oklch, var(--line), transparent 22%); border-radius: 8px; padding: 10px 11px; display: grid; gap: 6px; background: oklch(0.18 0.022 314); }}
    .scene.current {{ border-color: var(--heart); box-shadow: 0 0 0 1px color-mix(in oklch, var(--heart), transparent 60%); }}
    .scene strong, .prompt-card strong {{ font-size: 13px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .scene span, .prompt-card span {{ color: var(--muted); font-size: 12px; line-height: 1.35; overflow-wrap: anywhere; }}
    .scene small, .prompt-card small {{ color: color-mix(in oklch, var(--muted), var(--ink) 18%); font-size: 11px; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .prompt-card {{ border: 1px solid color-mix(in oklch, var(--line), transparent 34%); border-radius: 8px; padding: 9px 10px; display: grid; gap: 6px; background: oklch(0.165 0.021 314); }}
    .prompt-card.current {{ border-color: var(--cyan); background: oklch(0.19 0.028 306); }}
    .prompt-top {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px; }}
    .badge {{ border: 1px solid color-mix(in oklch, var(--line), transparent 18%); border-radius: 999px; padding: 2px 7px; color: var(--ink); font-size: 10px; line-height: 1.3; text-transform: uppercase; letter-spacing: 0.08em; }}
    .controller {{ position: absolute; left: 24px; right: 24px; bottom: 22px; display: grid; gap: 10px; pointer-events: auto; }}
    .midi-strip {{ display: flex; align-items: center; gap: 10px; min-width: 0; color: var(--muted); font-size: 12px; }}
    .midi-strip strong {{ color: var(--ink); font-size: 12px; letter-spacing: 0.11em; text-transform: uppercase; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .midi-strip span {{ border: 1px solid color-mix(in oklch, var(--line), transparent 20%); border-radius: 999px; padding: 3px 8px; background: oklch(0.17 0.022 314 / 0.78); white-space: nowrap; }}
    .midi-led {{ width: 8px; height: 8px; border-radius: 50%; background: oklch(0.58 0.02 314); box-shadow: 0 0 0 1px color-mix(in oklch, var(--line), transparent 25%); flex: 0 0 auto; }}
    .midi-led.active {{ background: oklch(0.82 0.22 148); box-shadow: 0 0 18px oklch(0.82 0.22 148 / 0.65); }}
    .pads {{ display: flex; gap: 8px; min-width: 0; overflow: hidden; }}
    .pad {{ min-width: 42px; height: 34px; border: 1px solid color-mix(in oklch, var(--line), transparent 18%); border-radius: 8px; background: oklch(0.18 0.024 314 / 0.9); color: var(--ink); font: 650 12px -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui; }}
    .pad.current {{ border-color: var(--heart); background: oklch(0.26 0.075 336 / 0.92); box-shadow: 0 0 0 1px color-mix(in oklch, var(--heart), transparent 54%); }}
    .piano {{ --white-count: 17; position: relative; height: 58px; border: 1px solid color-mix(in oklch, var(--line), transparent 14%); border-radius: 8px; overflow: hidden; background: oklch(0.105 0.014 314 / 0.92); box-shadow: inset 0 1px 0 oklch(0.94 0.012 314 / 0.12); }}
    .white-keys {{ position: absolute; inset: 0; display: grid; grid-template-columns: repeat(var(--white-count), minmax(0, 1fr)); }}
    .black-keys {{ position: absolute; inset: 0; pointer-events: none; }}
    .key {{ min-width: 0; border: 0; font: 650 10px -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui; display: flex; align-items: flex-end; justify-content: center; touch-action: none; user-select: none; }}
    .key.white {{ height: 100%; padding: 0 2px 5px; background: linear-gradient(180deg, oklch(0.965 0.008 314), oklch(0.84 0.012 314)); color: oklch(0.22 0.022 314); border-right: 1px solid oklch(0.36 0.022 314 / 0.44); box-shadow: inset 0 -7px 10px oklch(0.46 0.02 314 / 0.16); }}
    .key.white:last-child {{ border-right: 0; }}
    .key.black {{ position: absolute; top: 0; width: calc(100% / var(--white-count) * 0.58); height: 63%; transform: translateX(-50%); z-index: 2; padding: 0 1px 5px; border-radius: 0 0 5px 5px; background: linear-gradient(180deg, oklch(0.18 0.02 314), oklch(0.055 0.012 314)); color: oklch(0.82 0.018 314); border: 1px solid oklch(0.31 0.035 314 / 0.78); border-top: 0; box-shadow: 0 6px 10px oklch(0.03 0.01 314 / 0.48), inset 0 -5px 7px oklch(0.01 0.008 314 / 0.42); pointer-events: auto; }}
    .key.active {{ background: linear-gradient(180deg, oklch(0.82 0.29 342), var(--heart)); color: oklch(0.985 0.01 342); box-shadow: inset 0 0 0 1px oklch(0.98 0.03 342), 0 0 16px oklch(0.69 0.31 342 / 0.55); }}
    .key.black.active {{ background: linear-gradient(180deg, oklch(0.78 0.28 342), oklch(0.47 0.24 342)); box-shadow: 0 6px 16px oklch(0.69 0.31 342 / 0.66), inset 0 0 0 1px oklch(0.98 0.03 342); }}
    .controller-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .control-chip {{ border: 1px solid color-mix(in oklch, var(--line), transparent 28%); border-radius: 8px; padding: 8px 9px; background: oklch(0.165 0.021 314); display: grid; gap: 2px; min-width: 0; }}
    .control-chip span {{ color: var(--muted); font-size: 10px; letter-spacing: 0.09em; text-transform: uppercase; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .control-chip b {{ color: var(--ink); font-size: 12px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .meter {{ height: 6px; background: oklch(0.26 0.025 314); overflow: hidden; }}
    .meter i {{ display: block; height: 100%; width: 0%; background: linear-gradient(90deg, var(--heart), var(--cyan), var(--amber)); }}
    .footer {{ color: var(--muted); font-size: 12px; line-height: 1.5; }}
    @media (max-width: 820px) {{
      .shell {{ grid-template-columns: 1fr; grid-template-rows: minmax(0, 1fr) auto; }}
      .rail {{ border-left: 0; border-top: 1px solid var(--line); display: flex; flex-direction: column; max-height: 42vh; overflow: auto; padding: 18px 20px; }}
      .rail > .section, .rail > .footer {{ flex: 0 0 auto; }}
      .readout {{ grid-template-columns: auto minmax(0, 1fr); }}
      .controller {{ left: 14px; right: 14px; bottom: 14px; }}
      .midi-strip {{ display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 6px; }}
      .midi-strip span:nth-of-type(n+2) {{ display: none; }}
      .pads {{ display: none; }}
      .piano {{ height: 50px; }}
      .key {{ font-size: 0; padding: 0; }}
      .key.black {{ height: 60%; }}
    }}
  </style>
</head>
<body>
  <script id="mere-perform-state" type="application/json">{escaped_state}</script>
  <main class="shell">
    <section class="stage" aria-label="Magenta heart stage">
      <canvas id="stage"></canvas>
      <div class="brand">
        <strong>mere.perform</strong>
        <span id="prompt-line"></span>
      </div>
      <div class="controller" aria-label="MIDI performance controller">
        <div class="midi-strip">
          <strong id="midi-source"></strong>
          <span id="midi-gate"></span>
          <span id="midi-offset"></span>
          <span id="midi-notes"></span>
          <i id="midi-led" class="midi-led"></i>
        </div>
        <div id="midi-pads" class="pads"></div>
        <div id="piano" class="piano"></div>
      </div>
    </section>
    <aside class="rail">
      <div class="section">
        <span class="kicker">Magenta Heart</span>
        <h1 id="title"></h1>
        <div class="readout">
          <span>model</span><b id="model"></b>
          <span>duration</span><b id="duration"></b>
          <span>strategy</span><b id="strategy"></b>
          <span>audio</span><b id="audio"></b>
          <span>midi</span><b id="midi"></b>
        </div>
        <div class="meter"><i id="meter"></i></div>
      </div>
      <div class="section">
        <span class="kicker">Controller</span>
        <div class="controller-grid">
          <div class="control-chip"><span>source</span><b id="controller-source"></b></div>
          <div class="control-chip"><span>channel</span><b id="controller-channel"></b></div>
          <div class="control-chip"><span>gate</span><b id="controller-gate"></b></div>
          <div class="control-chip"><span>keys</span><b id="controller-keys"></b></div>
        </div>
      </div>
      <div class="section">
        <span class="kicker">Scenes</span>
        <div id="scenes" class="scene-list"></div>
      </div>
      <div class="section">
        <span class="kicker">Prompt Palette</span>
        <div id="prompts" class="prompt-list"></div>
      </div>
      <div class="footer" id="footer"></div>
    </aside>
  </main>
  <script>
    const state = JSON.parse(document.getElementById('mere-perform-state').textContent);
    const show = state.show;
    const midi = show.midi || {{}};
    const canvas = document.getElementById('stage');
    const ctx = canvas.getContext('2d');
    const meter = document.getElementById('meter');
    const scenesEl = document.getElementById('scenes');
    const promptsEl = document.getElementById('prompts');
    const padsEl = document.getElementById('midi-pads');
    const pianoEl = document.getElementById('piano');
    const midiLed = document.getElementById('midi-led');
    const activeNotes = new Set((midi.activity?.demoNotes || []).filter(note => Number.isFinite(note)));
    const pressedKeys = new Map();
    let manualSceneIndex = null;
    let manualSceneUntil = 0;
    const keyToSemitone = {{ a: 0, w: 1, s: 2, e: 3, d: 4, f: 5, t: 6, g: 7, y: 8, h: 9, u: 10, j: 11, k: 12, o: 13, l: 14, p: 15, ';': 16 }};
    const keyboard = midi.keyboard || {{}};
    const gate = midi.gate || {{}};
    const keyboardBaseNote = Number.isFinite(keyboard.baseNote) ? keyboard.baseNote : 60;
    const noteCount = Math.max(13, Math.min(29, 12 * (Number.isFinite(keyboard.octaveRange) ? keyboard.octaveRange : 2) + 5));
    const noteNames = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    function noteName(note) {{
      return `${{noteNames[((note % 12) + 12) % 12]}}${{Math.floor(note / 12) - 1}}`;
    }}
    function isBlack(note) {{
      return [1, 3, 6, 8, 10].includes(((note % 12) + 12) % 12);
    }}
    function buildKeyboard() {{
      const notes = Array.from({{ length: noteCount }}, (_, offset) => keyboardBaseNote + offset);
      const whiteNotes = notes.filter(note => !isBlack(note));
      const whiteIndexByNote = new Map();
      whiteNotes.forEach((note, index) => whiteIndexByNote.set(note, index));
      return {{ notes, whiteNotes, whiteIndexByNote }};
    }}
    function addPianoKey(parent, note, tone) {{
      const key = document.createElement('button');
      key.type = 'button';
      key.className = `key ${{tone}}${{activeNotes.has(note) ? ' active' : ''}}`;
      key.textContent = noteName(note);
      key.setAttribute('aria-label', noteName(note));
      key.addEventListener('pointerdown', () => setNote(note, true));
      key.addEventListener('pointerup', () => setNote(note, false));
      key.addEventListener('pointercancel', () => setNote(note, false));
      key.addEventListener('pointerleave', () => setNote(note, false));
      parent.appendChild(key);
      return key;
    }}
    function updateMidiReadouts() {{
      const source = midi.input || (keyboard.enabled ? 'computer keyboard' : 'none');
      const noteLabel = activeNotes.size ? `${{activeNotes.size}} held` : 'idle';
      document.getElementById('midi-source').textContent = source;
      document.getElementById('midi-gate').textContent = gate.enabled ? 'gate on' : 'gate off';
      document.getElementById('midi-offset').textContent = `offset ${{midi.noteOffset || 0}}`;
      document.getElementById('midi-notes').textContent = noteLabel;
      document.getElementById('controller-source').textContent = source;
      document.getElementById('controller-channel').textContent = midi.channel || 'all';
      document.getElementById('controller-gate').textContent = gate.enabled ? `${{gate.releaseMs || 0}}ms` : 'off';
      document.getElementById('controller-keys').textContent = keyboard.enabled ? `${{noteName(keyboardBaseNote)}} + ${{noteCount}}` : 'disabled';
      midiLed.classList.toggle('active', activeNotes.size > 0);
    }}
    function setNote(note, on) {{
      if (on) activeNotes.add(note);
      else activeNotes.delete(note);
      renderPiano();
      updateMidiReadouts();
    }}
    function renderPiano() {{
      const {{ notes, whiteNotes, whiteIndexByNote }} = buildKeyboard();
      pianoEl.style.setProperty('--white-count', String(whiteNotes.length));
      pianoEl.replaceChildren();
      const whiteLayer = document.createElement('div');
      const blackLayer = document.createElement('div');
      whiteLayer.className = 'white-keys';
      blackLayer.className = 'black-keys';
      whiteNotes.forEach(note => addPianoKey(whiteLayer, note, 'white'));
      notes.filter(isBlack).forEach(note => {{
        const previousWhiteIndex = whiteIndexByNote.get(note - 1);
        if (previousWhiteIndex === undefined) return;
        const key = addPianoKey(blackLayer, note, 'black');
        key.style.left = `${{((previousWhiteIndex + 1) / whiteNotes.length) * 100}}%`;
      }});
      pianoEl.append(whiteLayer, blackLayer);
    }}
    document.getElementById('title').textContent = show.title;
    document.getElementById('model').textContent = show.model;
    document.getElementById('duration').textContent = `${{Math.round(show.durationSeconds)}}s`;
    document.getElementById('strategy').textContent = `${{show.prompts.length}} anchors`;
    document.getElementById('audio').textContent = show.audio.play ? 'play + capture' : 'capture only';
    document.getElementById('midi').textContent = midi.input || (keyboard.enabled ? 'computer keys' : 'none');
    document.getElementById('footer').textContent = `run ${{state.runId}} · ${{state.status}}`;
    const sceneNodes = show.scenes.map((scene, index) => {{
      const el = document.createElement('div');
      el.className = 'scene';
      const title = document.createElement('strong');
      title.textContent = scene.title || scene.id;
      const meta = document.createElement('small');
      meta.textContent = [scene.promptId, scene.role, scene.mode, scene.cfgMusicCoCa ? `mc ${{scene.cfgMusicCoCa}}` : ''].filter(Boolean).join(' · ');
      const prompt = document.createElement('span');
      prompt.textContent = scene.prompt;
      el.append(title, meta, prompt);
      scenesEl.appendChild(el);
      return el;
    }});
    const padNodes = (midi.pads || []).map((pad, index) => {{
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'pad';
      button.textContent = pad.label || String(index + 1);
      button.addEventListener('click', () => {{
        const targetIndex = show.scenes.findIndex(scene => scene.id === pad.sceneId);
        if (targetIndex >= 0) {{
          manualSceneIndex = targetIndex;
          manualSceneUntil = performance.now() + 4200;
        }}
      }});
      padsEl.appendChild(button);
      return {{ pad, button }};
    }});
    const promptNodes = show.prompts.map(prompt => {{
      const el = document.createElement('div');
      el.className = 'prompt-card';
      el.style.borderColor = prompt.color;
      const top = document.createElement('div');
      top.className = 'prompt-top';
      const title = document.createElement('strong');
      title.textContent = prompt.id;
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = prompt.role || 'prompt';
      top.append(title, badge);
      const meta = document.createElement('small');
      meta.textContent = [prompt.mode || 'jam', prompt.cfgMusicCoCa ? `mc ${{prompt.cfgMusicCoCa}}` : '', prompt.resetAfterPrompt ? 'reset' : ''].filter(Boolean).join(' · ');
      const text = document.createElement('span');
      text.textContent = prompt.text;
      el.append(top, meta, text);
      promptsEl.appendChild(el);
      return el;
    }});
    renderPiano();
    updateMidiReadouts();
    if (keyboard.enabled) {{
      window.addEventListener('keydown', event => {{
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        const semi = keyToSemitone[event.key.toLowerCase()];
        if (semi === undefined || event.repeat) return;
        const note = keyboardBaseNote + semi;
        if (note < 0 || note > 127) return;
        event.preventDefault();
        pressedKeys.set(event.key.toLowerCase(), note);
        setNote(note, true);
      }});
      window.addEventListener('keyup', event => {{
        const key = event.key.toLowerCase();
        const note = pressedKeys.get(key);
        if (note === undefined) return;
        pressedKeys.delete(key);
        setNote(note, false);
      }});
      window.addEventListener('blur', () => {{
        pressedKeys.forEach(note => setNote(note, false));
        pressedKeys.clear();
      }});
    }}
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    function resize() {{
      const r = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(r.width * dpr));
      canvas.height = Math.max(1, Math.floor(r.height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }}
    window.addEventListener('resize', resize);
    resize();
    function heartPath(cx, cy, s) {{
      ctx.beginPath();
      ctx.moveTo(cx, cy + s * 0.32);
      ctx.bezierCurveTo(cx - s * 1.05, cy - s * 0.24, cx - s * 0.55, cy - s * 0.86, cx, cy - s * 0.35);
      ctx.bezierCurveTo(cx + s * 0.55, cy - s * 0.86, cx + s * 1.05, cy - s * 0.24, cx, cy + s * 0.32);
      ctx.closePath();
    }}
    function colorAlpha(color, alpha) {{
      if (/^#[0-9a-f]{{6}}$/i.test(color)) {{
        return color + Math.floor(Math.max(0, Math.min(1, alpha)) * 255).toString(16).padStart(2, '0');
      }}
      return color;
    }}
    function draw(t) {{
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);
      const total = Math.max(0.1, show.durationSeconds);
      const elapsed = (t / 1000) % total;
      let cursor = 0;
      let sceneIndex = 0;
      for (let i = 0; i < show.scenes.length; i++) {{
        const dur = show.scenes[i].durationSeconds || total / show.scenes.length;
        if (elapsed >= cursor && elapsed < cursor + dur) {{ sceneIndex = i; break; }}
        cursor += dur;
      }}
      if (manualSceneIndex !== null && t < manualSceneUntil) {{
        sceneIndex = manualSceneIndex;
      }} else if (manualSceneIndex !== null) {{
        manualSceneIndex = null;
      }}
      sceneNodes.forEach((el, i) => el.classList.toggle('current', i === sceneIndex));
      const scene = show.scenes[sceneIndex] || show.scenes[0];
      padNodes.forEach(({{pad, button}}) => button.classList.toggle('current', pad.sceneId === scene.id));
      promptNodes.forEach((el, i) => {{
        const prompt = show.prompts[i];
        const active = prompt.id === scene.promptId || prompt.text === scene.prompt;
        el.classList.toggle('current', active);
      }});
      document.getElementById('prompt-line').textContent = `${{scene.role || 'scene'}} · ${{scene.prompt}}`;
      const noteBoost = Math.min(0.22, activeNotes.size * 0.055);
      const energy = 0.48 + noteBoost + Math.sin(t / 210) * 0.22 + Math.sin(t / 89) * 0.08;
      meter.style.width = `${{Math.max(0, Math.min(1, energy)) * 100}}%`;
      const heart = show.heart || {{x: 0.5, y: 0.5, color: '#ff2fb3'}};
      const hx = heart.x * w + Math.sin(t / 1800) * w * 0.08;
      const hy = heart.y * h + Math.cos(t / 2200) * h * 0.06;
      show.prompts.forEach((p, i) => {{
        const px = p.x * w;
        const py = p.y * h;
        const dx = px - hx;
        const dy = py - hy;
        const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const active = p.id === scene.promptId || p.text === scene.prompt;
        const weight = Math.min(1, 36000 / (dist * dist)) + (active ? 0.18 : 0);
        ctx.strokeStyle = colorAlpha(p.color, 0.28 + Math.min(1, weight) * 0.48);
        ctx.lineWidth = 1 + weight * 3;
        ctx.beginPath();
        ctx.moveTo(hx, hy);
        ctx.lineTo(px, py);
        ctx.stroke();
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(px, py, 8 + Math.min(1, weight) * 10 + (active ? 4 : 0), 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = 'rgba(250,246,255,0.82)';
        ctx.font = '12px -apple-system, BlinkMacSystemFont, Segoe UI, system-ui';
        const label = `${{p.id}} · ${{p.role || p.mode || 'prompt'}}`;
        const labelWidth = ctx.measureText(label).width;
        let labelX = px + 14;
        if (labelX + labelWidth > w - 14) {{
          labelX = px - labelWidth - 14;
        }}
        labelX = Math.max(14, Math.min(labelX, w - labelWidth - 14));
        ctx.fillText(label, labelX, py + 4);
      }});
      for (let ring = 0; ring < 4; ring++) {{
        ctx.strokeStyle = `rgba(255,47,179,${{0.18 - ring * 0.035}})`;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(hx, hy, 42 + ring * 34 + energy * 18, 0, Math.PI * 2);
        ctx.stroke();
      }}
      ctx.shadowColor = 'rgba(255,47,179,0.55)';
      ctx.shadowBlur = 30;
      ctx.fillStyle = heart.color || '#ff2fb3';
      heartPath(hx, hy, 42 + energy * 8);
      ctx.fill();
      ctx.shadowBlur = 0;
      Array.from(activeNotes).slice(0, 8).forEach((note, index) => {{
        const angle = -Math.PI * 0.82 + index * 0.23 + Math.sin(t / 900 + index) * 0.06;
        const radius = 76 + (note % 12) * 7;
        const nx = hx + Math.cos(angle) * radius;
        const ny = hy + Math.sin(angle) * radius;
        ctx.fillStyle = index % 2 ? 'rgba(132,243,237,0.88)' : 'rgba(255,194,60,0.88)';
        ctx.beginPath();
        ctx.arc(nx, ny, 5 + Math.sin(t / 120 + index) * 1.5, 0, Math.PI * 2);
        ctx.fill();
      }});
      requestAnimationFrame(draw);
    }}
    requestAnimationFrame(draw);
  </script>
</body>
</html>
"""


def stage_state(manifest: JsonMap) -> JsonMap:
    performance = as_map(manifest["performance"], "performance")
    return {
        "runId": manifest.get("runId"),
        "status": manifest.get("status"),
        "plugin": manifest.get("plugin"),
        "show": performance["show"],
        "artifacts": manifest.get("artifacts"),
    }


def write_stage_assets(manifest: JsonMap) -> JsonMap:
    local = as_map(manifest["local"], "local")
    artifacts = as_map(manifest["artifacts"], "artifacts")
    stage_dir = pathlib.Path(string_field(local, "stageDirectory", "local"))
    stage_dir.mkdir(parents=True, exist_ok=True)
    html_path = pathlib.Path(string_field(local, "stageHtml", "local"))
    state_path = pathlib.Path(string_field(local, "stageState", "local"))
    show_path = pathlib.Path(string_field(local, "showJson", "local"))
    html_path.write_text(stage_html(manifest))
    write_json(state_path, stage_state(manifest))
    write_json(show_path, as_map(as_map(manifest["performance"], "performance")["show"], "performance.show"))
    artifacts["stageHtml"] = str(html_path)
    artifacts["stageState"] = str(state_path)
    artifacts["showJson"] = str(show_path)
    return {"stageHtml": str(html_path), "stageState": str(state_path), "showJson": str(show_path)}


def send_scene_commands(stdin: TextIO, manifest: JsonMap) -> None:
    show = as_map(as_map(manifest["performance"], "performance")["show"], "performance.show")
    scenes = [as_map(item, "scene") for item in as_list(show["scenes"], "show.scenes")]
    if len(scenes) <= 1:
        return
    strategy = as_map(show.get("promptStrategy"), "show.promptStrategy") if isinstance(show.get("promptStrategy"), dict) else {}
    previous = scenes[0]
    for scene in scenes[1:]:
        time.sleep(max(0.0, float_value(previous.get("durationSeconds"), 0.1)))
        prompt = string_field(scene, "prompt", "scene")
        stdin.write(f"prompt {runtime_scene_prompt(scene)}\n")
        for key, command_name in (
            ("temperature", "temp"),
            ("topK", "topk"),
            ("cfgMusicCoCa", "mc"),
            ("cfgNotes", "notes"),
            ("cfgDrums", "drums"),
            ("unmaskWidth", "unmask"),
        ):
            if key in scene:
                stdin.write(f"{command_name} {scene[key]}\n")
        if "drumless" in scene:
            stdin.write("drumless on\n" if bool_value(scene["drumless"], False) else "drumless off\n")
        stdin.flush()
        if bool_value(scene.get("resetAfterPrompt"), bool_value(strategy.get("resetAfterPrompt"), False)):
            debounce_seconds = max(0.0, float_value(scene.get("promptDebounceMs"), float_value(strategy.get("promptDebounceMs"), 400.0)) / 1000.0)
            if debounce_seconds > 0:
                time.sleep(debounce_seconds)
            stdin.write("reset\n")
            stdin.flush()
        append_event(manifest, {
            "type": "scene",
            "sceneId": scene.get("id"),
            "promptId": scene.get("promptId"),
            "prompt": prompt,
            "runtimePrompt": runtime_scene_prompt(scene),
            "role": scene.get("role"),
            "mode": scene.get("mode"),
        })
        previous = scene


def stream_child_output(process: subprocess.Popen[str]) -> None:
    stdout = process.stdout
    if stdout is None:
        return
    for line in stdout:
        eprint("mere.run: " + line.rstrip())


def execute_manifest(manifest_path: pathlib.Path, manifest: JsonMap) -> JsonMap:
    local = as_map(manifest["local"], "local")
    artifacts = as_map(manifest["artifacts"], "artifacts")
    output_dir = pathlib.Path(string_field(local, "outputDirectory", "local"))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_stage_assets(manifest)
    append_event(manifest, {"type": "started"})
    update_manifest(manifest_path, manifest, status="running")
    command = [str(part) for part in as_list(manifest["command"], "command")]
    if not command_available(command):
        raise PluginError(f"mere.run command not found: {command[0]}", 3)
    try:
        process = subprocess.Popen(
            command,
            cwd=output_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        reader = threading.Thread(target=stream_child_output, args=(process,), daemon=True)
        reader.start()
        if process.stdin is not None:
            with contextlib.suppress(BrokenPipeError):
                send_scene_commands(process.stdin, manifest)
            with contextlib.suppress(BrokenPipeError):
                process.stdin.close()
        returncode = process.wait()
        reader.join(timeout=1)
        if returncode != 0:
            raise PluginError(f"mere.run music realtime failed with exit {returncode}", 1)
        audio_path = pathlib.Path(string_field(local, "audioCapture", "local"))
        events_path = pathlib.Path(string_field(local, "eventsJsonl", "local"))
        sha: JsonMap = {}
        files: list[str] = []
        for path in (audio_path, events_path, pathlib.Path(string_field(local, "stageHtml", "local")), pathlib.Path(string_field(local, "stageState", "local")), pathlib.Path(string_field(local, "showJson", "local"))):
            if path.is_file():
                files.append(str(path))
                sha[str(path)] = file_sha256(path)
        artifacts["files"] = files
        artifacts["sha256"] = sha
        append_event(manifest, {"type": "finished", "exitCode": returncode})
        update_manifest(manifest_path, manifest, status="succeeded")
        return manifest
    except PluginError:
        update_manifest(manifest_path, manifest, status="failed")
        raise
    except OSError as exc:
        update_manifest(manifest_path, manifest, status="failed", error=str(exc))
        raise PluginError(str(exc), 1) from None


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    mere_run_command = split_command(args.mere_run_command)
    checks: list[JsonMap] = [
        {"name": "mere.run", "ok": command_available(mere_run_command), "detail": shlex.join(mere_run_command)},
        {"name": "stage-ui", "ok": True, "detail": "static HTML exporter available"},
        {"name": "cleanup", "ok": True, "detail": "local runs create no paid remote resources"},
    ]
    if args.live and command_available(mere_run_command):
        result = subprocess.run(
            [*mere_run_command, "music", "realtime", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        checks.append({"name": "music-realtime", "ok": result.returncode == 0, "detail": result.stderr.strip() or "help command succeeded"})
    print_json({"plugin": PLUGIN_NAME, "version": __version__, "checks": checks, "ok": all(bool_value(check.get("ok"), False) for check in checks)})
    return 0


def command_plan(args: argparse.Namespace) -> int:
    manifest = make_manifest(args)
    manifest_path = pathlib.Path(string_field(as_map(manifest["local"], "local"), "runManifest", "local"))
    write_json(manifest_path, manifest)
    print_json(manifest)
    return 0


def command_run(args: argparse.Namespace) -> int:
    manifest_path = args.run_manifest
    manifest = read_json(manifest_path)
    if args.dry_run:
        print_json(manifest)
        return 0
    result = execute_manifest(manifest_path, manifest)
    print_json(result)
    return 0


def command_perform(args: argparse.Namespace) -> int:
    manifest = make_manifest(args)
    manifest_path = pathlib.Path(string_field(as_map(manifest["local"], "local"), "runManifest", "local"))
    write_json(manifest_path, manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    result = execute_manifest(manifest_path, manifest)
    print_json(result)
    return 0


def command_resume(args: argparse.Namespace) -> int:
    manifest = read_json(args.run_manifest)
    print_json({
        "runId": manifest.get("runId"),
        "status": manifest.get("status"),
        "plugin": manifest.get("plugin"),
        "performance": manifest.get("performance"),
        "artifacts": manifest.get("artifacts"),
        "cleanup": manifest.get("cleanup"),
    })
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    manifest = read_json(args.run_manifest)
    cleanup = as_map(manifest.setdefault("cleanup", {"default": "none", "status": "not-started"}), "cleanup")
    cleanup["status"] = "skipped"
    cleanup["reason"] = "mere-perform creates local artifacts only; there are no remote resources to tear down"
    update_manifest(args.run_manifest, manifest)
    print_json(manifest)
    return 0


def command_stage(args: argparse.Namespace) -> int:
    manifest = read_json(args.run_manifest)
    exported = write_stage_assets(manifest)
    if not args.serve:
        print_json({"runId": manifest.get("runId"), **exported})
        return 0
    stage_dir = pathlib.Path(string_field(as_map(manifest["local"], "local"), "stageDirectory", "local"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(stage_dir))
    with socketserver.TCPServer((args.host, args.port), handler) as server:
        host, port = server.server_address
        url = f"http://{host}:{port}/"
        print_json({"runId": manifest.get("runId"), **exported, "url": url})
        sys.stdout.flush()
        eprint(f"serving stage UI at {url}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            eprint("stage server stopped")
    return 0


def command_devices(args: argparse.Namespace) -> int:
    command = [*split_command(args.mere_run_command), "music", "realtime", "--list-midi-inputs"]
    if args.dry_run:
        print_json({"command": command, "devices": [], "dryRun": True})
        return 0
    if not command_available(command):
        raise PluginError(f"mere.run command not found: {command[0]}", 3)
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.stderr.strip():
        eprint(result.stderr.strip())
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    print_json({"command": command, "devices": [{"raw": line} for line in lines], "exitCode": result.returncode})
    return 0 if result.returncode == 0 else 3


def command_show_template(args: argparse.Namespace) -> int:
    payload = template_show()
    if args.output:
        write_json(args.output, payload)
    print_json(payload)
    return 0


def default_mere_run_command() -> str:
    return os.environ.get("MERE_PERFORM_MERE_RUN") or DEFAULT_MERE_RUN


def normalize_common_args(args: argparse.Namespace) -> None:
    if hasattr(args, "run_id"):
        validate_run_id(args.run_id)
    if hasattr(args, "mere_run_command") and not args.mere_run_command:
        args.mere_run_command = default_mere_run_command()
    for name in ("show", "output_dir", "manifest", "run_manifest", "output"):
        if hasattr(args, name):
            value = getattr(args, name)
            if isinstance(value, pathlib.Path):
                setattr(args, name, value.expanduser().resolve())


def add_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--show", type=pathlib.Path, help="Performance show JSON. Defaults to the starter Magenta Heart show.")
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--mere-run-command", default="")
    parser.add_argument("--model", help="Magenta RT2 model id or local root.")
    parser.add_argument("--duration", type=float, help="Override show duration in seconds.")
    parser.add_argument("--capture", help="Override WAV capture path or filename.")
    parser.add_argument("--no-play", action="store_true", help="Capture audio without playing through the default output device.")
    parser.add_argument("--midi-input", help="CoreMIDI input source name or unique ID.")
    parser.add_argument("--midi-channel", help="MIDI channel 1-16 or all.")
    parser.add_argument("--midi-note-offset", type=int, help="Transpose incoming MIDI notes before they reach Magenta RT2.")
    parser.add_argument("--midi-cc", action="append", default=[], help="Repeatable CC mapping cc=target:min:max.")
    parser.add_argument("--stage-host", default="127.0.0.1")
    parser.add_argument("--stage-port", type=int, default=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mere-perform")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check local readiness.")
    doctor.add_argument("--mere-run-command", default="")
    doctor.add_argument("--live", action="store_true", help="Also ask mere.run for music realtime help.")
    doctor.set_defaults(func=command_doctor)

    plan = sub.add_parser("plan", help="Create a performance run manifest.")
    add_plan_args(plan)
    plan.set_defaults(func=command_plan)

    run = sub.add_parser("run", help="Execute a planned performance run manifest.")
    run.add_argument("run_manifest", type=pathlib.Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run)

    perform = sub.add_parser("perform", help="Plan and run a performance in one command.")
    add_plan_args(perform)
    perform.add_argument("--dry-run", action="store_true")
    perform.set_defaults(func=command_perform)

    resume = sub.add_parser("resume", help="Inspect a run manifest.")
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.set_defaults(func=command_resume)

    cleanup = sub.add_parser("cleanup", help="Mark local cleanup as skipped.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=command_cleanup)

    stage = sub.add_parser("stage", help="Export or serve the stage UI.")
    stage.add_argument("run_manifest", type=pathlib.Path)
    stage.add_argument("--serve", action="store_true")
    stage.add_argument("--host", default="127.0.0.1")
    stage.add_argument("--port", type=int, default=8765)
    stage.set_defaults(func=command_stage)

    devices = sub.add_parser("devices", help="List MIDI devices through mere.run.")
    devices.add_argument("--mere-run-command", default="")
    devices.add_argument("--dry-run", action="store_true")
    devices.set_defaults(func=command_devices)

    template = sub.add_parser("show-template", help="Print a starter show JSON.")
    template.add_argument("--output", type=pathlib.Path)
    template.set_defaults(func=command_show_template)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    normalize_common_args(args)
    try:
        return int(args.func(args))
    except PluginError as exc:
        eprint(str(exc))
        return exc.exit_code

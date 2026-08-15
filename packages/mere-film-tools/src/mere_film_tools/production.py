from __future__ import annotations

import hashlib
import html
import json
import pathlib
import re
import shutil
import subprocess
from collections.abc import Callable
from functools import partial

from .common import (
    JsonMap,
    PluginError,
    as_int,
    as_list,
    as_map,
    as_number,
    as_string,
    file_sha256,
    load_json,
    now_iso,
    object_sha256,
    optional_string,
    slug,
    write_json,
    write_text,
)
from .state import (
    ProjectPaths,
    add_artifact,
    clear_issue,
    gate,
    history,
    production_config,
    remove_artifact,
    save,
    set_gate_pending,
    set_issue,
)

NONCOMMERCIAL_IMAGE_MODELS = frozenset({"image-klein-9b", "image-klein-base-9b", "image-ideogram4-sdnq-uint4"})
NONCOMMERCIAL_SFX_MODELS = frozenset(
    {
        "sfx-woosh-dflow",
        "sfx-woosh-flow",
        "sfx-woosh-clap",
        "sfx-woosh-synchformer",
        "sfx-woosh-vflow-8s",
        "sfx-woosh-dvflow-8s",
    }
)
SFX_MINIMUM_PEAK_DBFS = -50.0
AUTO_VISION_INSPECTOR = "auto-qwen3-vl-2b"
AUTO_VISION_INSPECTOR_ID = "mlx-community/Qwen3-VL-2B-Instruct-4bit"


def production_plan(paths: ProjectPaths) -> JsonMap:
    if not paths.production.is_file():
        raise PluginError("production plan is missing; complete and approve preproduction first", 2)
    from .common import load_json

    return load_json(paths.production)


def command_config(project: JsonMap) -> JsonMap:
    return as_map(production_config(project).get("commands"), "project.production.commands")


def media_inspection_enabled(project: JsonMap) -> bool:
    return bool(production_config(project).get("inspectGeneratedMedia", True))


def model_config(project: JsonMap) -> JsonMap:
    return as_map(production_config(project).get("models"), "project.production.models")


def validate_usage_policy(project: JsonMap) -> None:
    brief = as_map(project.get("brief"), "project.brief")
    target = as_map(brief.get("target"), "project.brief.target")
    usage = as_string(target.get("usage"), "project.brief.target.usage")
    image_shot_model = as_string(model_config(project).get("imageShot"), "models.imageShot")
    if usage == "commercial" and image_shot_model in NONCOMMERCIAL_IMAGE_MODELS:
        raise PluginError(
            f"commercial production is blocked for known noncommercial image model {image_shot_model}; "
            "select a model whose current terms cover the project",
            2,
        )
    uses_sound_effects = any(
        bool(as_list(as_map(raw_shot, "project.shot").get("soundEffects", []), "project.shot.soundEffects"))
        for raw_shot in as_list(project.get("shots"), "project.shots")
    )
    sfx_model = as_string(model_config(project).get("sfx"), "models.sfx")
    if usage == "commercial" and uses_sound_effects and sfx_model in NONCOMMERCIAL_SFX_MODELS:
        raise PluginError(
            f"commercial production is blocked for noncommercial SFX model {sfx_model}; "
            "select an SFX model whose current terms cover the project or remove the accepted SFX cues",
            2,
        )


def command_value(project: JsonMap, key: str) -> str:
    return as_string(command_config(project).get(key), f"project.production.commands.{key}")


def output_path(paths: ProjectPaths, job: JsonMap) -> pathlib.Path:
    value = pathlib.Path(as_string(job.get("output"), "job.output"))
    return value if value.is_absolute() else paths.root / value


def jobs(project: JsonMap) -> list[JsonMap]:
    return [as_map(item, "production job") for item in as_list(project.get("jobs"), "project.jobs")]


def job_by_id(project: JsonMap, job_id: str) -> JsonMap | None:
    return next((item for item in jobs(project) if item.get("id") == job_id), None)


def upsert_job(project: JsonMap, payload: JsonMap) -> JsonMap:
    spec = {
        key: payload.get(key)
        for key in (
            "id",
            "kind",
            "subject",
            "speaker",
            "text",
            "startSeconds",
            "dependsOn",
            "output",
            "command",
            "artifactKind",
            "contentType",
            "candidateIndex",
            "selectionProfile",
            "mixProfile",
        )
    }
    spec_sha256 = object_sha256(spec)
    payload["specSha256"] = spec_sha256
    current = job_by_id(project, as_string(payload.get("id"), "job.id"))
    if current:
        status = current.get("status")
        attempts = current.get("attempts")
        prior_spec = current.get("specSha256")
        current.update(payload)
        current["status"] = "planned" if prior_spec != spec_sha256 else status or "planned"
        current["attempts"] = attempts or 0
        if prior_spec != spec_sha256:
            for key in ("sha256", "completedAt", "completedSpecSha256", "error", "failedAt", "reused"):
                current.pop(key, None)
        return current
    payload.setdefault("status", "planned")
    payload.setdefault("attempts", 0)
    as_list(project.setdefault("jobs", []), "project.jobs").append(payload)
    return payload


def cast_items(plan: JsonMap) -> list[JsonMap]:
    return [as_map(item, "cast item") for item in as_list(plan.get("cast"), "productionPlan.cast")]


def location_items(plan: JsonMap) -> list[JsonMap]:
    return [as_map(item, "location item") for item in as_list(plan.get("locations"), "productionPlan.locations")]


def shot_items(plan: JsonMap) -> list[JsonMap]:
    return [as_map(item, "shot") for item in as_list(plan.get("shots"), "productionPlan.shots")]


def cast_output(paths: ProjectPaths, cast_id: str) -> pathlib.Path:
    return paths.canon / "cast" / f"{slug(cast_id, 'character')}.png"


def location_output(paths: ProjectPaths, location_id: str) -> pathlib.Path:
    return paths.canon / "locations" / f"{slug(location_id, 'location')}.png"


def frame_output(paths: ProjectPaths, shot_id: str) -> pathlib.Path:
    return paths.frames / f"{slug(shot_id, 'shot')}.png"


def clip_output(paths: ProjectPaths, shot_id: str) -> pathlib.Path:
    return paths.clips / f"{slug(shot_id, 'shot')}.mp4"


def candidate_clip_output(paths: ProjectPaths, shot_id: str, candidate_index: int) -> pathlib.Path:
    return paths.clips / "candidates" / slug(shot_id, "shot") / f"candidate-{candidate_index:03d}.mp4"


def takes_per_shot(project: JsonMap) -> int:
    value = production_config(project).get("takesPerShot", 1)
    count = as_int(value, "project.production.takesPerShot")
    if not 1 <= count <= 4:
        raise PluginError("project.production.takesPerShot must be between 1 and 4", 2)
    return count


def stable_seed(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % 2_147_483_647


def build_media_jobs(paths: ProjectPaths, project: JsonMap) -> list[JsonMap]:
    plan = production_plan(paths)
    production = production_config(project)
    models = model_config(project)
    mere_run = command_value(project, "mereRun")
    target = as_map(plan.get("target"), "productionPlan.target")
    width = as_int(target.get("width"), "productionPlan.target.width")
    height = as_int(target.get("height"), "productionPlan.target.height")
    fps = as_int(target.get("fps"), "productionPlan.target.fps")
    mode = as_string(production.get("mode"), "project.production.mode")
    image_master_model = as_string(models.get("imageMaster"), "models.imageMaster")
    image_shot_model = as_string(models.get("imageShot"), "models.imageShot")
    video_model = optional_string(models.get("video")) or ""
    speech_tts_model = as_string(models.get("speechTts"), "models.speechTts")
    sfx_model = as_string(models.get("sfx"), "models.sfx")
    music_model = as_string(models.get("music"), "models.music")
    cast_paths: dict[str, pathlib.Path] = {}
    location_paths: dict[str, pathlib.Path] = {}
    created: list[JsonMap] = []
    for person in cast_items(plan):
        cast_id = as_string(person.get("id"), "cast.id")
        output = cast_output(paths, cast_id)
        cast_paths[cast_id] = output
        visual = as_string(person.get("visual"), f"cast {cast_id}.visual")
        wardrobe = str(person.get("wardrobe") or "")
        prompt = f"Production character reference portrait. {visual}. Wardrobe: {wardrobe}. Neutral readable pose, cinematic realism, no text."
        command = [
            mere_run,
            "image",
            "generate",
            "--model",
            image_master_model,
            "--prompt",
            prompt,
            "--width",
            "1024",
            "--height",
            "1024",
            "--seed",
            str(person.get("seed") if isinstance(person.get("seed"), int) else stable_seed(f"cast:{cast_id}")),
            "--output",
            str(output),
        ]
        created.append(
            upsert_job(
                project,
                {
                    "id": f"cast-{slug(cast_id)}",
                    "kind": "cast-master",
                    "subject": cast_id,
                    "dependsOn": [],
                    "output": str(output.relative_to(paths.root)),
                    "command": command,
                    "artifactKind": "cast-master",
                    "contentType": "image/png",
                },
            )
        )
    for location in location_items(plan):
        location_id = as_string(location.get("id"), "location.id")
        output = location_output(paths, location_id)
        location_paths[location_id] = output
        visual = as_string(location.get("visual"), f"location {location_id}.visual")
        ambience = str(location.get("ambience") or "")
        prompt = (
            f"Production location reference plate with no people. {visual}. "
            f"Sonic atmosphere translated into visual detail: {ambience}. Wide readable geography, cinematic realism, no text."
        )
        command = [
            mere_run,
            "image",
            "generate",
            "--model",
            image_master_model,
            "--prompt",
            prompt,
            "--width",
            str(width),
            "--height",
            str(height),
            "--seed",
            str(location.get("seed") if isinstance(location.get("seed"), int) else stable_seed(f"location:{location_id}")),
            "--output",
            str(output),
        ]
        created.append(
            upsert_job(
                project,
                {
                    "id": f"location-{slug(location_id)}",
                    "kind": "location-master",
                    "subject": location_id,
                    "dependsOn": [],
                    "output": str(output.relative_to(paths.root)),
                    "command": command,
                    "artifactKind": "location-master",
                    "contentType": "image/png",
                },
            )
        )
    selected_clip_ids: list[str] = []
    dialogue_ids: list[str] = []
    sound_effect_ids: list[str] = []
    candidate_count = takes_per_shot(project)
    cast_by_id = {as_string(item.get("id"), "cast.id"): item for item in cast_items(plan)}
    language = as_string(target.get("language"), "productionPlan.target.language")
    for shot in shot_items(plan):
        shot_id = as_string(shot.get("id"), "shot.id")
        character_ids = [str(value) for value in as_list(shot.get("characters"), f"shot {shot_id}.characters")]
        cast_dependencies = [f"cast-{slug(value)}" for value in character_ids if value in cast_paths]
        location_id = as_string(shot.get("location"), f"shot {shot_id}.location")
        location_reference = location_paths.get(location_id)
        dependencies = [*cast_dependencies]
        if location_reference:
            dependencies.append(f"location-{slug(location_id)}")
        frame = frame_output(paths, shot_id)
        frame_command = [
            mere_run,
            "image",
            "generate",
            "--model",
            image_shot_model,
            "--prompt",
            as_string(shot.get("framePrompt"), f"shot {shot_id}.framePrompt"),
            "--width",
            str(width),
            "--height",
            str(height),
            "--seed",
            str(shot.get("seed")),
            "--output",
            str(frame),
        ]
        for character_id in character_ids:
            reference = cast_paths.get(character_id)
            if reference:
                frame_command.extend(["--ref-image", str(reference)])
        if location_reference:
            frame_command.extend(["--ref-image", str(location_reference)])
        frame_job_id = f"frame-{slug(shot_id)}"
        created.append(
            upsert_job(
                project,
                {
                    "id": frame_job_id,
                    "kind": "keyframe",
                    "subject": shot_id,
                    "dependsOn": dependencies,
                    "output": str(frame.relative_to(paths.root)),
                    "command": frame_command,
                    "artifactKind": "shot-keyframe",
                    "contentType": "image/png",
                },
            )
        )
        for line_index, raw_line in enumerate(as_list(shot.get("dialogue"), f"shot {shot_id}.dialogue"), start=1):
            line = as_map(raw_line, f"shot {shot_id}.dialogue[{line_index}]")
            speaker = as_string(line.get("speaker"), f"shot {shot_id} dialogue {line_index}.speaker")
            person = as_map(cast_by_id.get(speaker), f"dialogue speaker {speaker}")
            voice = as_string(person.get("voice"), f"cast {speaker}.voice")
            delivery = as_string(line.get("delivery"), f"shot {shot_id} dialogue {line_index}.delivery")
            dialogue_output = paths.audio / "dialogue" / f"{slug(shot_id)}-{line_index:02d}.wav"
            dialogue_id = f"dialogue-{slug(shot_id)}-{line_index:02d}"
            dialogue_ids.append(dialogue_id)
            created.append(
                upsert_job(
                    project,
                    {
                        "id": dialogue_id,
                        "kind": "dialogue",
                        "subject": shot_id,
                        "speaker": speaker,
                        "text": as_string(line.get("text"), f"shot {shot_id} dialogue {line_index}.text"),
                        "startSeconds": as_number(
                            line.get("startSeconds"), f"shot {shot_id} dialogue {line_index}.startSeconds"
                        ),
                        "dependsOn": [],
                        "output": str(dialogue_output.relative_to(paths.root)),
                        "command": [
                            mere_run,
                            "speech",
                            "synthesize",
                            as_string(line.get("text"), f"shot {shot_id} dialogue {line_index}.text"),
                            "--model",
                            speech_tts_model,
                            "--voice",
                            f"{voice}. Performance direction: {delivery}",
                            "--language",
                            language,
                            "--output",
                            str(dialogue_output),
                        ],
                        "artifactKind": "dialogue-line",
                        "contentType": "audio/wav",
                    },
                )
            )
        for cue_index, raw_cue in enumerate(
            as_list(shot.get("soundEffects", []), f"shot {shot_id}.soundEffects"),
            start=1,
        ):
            cue = as_map(raw_cue, f"shot {shot_id}.soundEffects[{cue_index}]")
            effect_output = paths.audio / "sfx" / f"{slug(shot_id)}-{cue_index:02d}.wav"
            effect_id = f"sfx-{slug(shot_id)}-{cue_index:02d}"
            sound_effect_ids.append(effect_id)
            created.append(
                upsert_job(
                    project,
                    {
                        "id": effect_id,
                        "kind": "sound-effect",
                        "subject": shot_id,
                        "text": as_string(cue.get("prompt"), f"shot {shot_id} sound effect {cue_index}.prompt"),
                        "startSeconds": as_number(
                            cue.get("startSeconds"),
                            f"shot {shot_id} sound effect {cue_index}.startSeconds",
                        ),
                        "levelDb": as_number(cue.get("levelDb", -10), f"shot {shot_id} sound effect {cue_index}.levelDb"),
                        "dependsOn": [],
                        "output": str(effect_output.relative_to(paths.root)),
                        "command": [
                            mere_run,
                            "sfx",
                            "generate",
                            as_string(cue.get("prompt"), f"shot {shot_id} sound effect {cue_index}.prompt"),
                            "--model",
                            sfx_model,
                            "--duration",
                            str(cue.get("durationSeconds")),
                            "--seed",
                            str(cue.get("seed")),
                            "--output",
                            str(effect_output),
                        ],
                        "artifactKind": "sound-effect",
                        "contentType": "audio/wav",
                    },
                )
            )
        base_seed = as_int(shot.get("seed"), f"shot {shot_id}.seed")
        candidate_job_ids: list[str] = []
        for candidate_index in range(1, candidate_count + 1):
            multi_take = candidate_count > 1
            clip = (
                candidate_clip_output(paths, shot_id, candidate_index)
                if multi_take
                else clip_output(paths, shot_id)
            )
            clip_command = [
                mere_run,
                "video",
                "generate",
                as_string(shot.get("prompt"), f"shot {shot_id}.prompt"),
                "--image",
                str(frame),
                "--image-strength",
                "1.0",
                "--width",
                str(width),
                "--height",
                str(height),
                "--duration",
                str(shot.get("durationSeconds")),
                "--fps",
                str(fps),
                "--seed",
                str(base_seed + candidate_index - 1),
                "--quality",
                "draft" if mode == "draft" else "final",
                "--output-mode",
                "video-only" if mode == "draft" else "audio-video",
                "--output",
                str(clip),
            ]
            if video_model:
                clip_command.extend(["--model", video_model])
            clip_job_id = (
                f"clip-{slug(shot_id)}-candidate-{candidate_index:03d}"
                if multi_take
                else f"clip-{slug(shot_id)}"
            )
            candidate_job_ids.append(clip_job_id)
            created.append(
                upsert_job(
                    project,
                    {
                        "id": clip_job_id,
                        "kind": "clip-candidate" if multi_take else "clip",
                        "subject": shot_id,
                        "candidateIndex": candidate_index,
                        "dependsOn": [frame_job_id],
                        "output": str(clip.relative_to(paths.root)),
                        "command": clip_command,
                        "artifactKind": "shot-clip-candidate" if multi_take else "shot-clip",
                        "contentType": "video/mp4",
                    },
                )
            )
        if candidate_count > 1:
            selection_job_id = f"select-{slug(shot_id)}"
            selected_clip_ids.append(selection_job_id)
            created.append(
                upsert_job(
                    project,
                    {
                        "id": selection_job_id,
                        "kind": "take-selection",
                        "subject": shot_id,
                        "dependsOn": candidate_job_ids,
                        "output": str(clip_output(paths, shot_id).relative_to(paths.root)),
                        "command": [mere_run, "vision", "inspect", "<candidate-contact-sheets>"],
                        "artifactKind": "shot-clip",
                        "contentType": "video/mp4",
                        "selectionProfile": "canon-aware-contact-sheet-v1",
                    },
                )
            )
        else:
            selected_clip_ids.extend(candidate_job_ids)
    if bool(production.get("generateScore")):
        score = paths.audio / "score.wav"
        duration_value = plan.get("plannedDurationSeconds") or target.get("durationSeconds")
        duration = as_number(duration_value, "productionPlan.plannedDurationSeconds")
        score_command = [
            mere_run,
            "music",
            "generate",
            as_string(plan.get("scorePrompt"), "productionPlan.scorePrompt"),
            "--model",
            music_model,
            "--instrumental",
            "--duration",
            str(round(duration, 3)),
            "--quality",
            "draft" if mode == "draft" else "song",
            "--seed",
            str(stable_seed(f"score:{project.get('projectId')}")),
            "--output",
            str(score),
        ]
        created.append(
            upsert_job(
                project,
                {
                    "id": "score",
                    "kind": "score",
                    "subject": "film",
                    "dependsOn": [],
                    "output": str(score.relative_to(paths.root)),
                    "command": score_command,
                    "artifactKind": "score",
                    "contentType": "audio/wav",
                },
            )
        )
    assembly_dependencies = [*selected_clip_ids, *dialogue_ids, *sound_effect_ids]
    if bool(production.get("generateScore")):
        assembly_dependencies.append("score")
    created.append(
        upsert_job(
            project,
            {
                "id": "assemble-rough-cut",
                "kind": "assembly",
                "subject": "rough-cut",
                "dependsOn": assembly_dependencies,
                "output": str((paths.cuts / "rough-cut.mp4").relative_to(paths.root)),
                "command": [command_value(project, "ffmpeg"), "<normalized-concat>"],
                "artifactKind": "rough-cut",
                "contentType": "video/mp4",
                "mixProfile": "dialogue-sidechain-loudnorm-16-v1",
            },
        )
    )
    current_job_ids = {as_string(item.get("id"), "job.id") for item in created}
    managed_kinds = {
        "cast-master",
        "location-master",
        "keyframe",
        "dialogue",
        "sound-effect",
        "clip",
        "clip-candidate",
        "take-selection",
        "score",
        "assembly",
    }
    project_jobs = as_list(project.get("jobs"), "project.jobs")
    project_jobs[:] = [
        item
        for item in project_jobs
        if not isinstance(item, dict)
        or item.get("kind") not in managed_kinds
        or item.get("id") in current_job_ids
    ]
    return created


def command_plan_payload(paths: ProjectPaths, project: JsonMap) -> JsonMap:
    planned = build_media_jobs(paths, project)
    return {
        "contractVersion": "mere.run/film-command-plan.v1",
        "projectId": project.get("projectId"),
        "createdAt": now_iso(),
        "productionMode": production_config(project).get("mode"),
        "takesPerShot": takes_per_shot(project),
        "jobs": [
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "dependsOn": item.get("dependsOn"),
                "output": item.get("output"),
                "command": item.get("command"),
            }
            for item in planned
        ],
        "resourcePolicy": {
            "creativeAgentConcurrency": production_config(project).get("maxParallelAgents"),
            "mediaConcurrency": 1,
            "videoCandidatesPerShot": takes_per_shot(project),
            "reason": "Local image, video, and music generation are serialized through mere.run machine admission.",
        },
    }


def write_command_plan(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> pathlib.Path:
    path = paths.root / "production-commands.json"
    write_json(path, command_plan_payload(paths, project))
    add_artifact(paths, project, run, path, "production-command-plan", "application/json")
    return path


def preflight_command(command: list[str]) -> list[str] | None:
    command_kind = command[1:3]
    if len(command) < 3 or (command_kind != ["image", "generate"] and command_kind != ["video", "generate"]):
        return None
    return [*command, "--preflight", "--json"]


def required_model_roles(paths: ProjectPaths, project: JsonMap) -> list[tuple[str, str]]:
    plan = production_plan(paths)
    shots = shot_items(plan)
    models = model_config(project)
    uses_dialogue = any(bool(as_list(shot.get("dialogue"), "shot.dialogue")) for shot in shots)
    uses_sound_effects = any(bool(as_list(shot.get("soundEffects", []), "shot.soundEffects")) for shot in shots)
    required = [
        ("imageMaster", as_string(models.get("imageMaster"), "models.imageMaster")),
        ("imageShot", as_string(models.get("imageShot"), "models.imageShot")),
        ("video", as_string(models.get("video"), "models.video")),
    ]
    if media_inspection_enabled(project) or takes_per_shot(project) > 1:
        required.append(("visionInspector", as_string(models.get("visionInspector"), "models.visionInspector")))
    if uses_dialogue:
        required.extend(
            [
                ("speechTts", as_string(models.get("speechTts"), "models.speechTts")),
                ("speechAsr", as_string(models.get("speechAsr"), "models.speechAsr")),
            ]
        )
    if uses_sound_effects:
        required.append(("sfx", as_string(models.get("sfx"), "models.sfx")))
    if bool(production_config(project).get("generateScore")):
        required.append(("music", as_string(models.get("music"), "models.music")))
    return required


def verify_production_models(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    timeout_seconds: int,
) -> pathlib.Path:
    mere_run = command_value(project, "mereRun")
    required = required_model_roles(paths, project)
    cached: dict[str, JsonMap] = {}
    results: list[JsonMap] = []
    failures: list[str] = []
    for role, model in required:
        cache_key = f"{role}:{model}" if role == "visionInspector" else model
        result = cached.get(cache_key)
        if result is None:
            if role == "visionInspector" and model == AUTO_VISION_INSPECTOR:
                result = {
                    "status": "runtime-managed",
                    "configuredModel": model,
                    "resolvedId": AUTO_VISION_INSPECTOR_ID,
                    "runtime": "mere.run vision inspect",
                }
            elif role == "visionInspector":
                local = pathlib.Path(model).expanduser()
                required_paths = [local / "tokenizer", local / "text_encoder" / "config.json"]
                if local.is_dir() and all(path.exists() for path in required_paths):
                    result = {
                        "status": "ready",
                        "configuredModel": model,
                        "resolvedId": str(local.resolve()),
                        "manifestSha256": object_sha256(
                            {"root": str(local.resolve()), "requiredPaths": [str(path) for path in required_paths]}
                        ),
                    }
                else:
                    result = {
                        "status": "blocked",
                        "configuredModel": model,
                        "error": "vision inspector must be auto-qwen3-vl-2b or a compatible local Qwen model root",
                    }
            else:
                try:
                    process = run_child(
                        [mere_run, "model", "info", model, "--json"],
                        paths.root,
                        paths.logs / "media" / f"model-readiness-{slug(role)}.log",
                        timeout_seconds,
                    )
                    payload = json.loads(process.stdout)
                    if not isinstance(payload, dict):
                        raise PluginError(f"model info for {model} returned a non-object manifest")
                    result = {
                        "status": "ready",
                        "configuredModel": model,
                        "resolvedId": payload.get("id") or model,
                        "manifestSha256": object_sha256(payload),
                    }
                except (json.JSONDecodeError, PluginError) as exc:
                    result = {
                        "status": "blocked",
                        "configuredModel": model,
                        "error": str(exc),
                    }
            cached[cache_key] = result
        entry = {"role": role, **result}
        results.append(entry)
        if result.get("status") == "blocked":
            failures.append(f"{role} ({model})")
    receipt: JsonMap = {
        "contractVersion": "mere.run/film-production-readiness.v1",
        "projectId": project.get("projectId"),
        "checkedAt": now_iso(),
        "status": "blocked" if failures else "ready",
        "complete": not failures,
        "productionPlanSha256": file_sha256(paths.production),
        "configurationSha256": object_sha256({role: model for role, model in required}),
        "models": results,
    }
    receipt_path = paths.root / "production-readiness.json"
    write_json(receipt_path, receipt)
    add_artifact(
        paths,
        project,
        run,
        receipt_path,
        "production-readiness",
        "application/json",
        source="mere.run-model-info",
    )
    if failures:
        message = f"production model readiness failed: {', '.join(failures)}"
        set_issue(project, "model-readiness", message, True)
        project["status"] = "revision-required"
        save(paths, project, run)
        raise PluginError(message, 2)
    clear_issue(project, "model-readiness")
    save(paths, project, run)
    return receipt_path


def matching_artifact(paths: ProjectPaths, project: JsonMap, path: pathlib.Path, kind: str) -> bool:
    relative = str(path.resolve().relative_to(paths.root))
    for raw in as_list(project.get("artifacts"), "project.artifacts"):
        if not isinstance(raw, dict) or raw.get("path") != relative or raw.get("kind") != kind:
            continue
        expected = raw.get("sha256")
        return isinstance(expected, str) and path.is_file() and expected == file_sha256(path)
    return False


def archive_unverified_output(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    path: pathlib.Path,
    job_id: str,
) -> pathlib.Path:
    recovery = paths.root / "recovery" / f"{slug(job_id)}-{now_iso().replace(':', '-')}" / path.name
    recovery.parent.mkdir(parents=True, exist_ok=True)
    remove_artifact(paths, project, run, path)
    shutil.move(str(path), recovery)
    add_artifact(
        paths,
        project,
        run,
        recovery,
        "unverified-media",
        "application/octet-stream",
        source="resume-recovery",
    )
    history(project, "unverified-output-archived", f"Moved unverified output for {job_id} to recovery.")
    return recovery


def dependencies_succeeded(project: JsonMap, job: JsonMap) -> bool:
    dependencies = [str(value) for value in as_list(job.get("dependsOn"), "job.dependsOn")]
    return all((job_by_id(project, value) or {}).get("status") == "succeeded" for value in dependencies)


def run_child(command: list[str], cwd: pathlib.Path, log_path: pathlib.Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        raise PluginError(f"required executable not found: {command[0]}", 3) from None
    except subprocess.TimeoutExpired:
        raise PluginError(f"command timed out after {timeout_seconds} seconds: {command[0]}") from None
    write_text(
        log_path,
        f"command: {command[0]} {command[1] if len(command) > 1 else ''} ...\n"
        f"exit: {process.returncode}\n\nstdout:\n{process.stdout}\n\nstderr:\n{process.stderr}",
    )
    if process.returncode != 0:
        diagnostic = process.stderr.strip() or process.stdout.strip() or f"exit {process.returncode}"
        raise PluginError(f"{command[0]} failed: {diagnostic}")
    return process


def execute_media_job(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    job: JsonMap,
    timeout_seconds: int,
) -> None:
    output = output_path(paths, job)
    artifact_kind = as_string(job.get("artifactKind"), "job.artifactKind")
    expected_hash = job.get("sha256")
    can_reuse = (
        job.get("status") == "succeeded"
        and job.get("completedSpecSha256") == job.get("specSha256")
        and isinstance(expected_hash, str)
        and output.is_file()
        and output.stat().st_size > 0
        and file_sha256(output) == expected_hash
        and matching_artifact(paths, project, output, artifact_kind)
    )
    if can_reuse:
        job["status"] = "succeeded"
        job["reused"] = True
        add_artifact(
            paths,
            project,
            run,
            output,
            artifact_kind,
            as_string(job.get("contentType"), "job.contentType"),
            source="existing-media",
        )
        save(paths, project, run)
        return
    if output.is_file():
        archive_unverified_output(
            paths,
            project,
            run,
            output,
            as_string(job.get("id"), "job.id"),
        )
    if not dependencies_succeeded(project, job):
        raise PluginError(f"job {job.get('id')} has incomplete dependencies")
    command = [str(value) for value in as_list(job.get("command"), "job.command")]
    output.parent.mkdir(parents=True, exist_ok=True)
    job["status"] = "running"
    job["startedAt"] = now_iso()
    job["attempts"] = as_int(job.get("attempts", 0), "job.attempts") + 1
    save(paths, project, run)
    log_name = slug(as_string(job.get("id"), "job.id"))
    preflight = preflight_command(command)
    try:
        if preflight:
            result = run_child(preflight, paths.root, paths.logs / "media" / f"{log_name}-preflight.log", timeout_seconds)
            report_path = paths.logs / "media" / f"{log_name}-preflight.json"
            report_text = result.stdout.strip()
            try:
                report = json.loads(report_text)
            except json.JSONDecodeError:
                report = {"raw": report_text}
            write_json(report_path, report)
            job["preflight"] = str(report_path.relative_to(paths.root))
            if not isinstance(report, dict):
                raise PluginError(f"job {job.get('id')} preflight returned a non-object report")
            status = report.get("status")
            if (isinstance(status, str) and status != "ok") or report.get("ok") is False:
                raise PluginError(f"job {job.get('id')} preflight did not pass: {status or report.get('ok')}")
            job["preflightStatus"] = status or "ok"
        run_child(command, paths.root, paths.logs / "media" / f"{log_name}.log", timeout_seconds)
        if not output.is_file() or output.stat().st_size == 0:
            raise PluginError(f"job {job.get('id')} completed without output {output}")
        job["status"] = "succeeded"
        job["completedAt"] = now_iso()
        job["sha256"] = file_sha256(output)
        job["completedSpecSha256"] = job.get("specSha256")
        add_artifact(
            paths,
            project,
            run,
            output,
            artifact_kind,
            as_string(job.get("contentType"), "job.contentType"),
            source="mere.run",
        )
        save(paths, project, run)
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        job["failedAt"] = now_iso()
        project["status"] = "failed"
        set_issue(project, "media-job-failed", f"{job.get('id')} failed: {exc}", True)
        save(paths, project, run)
        raise


def probe_media(path: pathlib.Path, ffprobe_command: str) -> JsonMap:
    process = run_child(
        [
            ffprobe_command,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        path.parent,
        path.parent / f".{path.name}.ffprobe.log",
        120,
    )
    try:
        return as_map(json.loads(process.stdout), f"ffprobe output for {path}")
    except json.JSONDecodeError as exc:
        raise PluginError(f"ffprobe returned invalid JSON for {path}: {exc}") from None


def media_has_audio(report: JsonMap) -> bool:
    return any(
        isinstance(item, dict) and item.get("codec_type") == "audio"
        for item in as_list(report.get("streams"), "ffprobe.streams")
    )


def analyze_media_signal(path: pathlib.Path, project: JsonMap) -> JsonMap:
    ffmpeg = command_value(project, "ffmpeg")
    try:
        process = run_child(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-filter_complex",
                "[0:v]blackdetect=d=0.5:pix_th=0.98,freezedetect=n=-60dB:d=1.5[v];"
                "[0:a]silencedetect=n=-50dB:d=2.0[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-f",
                "null",
                "-",
            ],
            path.parent,
            path.parent / f".{path.name}.signal-analysis.log",
            600,
        )
    except PluginError as exc:
        return {
            "contractVersion": "mere.run/film-signal-analysis.v1",
            "available": False,
            "advisory": True,
            "error": str(exc),
        }
    diagnostic = process.stderr
    black = re.findall(r"black_start:([0-9.]+)", diagnostic)
    freeze = re.findall(r"freeze_start:([0-9.]+)", diagnostic)
    silence = re.findall(r"silence_start: ?([0-9.]+)", diagnostic)
    return {
        "contractVersion": "mere.run/film-signal-analysis.v1",
        "available": True,
        "blackSegments": len(black),
        "freezeSegments": len(freeze),
        "silenceSegments": len(silence),
        "events": {
            "blackStarts": [float(value) for value in black],
            "freezeStarts": [float(value) for value in freeze],
            "silenceStarts": [float(value) for value in silence],
        },
        "advisory": True,
    }


def dialogue_jobs_for_shot(project: JsonMap, shot_id: str) -> list[JsonMap]:
    selected = [item for item in jobs(project) if item.get("kind") == "dialogue" and item.get("subject") == shot_id]
    selected.sort(key=lambda item: as_string(item.get("id"), "dialogue job.id"))
    return selected


def sound_effect_jobs_for_shot(project: JsonMap, shot_id: str) -> list[JsonMap]:
    selected = [
        item
        for item in jobs(project)
        if item.get("kind") == "sound-effect" and item.get("subject") == shot_id
    ]
    selected.sort(key=lambda item: as_string(item.get("id"), "sound effect job.id"))
    return selected


def normalize_clip(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    shot_id: str,
    clip: pathlib.Path,
    width: int,
    height: int,
    fps: int,
    duration_seconds: float,
    transition: str,
) -> pathlib.Path:
    ffmpeg = command_value(project, "ffmpeg")
    ffprobe = command_value(project, "ffprobe")
    block = paths.blocks / f"{slug(shot_id)}.mp4"
    receipt_path = paths.blocks / f"{slug(shot_id)}.json"
    dialogue = dialogue_jobs_for_shot(project, shot_id)
    sound_effects = sound_effect_jobs_for_shot(project, shot_id)
    dialogue_sources: list[JsonMap] = []
    for line in dialogue:
        audio = output_path(paths, line)
        if line.get("status") != "succeeded" or not audio.is_file() or audio.stat().st_size == 0:
            raise PluginError(f"cannot mix shot {shot_id}: dialogue job {line.get('id')} is incomplete")
        dialogue_sources.append(
            {
                "jobId": line.get("id"),
                "sha256": file_sha256(audio),
                "startSeconds": line.get("startSeconds"),
                "speaker": line.get("speaker"),
            }
        )
    sound_sources: list[JsonMap] = []
    for effect in sound_effects:
        audio = output_path(paths, effect)
        if effect.get("status") != "succeeded" or not audio.is_file() or audio.stat().st_size == 0:
            raise PluginError(f"cannot mix shot {shot_id}: sound effect job {effect.get('id')} is incomplete")
        sound_sources.append(
            {
                "jobId": effect.get("id"),
                "sha256": file_sha256(audio),
                "startSeconds": effect.get("startSeconds"),
                "levelDb": effect.get("levelDb"),
                "prompt": effect.get("text"),
            }
        )
    block_digest = object_sha256(
        {
            "mixProfile": "dialogue-sfx-duck-delay-v2",
            "clipSha256": file_sha256(clip),
            "dialogue": dialogue_sources,
            "soundEffects": sound_sources,
            "width": width,
            "height": height,
            "fps": fps,
            "durationSeconds": duration_seconds,
            "transition": transition,
        }
    )
    if (
        block.is_file()
        and block.stat().st_size > 0
        and receipt_path.is_file()
        and matching_artifact(paths, project, block, "edit-block")
        and matching_artifact(paths, project, receipt_path, "edit-block-receipt")
        and load_json(receipt_path).get("sourceDigest") == block_digest
    ):
        return block
    if block.is_file():
        archive_unverified_output(paths, project, run, block, f"block-{shot_id}")
    if receipt_path.is_file():
        archive_unverified_output(paths, project, run, receipt_path, f"block-receipt-{shot_id}")
    report = probe_media(clip, ffprobe)
    command = [ffmpeg, "-y", "-loglevel", "error", "-i", str(clip)]
    source_has_audio = media_has_audio(report)
    if not source_has_audio:
        command.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
    first_dialogue_input = 1 if source_has_audio else 2
    for line in dialogue:
        command.extend(["-i", str(output_path(paths, line))])
    first_effect_input = first_dialogue_input + len(dialogue)
    for effect in sound_effects:
        command.extend(["-i", str(output_path(paths, effect))])
    video_chain = f"scale={width}:{height}:flags=lanczos,setsar=1,fps={fps},format=yuv420p"
    fade_duration = min(0.35, duration_seconds / 2)
    fade_start = max(0.0, duration_seconds - fade_duration)
    if transition == "fade":
        video_chain += f",fade=t=out:st={fade_start:.3f}:d={fade_duration:.3f}"
    video_filter = f"[0:v]{video_chain}[v]"
    base_audio_input = 0 if source_has_audio else 1
    base_volume = "0.58" if dialogue else ("0.78" if sound_effects else "1.0")
    audio_filters = [
        f"[{base_audio_input}:a]aresample=48000,aformat=channel_layouts=stereo,volume={base_volume}[base]"
    ]
    mix_labels: list[str] = []
    for index, line in enumerate(dialogue):
        label = f"d{index}"
        delay_ms = round(as_number(line.get("startSeconds"), "dialogue.startSeconds") * 1000)
        input_index = first_dialogue_input + index
        audio_filters.append(
            f"[{input_index}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms},volume=1.12[{label}]"
        )
        mix_labels.append(f"[{label}]")
    for index, effect in enumerate(sound_effects):
        label = f"s{index}"
        delay_ms = round(as_number(effect.get("startSeconds"), "sound effect.startSeconds") * 1000)
        level_db = as_number(effect.get("levelDb"), "sound effect.levelDb")
        input_index = first_effect_input + index
        audio_filters.append(
            f"[{input_index}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms},volume={level_db:.2f}dB[{label}]"
        )
        mix_labels.append(f"[{label}]")
    if mix_labels:
        audio_filters.append(
            f"[base]{''.join(mix_labels)}amix=inputs={len(mix_labels) + 1}:duration=first:normalize=0[a]"
        )
    else:
        audio_filters.append("[base]anull[a]")
    audio_label = "[a]"
    if transition == "fade":
        audio_filters.append(f"[a]afade=t=out:st={fade_start:.3f}:d={fade_duration:.3f}[afinal]")
        audio_label = "[afinal]"
    command.extend(["-filter_complex", ";".join([video_filter, *audio_filters]), "-map", "[v]", "-map", audio_label])
    if not source_has_audio:
        command.append("-shortest")
    command.extend(
        [
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(block),
        ]
    )
    run_child(command, paths.root, paths.logs / "media" / f"block-{slug(shot_id)}.log", 3600)
    if not block.is_file() or block.stat().st_size == 0:
        raise PluginError(f"normalization did not produce {block}")
    add_artifact(paths, project, run, block, "edit-block", "video/mp4", source="ffmpeg")
    write_json(
        receipt_path,
        {
            "contractVersion": "mere.run/film-edit-block.v1",
            "shotId": shot_id,
            "createdAt": now_iso(),
            "sourceDigest": block_digest,
            "clipSha256": file_sha256(clip),
            "dialogue": dialogue_sources,
            "soundEffects": sound_sources,
            "transition": transition,
            "outputSha256": file_sha256(block),
        },
    )
    add_artifact(paths, project, run, receipt_path, "edit-block-receipt", "application/json", source="ffmpeg")
    return block


def assemble_rough_cut(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> pathlib.Path:
    plan = production_plan(paths)
    target = as_map(plan.get("target"), "productionPlan.target")
    width = as_int(target.get("width"), "productionPlan.target.width")
    height = as_int(target.get("height"), "productionPlan.target.height")
    fps = as_int(target.get("fps"), "productionPlan.target.fps")
    blocks: list[pathlib.Path] = []
    for shot in shot_items(plan):
        shot_id = as_string(shot.get("id"), "shot.id")
        clip = clip_output(paths, shot_id)
        if not clip.is_file():
            raise PluginError(f"cannot assemble: missing clip {shot_id}")
        blocks.append(
            normalize_clip(
                paths=paths,
                project=project,
                run=run,
                shot_id=shot_id,
                clip=clip,
                width=width,
                height=height,
                fps=fps,
                duration_seconds=as_number(shot.get("durationSeconds"), f"shot {shot_id}.durationSeconds"),
                transition=as_string(shot.get("transition"), f"shot {shot_id}.transition"),
            )
        )
    if not blocks:
        raise PluginError("cannot assemble a film with no clips")
    output = paths.cuts / "rough-cut.mp4"
    if output.is_file():
        archive_unverified_output(paths, project, run, output, "assemble-rough-cut")
    ffmpeg = command_value(project, "ffmpeg")
    command = [ffmpeg, "-y", "-loglevel", "error"]
    for block in blocks:
        command.extend(["-i", str(block)])
    score = paths.audio / "score.wav"
    has_score = score.is_file() and score.stat().st_size > 0
    if has_score:
        command.extend(["-stream_loop", "-1", "-i", str(score)])
    chain = "".join(f"[{index}:v][{index}:a]" for index in range(len(blocks)))
    filters = f"{chain}concat=n={len(blocks)}:v=1:a=1[mv][ma]"
    if has_score:
        filters += (
            f";[{len(blocks)}:a]volume=0.22,aresample=48000,aformat=channel_layouts=stereo[score]"
            ";[score][ma]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=350[ducked]"
            ";[ma][ducked]amix=inputs=2:duration=first:normalize=0[premaster]"
            ";[premaster]loudnorm=I=-16:LRA=11:TP=-1.5,aresample=48000[a]"
        )
        audio_label = "[a]"
    else:
        filters += ";[ma]loudnorm=I=-16:LRA=11:TP=-1.5,aresample=48000[a]"
        audio_label = "[a]"
    filters += ";[mv]fade=t=in:st=0:d=0.35[v]"
    command.extend(
        [
            "-filter_complex",
            filters,
            "-map",
            "[v]",
            "-map",
            audio_label,
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    assembly_job = job_by_id(project, "assemble-rough-cut")
    if assembly_job:
        assembly_job["command"] = command
        assembly_job["status"] = "running"
        assembly_job["startedAt"] = now_iso()
        assembly_job["attempts"] = as_int(assembly_job.get("attempts", 0), "assembly job.attempts") + 1
        save(paths, project, run)
    try:
        run_child(command, paths.root, paths.logs / "media" / "assemble-rough-cut.log", 3600)
        if not output.is_file() or output.stat().st_size == 0:
            raise PluginError("assembly command did not produce a playable file")
        if assembly_job:
            assembly_job["status"] = "succeeded"
            assembly_job["completedAt"] = now_iso()
            assembly_job["sha256"] = file_sha256(output)
            assembly_job["completedSpecSha256"] = assembly_job.get("specSha256")
        add_artifact(paths, project, run, output, "rough-cut", "video/mp4", source="ffmpeg")
        proof = as_map(project.get("proof"), "project.proof")
        proof["clips"] = True
        proof["assembly"] = True
        project["phase"] = "postproduction"
        project["status"] = "planned"
        clear_issue(project, "media-job-failed")
        clear_issue(project, "production-mode-plan")
        history(project, "rough-cut-assembled", f"Assembled {len(blocks)} normalized clips into a rough cut.")
        save(paths, project, run)
        return output
    except Exception as exc:
        if assembly_job:
            assembly_job["status"] = "failed"
            assembly_job["error"] = str(exc)
        project["status"] = "failed"
        set_issue(project, "assembly-failed", str(exc), True)
        save(paths, project, run)
        raise


def execute_production(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    timeout_seconds: int,
) -> JsonMap:
    if gate(project, "production").get("status") != "approved":
        raise PluginError("production gate is not approved", 2)
    try:
        validate_usage_policy(project)
    except PluginError as exc:
        set_issue(project, "license-policy", str(exc), True)
        project["status"] = "revision-required"
        save(paths, project, run)
        raise
    clear_issue(project, "license-policy")
    command_plan = write_command_plan(paths, project, run)
    mode = as_string(production_config(project).get("mode"), "project.production.mode")
    if mode == "plan":
        project["phase"] = "production"
        project["status"] = "awaiting-approval"
        set_issue(
            project,
            "production-mode-plan",
            "Production is still plan-only. Configure draft or final after reviewing compute impact.",
            True,
        )
        save(paths, project, run)
        return {
            "executed": False,
            "reason": "production-mode-plan",
            "commandPlan": str(command_plan),
            "jobs": len(jobs(project)),
        }
    readiness = verify_production_models(paths, project, run, min(timeout_seconds, 300))
    project["phase"] = "production"
    project["status"] = "running"
    save(paths, project, run)
    media_jobs = [
        item
        for item in jobs(project)
        if item.get("kind")
        in {
            "cast-master",
            "location-master",
            "keyframe",
            "dialogue",
            "sound-effect",
            "clip",
            "clip-candidate",
            "score",
        }
    ]
    order = {
        "cast-master": 0,
        "location-master": 0,
        "keyframe": 1,
        "dialogue": 2,
        "sound-effect": 2,
        "clip": 3,
        "clip-candidate": 3,
        "score": 4,
    }
    media_jobs.sort(key=lambda item: (order.get(str(item.get("kind")), 99), str(item.get("id"))))
    for item in media_jobs:
        execute_media_job(
            paths=paths,
            project=project,
            run=run,
            job=item,
            timeout_seconds=timeout_seconds,
        )
    selection_receipt = select_best_takes(paths, project, run, timeout_seconds)
    dialogue_qc = verify_dialogue(paths, project, run, timeout_seconds)
    sound_qc = verify_sound_effects(paths, project, run)
    captions_receipt = prepare_captions(paths, project, run)
    rough_cut = assemble_rough_cut(paths, project, run)
    return {
        "executed": True,
        "mode": mode,
        "roughCut": str(rough_cut),
        "sha256": file_sha256(rough_cut),
        "dialogueQc": str(dialogue_qc),
        "soundQc": str(sound_qc),
        "captions": str(captions_receipt),
        "takeSelection": str(selection_receipt) if selection_receipt else None,
        "modelReadiness": str(readiness),
        "jobs": len(media_jobs) + len([item for item in jobs(project) if item.get("kind") == "take-selection"]) + 1,
    }


def transcript_words(value: str) -> list[str]:
    return re.findall(r"[\w']+", value.casefold(), flags=re.UNICODE)


def transcript_recall(expected: str, actual: str) -> float:
    expected_words = transcript_words(expected)
    if not expected_words:
        return 1.0
    actual_words = set(transcript_words(actual))
    return sum(1 for word in expected_words if word in actual_words) / len(expected_words)


def verify_dialogue(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    timeout_seconds: int,
) -> pathlib.Path:
    dialogue = [item for item in jobs(project) if item.get("kind") == "dialogue"]
    sources: list[JsonMap] = []
    for line in dialogue:
        audio = output_path(paths, line)
        if line.get("status") != "succeeded" or not audio.is_file() or audio.stat().st_size == 0:
            raise PluginError(f"dialogue job {line.get('id')} is incomplete")
        sources.append(
            {
                "jobId": line.get("id"),
                "audioSha256": file_sha256(audio),
                "text": line.get("text"),
                "speaker": line.get("speaker"),
            }
        )
    target = as_map(production_plan(paths).get("target"), "productionPlan.target")
    language = as_string(target.get("language"), "productionPlan.target.language")
    mere_run = command_value(project, "mereRun")
    asr_model = optional_string(model_config(project).get("speechAsr"))
    source_digest = object_sha256(
        {
            "verificationProfile": "asr-word-recall-0.6-v1",
            "asrModel": asr_model or "default-auto",
            "language": language,
            "sources": sources,
        }
    )
    receipt_path = paths.reviews / "dialogue-qc.json"
    if receipt_path.is_file() and matching_artifact(paths, project, receipt_path, "dialogue-qc"):
        cached = load_json(receipt_path)
        if cached.get("sourceDigest") == source_digest:
            as_map(project.get("proof"), "project.proof")["dialogue"] = True
            return receipt_path
    if receipt_path.is_file():
        archive_unverified_output(paths, project, run, receipt_path, "dialogue-qc")
    results: list[JsonMap] = []
    try:
        for line in dialogue:
            line_id = as_string(line.get("id"), "dialogue job.id")
            audio = output_path(paths, line)
            command = [
                mere_run,
                "speech",
                "transcribe",
                str(audio),
                "--backend",
                "auto",
                "--task",
                "transcribe",
                "--language",
                language,
                "--no-timestamps",
            ]
            if asr_model:
                command.extend(["--model", asr_model])
            process = run_child(
                command,
                paths.root,
                paths.logs / "media" / f"transcribe-{slug(line_id)}.log",
                timeout_seconds,
            )
            expected = as_string(line.get("text"), f"dialogue {line_id}.text")
            actual = process.stdout.strip()
            recall = transcript_recall(expected, actual)
            results.append(
                {
                    "jobId": line_id,
                    "shotId": line.get("subject"),
                    "speaker": line.get("speaker"),
                    "audio": str(audio.relative_to(paths.root)),
                    "audioSha256": file_sha256(audio),
                    "expected": expected,
                    "transcript": actual,
                    "wordRecall": round(recall, 4),
                    "decision": "pass" if recall >= 0.6 else "review",
                }
            )
        review_count = sum(1 for item in results if item.get("decision") == "review")
        payload: JsonMap = {
            "contractVersion": "mere.run/film-dialogue-qc.v1",
            "projectId": project.get("projectId"),
            "createdAt": now_iso(),
            "sourceDigest": source_digest,
            "verifier": {
                "command": "mere.run speech transcribe",
                "model": asr_model or "default-auto",
                "profile": "asr-word-recall-0.6-v1",
            },
            "complete": len(results) == len(dialogue),
            "summary": {"lines": len(results), "passed": len(results) - review_count, "review": review_count},
            "lines": results,
        }
        write_json(receipt_path, payload)
        add_artifact(paths, project, run, receipt_path, "dialogue-qc", "application/json", source="mere.run-speech")
        as_map(project.get("proof"), "project.proof")["dialogue"] = True
        clear_issue(project, "dialogue-qc-failed")
        if review_count:
            set_issue(
                project,
                "dialogue-qc-findings",
                f"Speech transcription marked {review_count} of {len(results)} dialogue lines for reviewer attention.",
                False,
            )
        else:
            clear_issue(project, "dialogue-qc-findings")
        history(
            project,
            "dialogue-verified",
            f"Transcribed {len(results)} generated dialogue lines; {review_count} require reviewer attention.",
        )
        save(paths, project, run)
        return receipt_path
    except Exception as exc:
        as_map(project.get("proof"), "project.proof")["dialogue"] = False
        set_issue(project, "dialogue-qc-failed", str(exc), True)
        project["status"] = "failed"
        save(paths, project, run)
        raise


def verify_sound_effects(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> pathlib.Path:
    effects = [item for item in jobs(project) if item.get("kind") == "sound-effect"]
    sources: list[JsonMap] = []
    for effect in effects:
        audio = output_path(paths, effect)
        if effect.get("status") != "succeeded" or not audio.is_file() or audio.stat().st_size == 0:
            raise PluginError(f"sound effect job {effect.get('id')} is incomplete")
        sources.append(
            {
                "jobId": effect.get("id"),
                "shotId": effect.get("subject"),
                "prompt": effect.get("text"),
                "startSeconds": effect.get("startSeconds"),
                "levelDb": effect.get("levelDb"),
                "audioSha256": file_sha256(audio),
            }
        )
    sources.sort(key=lambda item: str(item.get("jobId")))
    source_digest = object_sha256({"verificationProfile": "audio-stream-duration-peak-v2", "sources": sources})
    receipt_path = paths.reviews / "sound-qc.json"
    if receipt_path.is_file() and matching_artifact(paths, project, receipt_path, "sound-qc"):
        cached = load_json(receipt_path)
        if cached.get("sourceDigest") == source_digest:
            as_map(project.get("proof"), "project.proof")["sound"] = True
            return receipt_path
    if receipt_path.is_file():
        archive_unverified_output(paths, project, run, receipt_path, "sound-qc")
    results: list[JsonMap] = []
    ffprobe = command_value(project, "ffprobe")
    ffmpeg = command_value(project, "ffmpeg")
    for effect in effects:
        audio = output_path(paths, effect)
        report = probe_media(audio, ffprobe)
        format_info = as_map(report.get("format"), "sound effect ffprobe.format")
        try:
            duration = float(str(format_info.get("duration") or "0"))
        except ValueError:
            duration = 0.0
        streams = as_list(report.get("streams"), "sound effect ffprobe.streams")
        audio_stream = next(
            (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"),
            None,
        )
        peak_process = run_child(
            [ffmpeg, "-hide_banner", "-nostats", "-i", str(audio), "-af", "volumedetect", "-f", "null", "-"],
            paths.root,
            paths.logs / "media" / f"sound-peak-{slug(as_string(effect.get('id'), 'sound effect.id'))}.log",
            300,
        )
        peak_match = re.search(r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB", peak_process.stderr)
        if not peak_match:
            raise PluginError(f"sound effect job {effect.get('id')} did not produce a peak measurement")
        peak_text = peak_match.group(1)
        peak_dbfs = -200.0 if peak_text == "-inf" else float(peak_text)
        audible = peak_dbfs >= SFX_MINIMUM_PEAK_DBFS
        results.append(
            {
                "jobId": effect.get("id"),
                "shotId": effect.get("subject"),
                "audio": str(audio.relative_to(paths.root)),
                "audioSha256": file_sha256(audio),
                "durationSeconds": duration,
                "hasAudioStream": audio_stream is not None,
                "peakDbfs": peak_dbfs,
                "audible": audible,
                "passed": audio_stream is not None and duration > 0 and audible,
            }
        )
    passed_count = sum(item.get("passed") is True for item in results)
    payload: JsonMap = {
        "contractVersion": "mere.run/film-sound-qc.v1",
        "projectId": project.get("projectId"),
        "createdAt": now_iso(),
        "sourceDigest": source_digest,
        "verifier": {
            "command": "ffprobe + ffmpeg volumedetect",
            "profile": "audio-stream-duration-peak-v2",
            "minimumPeakDbfs": SFX_MINIMUM_PEAK_DBFS,
        },
        "complete": passed_count == len(results),
        "summary": {"cues": len(results), "passed": passed_count, "failed": len(results) - passed_count},
        "cues": results,
    }
    write_json(receipt_path, payload)
    add_artifact(paths, project, run, receipt_path, "sound-qc", "application/json", source="ffprobe+ffmpeg")
    proof = as_map(project.get("proof"), "project.proof")
    proof["sound"] = payload.get("complete") is True
    if payload.get("complete") is not True:
        project["status"] = "revision-required"
        set_issue(
            project,
            "sound-qc-failed",
            "One or more generated sound effects failed stream, duration, or audibility validation.",
            True,
        )
    else:
        clear_issue(project, "sound-qc-failed")
        history(project, "sound-verified", f"Validated {len(results)} timed sound-effect cues.")
    save(paths, project, run)
    if payload.get("complete") is not True:
        raise PluginError("sound-effect QC failed", 2)
    return receipt_path


def caption_timestamp(seconds: float, *, webvtt: bool) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    separator = "." if webvtt else ","
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{millis:03d}"


def dialogue_audio_duration(path: pathlib.Path, project: JsonMap) -> float:
    report = probe_media(path, command_value(project, "ffprobe"))
    format_info = as_map(report.get("format"), "dialogue ffprobe.format")
    try:
        duration = float(str(format_info.get("duration") or "0"))
    except ValueError:
        duration = 0.0
    return duration if duration > 0 else 2.0


def prepare_captions(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> pathlib.Path:
    plan = production_plan(paths)
    target = as_map(plan.get("target"), "productionPlan.target")
    language = slug(as_string(target.get("language"), "productionPlan.target.language"), "en")
    srt_path = paths.captions / f"subtitles.{language}.srt"
    vtt_path = paths.captions / f"subtitles.{language}.vtt"
    receipt_path = paths.captions / "captions.json"
    source_jobs: list[JsonMap] = []
    for line in jobs(project):
        if line.get("kind") != "dialogue":
            continue
        audio = output_path(paths, line)
        if line.get("status") != "succeeded" or not audio.is_file() or audio.stat().st_size == 0:
            raise PluginError(f"cannot caption incomplete dialogue job {line.get('id')}")
        source_jobs.append(
            {
                "jobId": line.get("id"),
                "shotId": line.get("subject"),
                "speaker": line.get("speaker"),
                "text": line.get("text"),
                "startSeconds": line.get("startSeconds"),
                "audioSha256": file_sha256(audio),
            }
        )
    source_jobs.sort(key=lambda item: str(item.get("jobId")))
    source_digest = object_sha256(
        {
            "captionProfile": "dialogue-timeline-sidecar-v1",
            "language": language,
            "shots": [
                {
                    "id": shot.get("id"),
                    "durationSeconds": shot.get("durationSeconds"),
                }
                for shot in shot_items(plan)
            ],
            "dialogue": source_jobs,
        }
    )
    if (
        receipt_path.is_file()
        and srt_path.is_file()
        and vtt_path.is_file()
        and matching_artifact(paths, project, receipt_path, "caption-receipt")
        and matching_artifact(paths, project, srt_path, "subtitle-srt")
        and matching_artifact(paths, project, vtt_path, "subtitle-vtt")
        and load_json(receipt_path).get("sourceDigest") == source_digest
    ):
        as_map(project.get("proof"), "project.proof")["captions"] = True
        return receipt_path
    for path, label in (
        (receipt_path, "caption-receipt"),
        (srt_path, "subtitle-srt"),
        (vtt_path, "subtitle-vtt"),
    ):
        if path.is_file():
            archive_unverified_output(paths, project, run, path, label)
    cues: list[JsonMap] = []
    shot_offset = 0.0
    for shot in shot_items(plan):
        shot_id = as_string(shot.get("id"), "shot.id")
        shot_duration = as_number(shot.get("durationSeconds"), f"shot {shot_id}.durationSeconds")
        for line in dialogue_jobs_for_shot(project, shot_id):
            audio = output_path(paths, line)
            local_start = as_number(line.get("startSeconds"), f"dialogue {line.get('id')}.startSeconds")
            minimum_cue = min(0.25, shot_duration)
            bounded_start = min(max(0.0, local_start), max(0.0, shot_duration - minimum_cue))
            start = shot_offset + bounded_start
            available = shot_duration - bounded_start
            duration = min(max(minimum_cue, dialogue_audio_duration(audio, project)), available)
            end = start + duration
            text = re.sub(r"\s+", " ", as_string(line.get("text"), f"dialogue {line.get('id')}.text")).strip()
            speaker = as_string(line.get("speaker"), f"dialogue {line.get('id')}.speaker")
            cues.append(
                {
                    "index": len(cues) + 1,
                    "jobId": line.get("id"),
                    "shotId": shot_id,
                    "speaker": speaker,
                    "text": text,
                    "startSeconds": round(start, 3),
                    "endSeconds": round(end, 3),
                }
            )
        shot_offset += shot_duration
    srt_blocks = [
        f"{cue['index']}\n{caption_timestamp(as_number(cue['startSeconds'], 'cue.start'), webvtt=False)} --> "
        f"{caption_timestamp(as_number(cue['endSeconds'], 'cue.end'), webvtt=False)}\n"
        f"{cue['speaker']}: {cue['text']}"
        for cue in cues
    ]
    vtt_blocks = [
        f"{caption_timestamp(as_number(cue['startSeconds'], 'cue.start'), webvtt=True)} --> "
        f"{caption_timestamp(as_number(cue['endSeconds'], 'cue.end'), webvtt=True)}\n"
        f"<v {cue['speaker']}>{html.escape(str(cue['text']), quote=False)}"
        for cue in cues
    ]
    write_text(srt_path, "\n\n".join(srt_blocks) + ("\n" if srt_blocks else ""))
    write_text(vtt_path, "WEBVTT\n\n" + "\n\n".join(vtt_blocks) + ("\n" if vtt_blocks else ""))
    payload: JsonMap = {
        "contractVersion": "mere.run/film-captions.v1",
        "projectId": project.get("projectId"),
        "createdAt": now_iso(),
        "sourceDigest": source_digest,
        "language": language,
        "profile": "dialogue-timeline-sidecar-v1",
        "complete": len(cues) == len(source_jobs),
        "summary": {"cues": len(cues)},
        "files": {
            "srt": {"path": str(srt_path.relative_to(paths.root)), "sha256": file_sha256(srt_path)},
            "vtt": {"path": str(vtt_path.relative_to(paths.root)), "sha256": file_sha256(vtt_path)},
        },
        "cues": cues,
    }
    write_json(receipt_path, payload)
    add_artifact(paths, project, run, srt_path, "subtitle-srt", "application/x-subrip", source="film-timeline")
    add_artifact(paths, project, run, vtt_path, "subtitle-vtt", "text/vtt", source="film-timeline")
    add_artifact(paths, project, run, receipt_path, "caption-receipt", "application/json", source="film-timeline")
    as_map(project.get("proof"), "project.proof")["captions"] = True
    clear_issue(project, "caption-generation-failed")
    history(project, "captions-prepared", f"Wrote SRT and WebVTT sidecars for {len(cues)} dialogue cues.")
    save(paths, project, run)
    return receipt_path


def analyze_loudness(path: pathlib.Path, project: JsonMap) -> JsonMap:
    try:
        process = run_child(
            [
                command_value(project, "ffmpeg"),
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json",
                "-f",
                "null",
                "-",
            ],
            path.parent,
            path.parent / f".{path.name}.loudness-analysis.log",
            600,
        )
    except PluginError as exc:
        return {
            "contractVersion": "mere.run/film-loudness-analysis.v1",
            "available": False,
            "target": {"integratedLufs": -16, "loudnessRange": 11, "truePeakDbtp": -1.5},
            "error": str(exc),
        }
    start = process.stderr.rfind("{")
    end = process.stderr.rfind("}")
    if start < 0 or end <= start:
        return {
            "contractVersion": "mere.run/film-loudness-analysis.v1",
            "available": False,
            "target": {"integratedLufs": -16, "loudnessRange": 11, "truePeakDbtp": -1.5},
            "error": "ffmpeg did not emit a loudnorm measurement object",
        }
    try:
        measurement = as_map(json.loads(process.stderr[start : end + 1]), "loudness measurement")
    except json.JSONDecodeError as exc:
        return {
            "contractVersion": "mere.run/film-loudness-analysis.v1",
            "available": False,
            "target": {"integratedLufs": -16, "loudnessRange": 11, "truePeakDbtp": -1.5},
            "error": f"invalid loudnorm measurement: {exc}",
        }
    return {
        "contractVersion": "mere.run/film-loudness-analysis.v1",
        "available": True,
        "target": {"integratedLufs": -16, "loudnessRange": 11, "truePeakDbtp": -1.5},
        "measurement": measurement,
    }


def technical_review(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> JsonMap:
    rough_cut = paths.cuts / "rough-cut.mp4"
    if not rough_cut.is_file():
        raise PluginError("rough cut is missing; cannot review", 2)
    report = probe_media(rough_cut, command_value(project, "ffprobe"))
    plan = production_plan(paths)
    target = as_map(plan.get("target"), "productionPlan.target")
    streams = [as_map(item, "ffprobe stream") for item in as_list(report.get("streams"), "ffprobe.streams")]
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    format_info = as_map(report.get("format"), "ffprobe.format")
    try:
        duration = float(str(format_info.get("duration") or "0"))
    except ValueError:
        duration = 0.0
    planned_duration = as_number(
        plan.get("plannedDurationSeconds") or target.get("durationSeconds"),
        "productionPlan.plannedDurationSeconds",
    )
    tolerance = max(2.0, planned_duration * 0.12)
    checks = [
        {"name": "non-empty-file", "passed": rough_cut.stat().st_size > 0, "detail": rough_cut.stat().st_size},
        {"name": "video-stream", "passed": video is not None, "detail": video or {}},
        {"name": "audio-stream", "passed": audio is not None, "detail": audio or {}},
        {
            "name": "audio-sample-rate",
            "passed": audio is not None and str(audio.get("sample_rate")) == "48000",
            "detail": {
                "actual": audio.get("sample_rate") if audio else None,
                "expected": "48000",
            },
        },
        {
            "name": "geometry",
            "passed": video is not None
            and video.get("width") == target.get("width")
            and video.get("height") == target.get("height"),
            "detail": {
                "actual": [video.get("width"), video.get("height")] if video else None,
                "expected": [target.get("width"), target.get("height")],
            },
        },
        {
            "name": "duration",
            "passed": duration > 0 and abs(duration - planned_duration) <= tolerance,
            "detail": {"actual": duration, "planned": planned_duration, "tolerance": tolerance},
        },
    ]
    signal_analysis = analyze_media_signal(rough_cut, project) if video is not None and audio is not None else None
    loudness_analysis = analyze_loudness(rough_cut, project) if audio is not None else None
    measurement = (
        as_map(loudness_analysis.get("measurement"), "loudness measurement")
        if loudness_analysis and loudness_analysis.get("available") is True
        else {}
    )
    try:
        integrated_lufs = float(str(measurement.get("input_i")))
        true_peak_dbtp = float(str(measurement.get("input_tp")))
    except (TypeError, ValueError):
        integrated_lufs = 0.0
        true_peak_dbtp = 0.0
    loudness_passed = (
        loudness_analysis is not None
        and loudness_analysis.get("available") is True
        and -18.0 <= integrated_lufs <= -14.0
        and true_peak_dbtp <= -1.0
    )
    checks.append(
        {
            "name": "loudness-master",
            "passed": loudness_passed,
            "detail": {
                "integratedLufs": integrated_lufs if measurement else None,
                "truePeakDbtp": true_peak_dbtp if measurement else None,
                "targetIntegratedLufs": -16.0,
                "targetTruePeakDbtp": -1.5,
                "toleranceLufs": 2.0,
            },
        }
    )
    passed = all(bool(item.get("passed")) for item in checks)
    payload: JsonMap = {
        "contractVersion": "mere.run/film-technical-review.v1",
        "projectId": project.get("projectId"),
        "createdAt": now_iso(),
        "passed": passed,
        "master": {
            "path": str(rough_cut.relative_to(paths.root)),
            "sha256": file_sha256(rough_cut),
            "bytes": rough_cut.stat().st_size,
            "durationSeconds": duration,
        },
        "checks": checks,
        "signalAnalysis": signal_analysis,
        "loudnessAnalysis": loudness_analysis,
        "ffprobe": report,
    }
    path = paths.reviews / "technical-qc.json"
    write_json(path, payload)
    add_artifact(paths, project, run, path, "technical-review", "application/json", source="ffprobe")
    if not passed:
        project["status"] = "revision-required"
        set_issue(project, "technical-review", "Rough cut failed one or more technical delivery checks.", True)
    else:
        clear_issue(project, "technical-review")
        history(
            project,
            "technical-review-passed",
            "Rough cut passed file, stream, geometry, duration, and loudness checks; signal scans were recorded.",
        )
    save(paths, project, run)
    return payload


def prepare_review_attachments(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    count: int = 5,
) -> list[pathlib.Path]:
    rough_cut = paths.cuts / "rough-cut.mp4"
    if not rough_cut.is_file():
        raise PluginError("rough cut is missing; cannot prepare creative review", 2)
    plan = production_plan(paths)
    target = as_map(plan.get("target"), "productionPlan.target")
    duration = as_number(
        plan.get("plannedDurationSeconds") or target.get("durationSeconds"),
        "productionPlan.plannedDurationSeconds",
    )
    if count < 1:
        raise PluginError("review attachment count must be positive", 2)
    directory = paths.reviews / "frames"
    directory.mkdir(parents=True, exist_ok=True)
    attachments: list[pathlib.Path] = []
    ffmpeg = command_value(project, "ffmpeg")
    for index in range(count):
        output = directory / f"review-{index + 1:02d}.png"
        if output.is_file() and matching_artifact(paths, project, output, "review-frame"):
            attachments.append(output)
            continue
        if output.is_file():
            archive_unverified_output(paths, project, run, output, f"review-frame-{index + 1}")
        timestamp = duration * ((index + 0.5) / count)
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(rough_cut),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(1280,iw)':-2",
            str(output),
        ]
        run_child(command, paths.root, paths.logs / "media" / f"review-frame-{index + 1}.log", 300)
        if not output.is_file() or output.stat().st_size == 0:
            raise PluginError(f"review frame extraction did not produce {output}")
        add_artifact(paths, project, run, output, "review-frame", "image/png", source="ffmpeg")
        attachments.append(output)
    history(project, "review-frames-prepared", f"Extracted {len(attachments)} frames from the assembled rough cut.")
    save(paths, project, run)
    return attachments


def inspection_source_digest(paths: ProjectPaths, plan: JsonMap) -> str:
    sources: list[JsonMap] = []
    for shot in shot_items(plan):
        shot_id = as_string(shot.get("id"), "shot.id")
        clip = clip_output(paths, shot_id)
        if not clip.is_file() or clip.stat().st_size == 0:
            raise PluginError(f"cannot inspect generated media: missing clip {shot_id}", 2)
        sources.append(
            {
                "shotId": shot_id,
                "clipSha256": file_sha256(clip),
                "purpose": shot.get("purpose"),
                "framePrompt": shot.get("framePrompt"),
                "characters": shot.get("characters"),
                "location": shot.get("location"),
                "durationSeconds": shot.get("durationSeconds"),
            }
        )
    return object_sha256({"inspectionProfile": "early-mid-late-contact-sheet-v1", "sources": sources})


def parse_inspection_response(text: str, shot_id: str) -> JsonMap:
    stripped = text.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        stripped = stripped[7:-3].strip()
    elif stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3].strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise PluginError(f"local vision returned non-JSON inspection for {shot_id}: {exc}") from None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as nested:
            raise PluginError(f"local vision returned invalid inspection JSON for {shot_id}: {nested}") from None
    payload = as_map(value, f"media inspection for {shot_id}")
    decision = as_string(payload.get("decision"), f"media inspection {shot_id}.decision")
    if decision not in {"pass", "review"}:
        raise PluginError(f"local vision decision for {shot_id} must be pass or review")
    observations = as_list(payload.get("observations"), f"media inspection {shot_id}.observations")
    mismatches = as_list(payload.get("mismatches"), f"media inspection {shot_id}.mismatches")
    if not all(isinstance(item, str) for item in observations):
        raise PluginError(f"local vision observations for {shot_id} must be strings")
    if len(observations) > 5:
        raise PluginError(f"local vision observations for {shot_id} must contain at most 5 items")
    if not all(isinstance(item, dict) for item in mismatches):
        raise PluginError(f"local vision mismatches for {shot_id} must be objects")
    if len(mismatches) > 8:
        raise PluginError(f"local vision mismatches for {shot_id} must contain at most 8 items")
    for index, raw in enumerate(mismatches, start=1):
        mismatch = as_map(raw, f"media inspection {shot_id}.mismatches[{index}]")
        for key in ("code", "severity", "message"):
            as_string(mismatch.get(key), f"media inspection {shot_id}.mismatches[{index}].{key}")
    confidence = as_number(payload.get("confidence"), f"media inspection {shot_id}.confidence")
    if confidence < 0 or confidence > 1:
        raise PluginError(f"local vision confidence for {shot_id} must be between 0 and 1")
    return payload


def expected_shot_canon(plan: JsonMap, shot: JsonMap) -> JsonMap:
    cast_by_id = {
        as_string(item.get("id"), "cast.id"): item
        for item in cast_items(plan)
    }
    locations_by_id = {
        as_string(item.get("id"), "location.id"): item
        for item in location_items(plan)
    }
    character_ids = [str(value) for value in as_list(shot.get("characters"), "shot.characters")]
    location_id = as_string(shot.get("location"), "shot.location")
    visible_characters = []
    for value in character_ids:
        if value not in cast_by_id:
            continue
        person = cast_by_id[value]
        visible_characters.append(
            {
                "id": value,
                "name": person.get("name"),
                "visual": person.get("visual"),
                "wardrobe": person.get("wardrobe"),
            }
        )
    location = locations_by_id.get(location_id, {"id": location_id})
    visible_location = {
        "id": location_id,
        "name": location.get("name"),
        "visual": location.get("visual"),
    }
    return {
        "shotId": shot.get("id"),
        "purpose": shot.get("purpose"),
        "prompt": shot.get("prompt"),
        "framePrompt": shot.get("framePrompt"),
        "characters": visible_characters,
        "location": visible_location,
    }


def inspection_prompt(plan: JsonMap, shot: JsonMap) -> str:
    expected = expected_shot_canon(plan, shot)
    return (
        "You are a conservative film continuity inspector. The image is a left-to-right early, midpoint, and late "
        "contact sheet from one generated shot. Compare only visible evidence across all three moments "
        "against the expected production canon below. Do not invent identity, action, or off-frame detail. Flag malformed "
        "anatomy, unreadable composition, missing required subjects, wardrobe/location drift, unwanted text, and obvious "
        "generation artifacts. Do not report IDs, seeds, voice, ambience, or prompt text as visual mismatches. Return "
        "exactly one JSON object with decision ('pass' or 'review'), observations (array of "
        "strings), mismatches (array of objects with code, severity, and message), and confidence (number from 0 to 1). "
        "Use at most 3 concise observations and 5 concise mismatches. Use review whenever the visible evidence is "
        "ambiguous or materially conflicts with canon.\nExpected visible canon:\n"
        + json.dumps(expected, indent=2, sort_keys=True)
    )


def extract_contact_sheet(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    source: pathlib.Path,
    output: pathlib.Path,
    duration_seconds: float,
    artifact_kind: str,
    log_name: str,
) -> pathlib.Path:
    if output.is_file():
        archive_unverified_output(paths, project, run, output, log_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [command_value(project, "ffmpeg"), "-y", "-loglevel", "error"]
    for fraction in (0.1, 0.5, 0.9):
        command.extend(["-ss", f"{duration_seconds * fraction:.3f}", "-i", str(source)])
    command.extend(
        [
            "-filter_complex",
            "[0:v]scale=420:-2[a];[1:v]scale=420:-2[b];[2:v]scale=420:-2[c];"
            "[a][b][c]hstack=inputs=3[sheet]",
            "-map",
            "[sheet]",
            "-frames:v",
            "1",
            str(output),
        ]
    )
    run_child(command, paths.root, paths.logs / "media" / f"{slug(log_name)}.log", 300)
    if not output.is_file() or output.stat().st_size == 0:
        raise PluginError(f"contact sheet extraction did not produce {output}")
    add_artifact(paths, project, run, output, artifact_kind, "image/png", source="ffmpeg")
    return output


def take_selection_prompt(plan: JsonMap, shot: JsonMap, candidate_index: int, candidate_count: int) -> str:
    expected = expected_shot_canon(plan, shot)
    return (
        "You are selecting a production take for a short film. The image is a left-to-right early, midpoint, and late "
        f"contact sheet for candidate {candidate_index} of {candidate_count}. Score only visible evidence against canon. "
        "Reward coherent motion, stable identity and wardrobe, readable composition, clean anatomy, location continuity, "
        "and fulfillment of the intended action. Penalize frozen action, morphing, text artifacts, discontinuity, and "
        "material deviation. Do not infer off-frame detail. Return exactly one JSON object with decision ('pass' or "
        "'review'), score (number from 0 to 100), observations (array of strings), mismatches (array of objects with code, "
        "severity, and message), and confidence (number from 0 to 1). Do not report IDs, seeds, voice, ambience, or prompt "
        "text as visual mismatches. Use at most 3 concise observations and 5 concise mismatches. This is a take-selection "
        "comparison; use the full score range and use review when the evidence is ambiguous or unsuitable.\nExpected "
        "visible canon:\n"
        + json.dumps(expected, indent=2, sort_keys=True)
    )


def run_vision_json(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    image: pathlib.Path,
    prompt: str,
    max_tokens: int,
    log_name: str,
    timeout_seconds: int,
    parser: Callable[[str], JsonMap],
) -> JsonMap:
    mere_run = command_value(project, "mereRun")
    inspector_model = as_string(model_config(project).get("visionInspector"), "models.visionInspector")
    last_error = ""
    for attempt in range(1, 3):
        attempt_prompt = prompt
        if attempt > 1:
            attempt_prompt += (
                "\nYour prior response was invalid or truncated. Return only the compact JSON object. "
                "Use no more than 3 observations and 5 mismatches, with each string under 160 characters."
            )
        command = [
            mere_run,
            "vision",
            "inspect",
            str(image),
            "--prompt",
            attempt_prompt,
            "--max-tokens",
            str(max_tokens),
            "--temperature",
            "0.1",
            "--top-p",
            "0.9",
        ]
        if inspector_model != AUTO_VISION_INSPECTOR:
            command.extend(["--model", inspector_model])
        process = run_child(
            command,
            paths.root,
            paths.logs / "media" / f"{slug(log_name)}-attempt-{attempt}.log",
            timeout_seconds,
        )
        try:
            return parser(process.stdout)
        except PluginError as exc:
            last_error = str(exc)
    raise PluginError(f"local vision failed to return bounded valid JSON after 2 attempts: {last_error}")


def parse_take_selection_response(text: str, shot_id: str, candidate_index: int) -> JsonMap:
    payload = parse_inspection_response(text, f"{shot_id} candidate {candidate_index}")
    score = as_number(payload.get("score"), f"take selection {shot_id} candidate {candidate_index}.score")
    if score < 0 or score > 100:
        raise PluginError(f"take selection score for {shot_id} candidate {candidate_index} must be between 0 and 100")
    return payload


def take_selection_source_digest(paths: ProjectPaths, project: JsonMap, plan: JsonMap) -> str:
    candidates: list[JsonMap] = []
    for job in jobs(project):
        if job.get("kind") != "clip-candidate":
            continue
        path = output_path(paths, job)
        if job.get("status") != "succeeded" or not path.is_file() or path.stat().st_size == 0:
            raise PluginError(f"take candidate {job.get('id')} is incomplete")
        candidates.append(
            {
                "jobId": job.get("id"),
                "shotId": job.get("subject"),
                "candidateIndex": job.get("candidateIndex"),
                "specSha256": job.get("specSha256"),
                "sha256": file_sha256(path),
            }
        )
    candidates.sort(
        key=lambda item: (
            str(item.get("shotId")),
            as_int(item.get("candidateIndex"), "take candidate.candidateIndex"),
        )
    )
    return object_sha256(
        {
            "selectionProfile": "canon-aware-contact-sheet-v1",
            "model": model_config(project).get("visionInspector") or "default-local",
            "canon": [expected_shot_canon(plan, shot) for shot in shot_items(plan)],
            "candidates": candidates,
        }
    )


def selected_take_receipt_is_current(
    paths: ProjectPaths,
    project: JsonMap,
    receipt: JsonMap,
    source_digest: str,
) -> bool:
    if receipt.get("sourceDigest") != source_digest:
        return False
    for raw in as_list(receipt.get("shots"), "take selection.shots"):
        item = as_map(raw, "take selection shot")
        shot_id = as_string(item.get("shotId"), "take selection shot.shotId")
        output = clip_output(paths, shot_id)
        if (
            not output.is_file()
            or item.get("selectedSha256") != file_sha256(output)
            or not matching_artifact(paths, project, output, "shot-clip")
        ):
            return False
    return True


def select_best_takes(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    timeout_seconds: int,
) -> pathlib.Path | None:
    if takes_per_shot(project) == 1:
        return None
    plan = production_plan(paths)
    receipt_path = paths.reviews / "take-selection.json"
    source_digest = take_selection_source_digest(paths, project, plan)
    if receipt_path.is_file() and matching_artifact(paths, project, receipt_path, "take-selection"):
        cached = load_json(receipt_path)
        if selected_take_receipt_is_current(paths, project, cached, source_digest):
            for raw in as_list(cached.get("shots"), "take selection.shots"):
                item = as_map(raw, "take selection shot")
                selection_job = job_by_id(project, f"select-{slug(as_string(item.get('shotId'), 'shotId'))}")
                if selection_job:
                    selection_job["status"] = "succeeded"
                    selection_job["sha256"] = item.get("selectedSha256")
                    selection_job["completedSpecSha256"] = selection_job.get("specSha256")
                    selection_job["reused"] = True
            save(paths, project, run)
            return receipt_path
    if receipt_path.is_file():
        archive_unverified_output(paths, project, run, receipt_path, "take-selection")
    inspector_model = as_string(model_config(project).get("visionInspector"), "models.visionInspector")
    selections: list[JsonMap] = []
    selected_for_review = 0
    try:
        for shot in shot_items(plan):
            shot_id = as_string(shot.get("id"), "shot.id")
            selection_job = job_by_id(project, f"select-{slug(shot_id)}")
            if not selection_job or not dependencies_succeeded(project, selection_job):
                raise PluginError(f"take selection for {shot_id} has incomplete candidates")
            selection_job["status"] = "running"
            selection_job["startedAt"] = now_iso()
            selection_job["attempts"] = as_int(selection_job.get("attempts", 0), "selection job.attempts") + 1
            save(paths, project, run)
            candidates = [
                item
                for item in jobs(project)
                if item.get("kind") == "clip-candidate" and item.get("subject") == shot_id
            ]
            candidates.sort(key=lambda item: as_int(item.get("candidateIndex"), "candidateIndex"))
            evaluated: list[JsonMap] = []
            for candidate in candidates:
                candidate_index = as_int(candidate.get("candidateIndex"), "candidateIndex")
                source = output_path(paths, candidate)
                sheet = paths.reviews / "take-selection" / slug(shot_id) / f"candidate-{candidate_index:03d}.png"
                extract_contact_sheet(
                    paths=paths,
                    project=project,
                    run=run,
                    source=source,
                    output=sheet,
                    duration_seconds=as_number(shot.get("durationSeconds"), f"shot {shot_id}.durationSeconds"),
                    artifact_kind="take-selection-frame",
                    log_name=f"take-selection-{shot_id}-{candidate_index}",
                )
                result = run_vision_json(
                    paths=paths,
                    project=project,
                    image=sheet,
                    prompt=take_selection_prompt(plan, shot, candidate_index, len(candidates)),
                    max_tokens=900,
                    log_name=f"take-selection-{shot_id}-{candidate_index:03d}",
                    timeout_seconds=timeout_seconds,
                    parser=partial(
                        parse_take_selection_response,
                        shot_id=shot_id,
                        candidate_index=candidate_index,
                    ),
                )
                evaluated.append(
                    {
                        "candidateIndex": candidate_index,
                        "jobId": candidate.get("id"),
                        "seed": as_int(shot.get("seed"), f"shot {shot_id}.seed") + candidate_index - 1,
                        "path": str(source.relative_to(paths.root)),
                        "sha256": file_sha256(source),
                        "contactSheet": str(sheet.relative_to(paths.root)),
                        "contactSheetSha256": file_sha256(sheet),
                        "decision": result.get("decision"),
                        "score": result.get("score"),
                        "confidence": result.get("confidence"),
                        "observations": result.get("observations"),
                        "mismatches": result.get("mismatches"),
                    }
                )
            winner = max(
                evaluated,
                key=lambda item: (
                    as_number(item.get("score"), "candidate.score"),
                    as_number(item.get("confidence"), "candidate.confidence"),
                    -as_int(item.get("candidateIndex"), "candidate.candidateIndex"),
                ),
            )
            canonical = clip_output(paths, shot_id)
            winner_path = paths.root / as_string(winner.get("path"), "winner.path")
            winner_hash = file_sha256(winner_path)
            canonical_is_current = (
                canonical.is_file()
                and file_sha256(canonical) == winner_hash
                and matching_artifact(paths, project, canonical, "shot-clip")
            )
            if canonical.is_file() and not canonical_is_current:
                archive_unverified_output(paths, project, run, canonical, f"selected-take-{shot_id}")
            if not canonical_is_current:
                canonical.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(winner_path, canonical)
            add_artifact(paths, project, run, canonical, "shot-clip", "video/mp4", source="local-take-selector")
            selection_job["status"] = "succeeded"
            selection_job["completedAt"] = now_iso()
            selection_job["sha256"] = winner_hash
            selection_job["completedSpecSha256"] = selection_job.get("specSha256")
            selection_job["selectedCandidate"] = winner.get("candidateIndex")
            selection_job["selectedSeed"] = winner.get("seed")
            shot["selectedCandidate"] = winner.get("candidateIndex")
            shot["selectedSeed"] = winner.get("seed")
            for project_shot in [as_map(item, "project shot") for item in as_list(project.get("shots"), "project.shots")]:
                if project_shot.get("id") == shot_id:
                    project_shot["selectedCandidate"] = winner.get("candidateIndex")
                    project_shot["selectedSeed"] = winner.get("seed")
            if winner.get("decision") == "review":
                selected_for_review += 1
            selections.append(
                {
                    "shotId": shot_id,
                    "selectedCandidate": winner.get("candidateIndex"),
                    "selectedSeed": winner.get("seed"),
                    "selectedSha256": winner_hash,
                    "decision": winner.get("decision"),
                    "score": winner.get("score"),
                    "confidence": winner.get("confidence"),
                    "candidates": evaluated,
                }
            )
        write_json(paths.production, plan)
        add_artifact(paths, project, run, paths.production, "production-plan", "application/json", source="take-selection")
        total_candidates = sum(
            len(as_list(item.get("candidates"), "selection candidates")) for item in selections
        )
        payload: JsonMap = {
            "contractVersion": "mere.run/film-take-selection.v1",
            "projectId": project.get("projectId"),
            "createdAt": now_iso(),
            "sourceDigest": source_digest,
            "selector": {
                "command": "mere.run vision inspect",
                "model": inspector_model,
                "profile": "canon-aware-contact-sheet-v1",
            },
            "summary": {
                "shots": len(selections),
                "candidates": total_candidates,
                "selectedForReview": selected_for_review,
            },
            "shots": selections,
        }
        write_json(receipt_path, payload)
        add_artifact(paths, project, run, receipt_path, "take-selection", "application/json", source="mere.run-vision")
        if selected_for_review:
            set_issue(
                project,
                "take-selection-findings",
                f"The best local take for {selected_for_review} shot(s) still needs independent creative review.",
                False,
            )
        else:
            clear_issue(project, "take-selection-findings")
        clear_issue(project, "take-selection-failed")
        history(
            project,
            "takes-selected",
            f"Scored {total_candidates} candidates and selected canon for {len(selections)} shots.",
        )
        save(paths, project, run)
        return receipt_path
    except Exception as exc:
        for item in jobs(project):
            if item.get("kind") == "take-selection" and item.get("status") == "running":
                item["status"] = "failed"
                item["failedAt"] = now_iso()
                item["error"] = str(exc)
        project["status"] = "failed"
        set_issue(project, "take-selection-failed", str(exc), True)
        save(paths, project, run)
        raise


def inspect_generated_media(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    timeout_seconds: int,
) -> pathlib.Path | None:
    if not media_inspection_enabled(project):
        as_map(project.get("proof"), "project.proof")["inspection"] = False
        set_issue(
            project,
            "media-inspection-disabled",
            "Local generated-media inspection is disabled; creative reviewers will receive frames without a local vision receipt.",
            False,
        )
        save(paths, project, run)
        return None
    plan = production_plan(paths)
    receipt_path = paths.reviews / "media-inspection.json"
    source_digest = inspection_source_digest(paths, plan)
    if receipt_path.is_file() and matching_artifact(paths, project, receipt_path, "media-inspection"):
        cached = load_json(receipt_path)
        if cached.get("sourceDigest") == source_digest:
            as_map(project.get("proof"), "project.proof")["inspection"] = True
            return receipt_path
    if receipt_path.is_file():
        archive_unverified_output(paths, project, run, receipt_path, "media-inspection")
    directory = paths.reviews / "inspection-frames"
    directory.mkdir(parents=True, exist_ok=True)
    inspector_model = as_string(model_config(project).get("visionInspector"), "models.visionInspector")
    results: list[JsonMap] = []
    try:
        for shot in shot_items(plan):
            shot_id = as_string(shot.get("id"), "shot.id")
            clip = clip_output(paths, shot_id)
            output = directory / f"{slug(shot_id)}.png"
            duration = as_number(shot.get("durationSeconds"), f"shot {shot_id}.durationSeconds")
            extract_contact_sheet(
                paths=paths,
                project=project,
                run=run,
                source=clip,
                output=output,
                duration_seconds=duration,
                artifact_kind="inspection-frame",
                log_name=f"inspection-frame-{shot_id}",
            )
            result = run_vision_json(
                paths=paths,
                project=project,
                image=output,
                prompt=inspection_prompt(plan, shot),
                max_tokens=700,
                log_name=f"inspect-{shot_id}",
                timeout_seconds=timeout_seconds,
                parser=partial(parse_inspection_response, shot_id=shot_id),
            )
            results.append(
                {
                    "shotId": shot_id,
                    "frame": str(output.relative_to(paths.root)),
                    "frameSha256": file_sha256(output),
                    "decision": result.get("decision"),
                    "observations": result.get("observations"),
                    "mismatches": result.get("mismatches"),
                    "confidence": result.get("confidence"),
                }
            )
        review_count = sum(1 for item in results if item.get("decision") == "review")
        payload: JsonMap = {
            "contractVersion": "mere.run/film-media-inspection.v1",
            "projectId": project.get("projectId"),
            "createdAt": now_iso(),
            "sourceDigest": source_digest,
            "inspector": {
                "command": "mere.run vision inspect",
                "model": inspector_model,
                "samplingProfile": "early-mid-late-contact-sheet-v1",
            },
            "complete": len(results) == len(shot_items(plan)),
            "summary": {"shots": len(results), "passed": len(results) - review_count, "review": review_count},
            "shots": results,
        }
        write_json(receipt_path, payload)
        add_artifact(
            paths,
            project,
            run,
            receipt_path,
            "media-inspection",
            "application/json",
            source="mere.run-vision",
        )
        as_map(project.get("proof"), "project.proof")["inspection"] = True
        clear_issue(project, "media-inspection-failed")
        clear_issue(project, "media-inspection-disabled")
        if review_count:
            set_issue(
                project,
                "media-inspection-findings",
                f"Local vision marked {review_count} of {len(results)} shots for independent creative review.",
                False,
            )
        else:
            clear_issue(project, "media-inspection-findings")
        history(
            project,
            "generated-media-inspected",
            f"Local vision inspected {len(results)} generated shot frames; {review_count} require reviewer attention.",
        )
        save(paths, project, run)
        return receipt_path
    except Exception as exc:
        as_map(project.get("proof"), "project.proof")["inspection"] = False
        set_issue(project, "media-inspection-failed", str(exc), True)
        project["status"] = "failed"
        save(paths, project, run)
        raise


def current_review_binding(paths: ProjectPaths, project: JsonMap) -> JsonMap:
    rough_cut = paths.cuts / "rough-cut.mp4"
    if not rough_cut.is_file():
        raise PluginError("rough cut is missing; cannot bind a human review decision", 2)
    evidence_paths = {
        "technicalReview": paths.reviews / "technical-qc.json",
        "dialogueQc": paths.reviews / "dialogue-qc.json",
        "soundQc": paths.reviews / "sound-qc.json",
        "captions": paths.captions / "captions.json",
        "mediaInspection": paths.reviews / "media-inspection.json",
        "creativeReview": paths.reviews / "creative-review.json",
        "takeSelection": paths.reviews / "take-selection.json",
    }
    hashes = {
        name: file_sha256(path)
        for name, path in evidence_paths.items()
        if path.is_file()
    }
    payload: JsonMap = {
        "projectId": project.get("projectId"),
        "masterSha256": file_sha256(rough_cut),
        "evidence": hashes,
    }
    payload["reviewEvidenceDigest"] = object_sha256(payload)
    return payload


def record_human_review_decision(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    decision_payload: JsonMap,
) -> JsonMap:
    if gate(project, "picture-lock").get("status") == "approved":
        raise PluginError("picture lock is already approved; reroll to create a new review cycle", 2)
    binding = current_review_binding(paths, project)
    contract = as_string(decision_payload.get("contractVersion"), "human review.contractVersion")
    if contract != "mere.run/film-human-review.v1":
        raise PluginError(f"unsupported human review contract: {contract}", 2)
    if decision_payload.get("projectId") != project.get("projectId"):
        raise PluginError("human review projectId does not match this film", 2)
    if decision_payload.get("masterSha256") != binding.get("masterSha256"):
        raise PluginError("human review is bound to a different rough cut", 2)
    if decision_payload.get("reviewEvidenceDigest") != binding.get("reviewEvidenceDigest"):
        raise PluginError("human review is bound to stale or incomplete review evidence", 2)
    decision = as_string(decision_payload.get("decision"), "human review.decision")
    if decision not in {"approve", "revise"}:
        raise PluginError("human review decision must be approve or revise", 2)
    reviewer = as_string(decision_payload.get("reviewer"), "human review.reviewer").strip()
    if not reviewer:
        raise PluginError("human review.reviewer cannot be blank", 2)
    notes = str(decision_payload.get("notes") or "").strip()
    rerolls = as_list(decision_payload.get("rerolls", []), "human review.rerolls")
    known_shots = {
        as_string(item.get("id"), "project shot.id")
        for item in [as_map(raw, "project shot") for raw in as_list(project.get("shots"), "project.shots")]
    }
    normalized_rerolls: list[JsonMap] = []
    for index, raw in enumerate(rerolls, start=1):
        item = as_map(raw, f"human review.rerolls[{index}]")
        shot_id = as_string(item.get("shotId"), f"human review.rerolls[{index}].shotId")
        note = as_string(item.get("note"), f"human review.rerolls[{index}].note").strip()
        if not note:
            raise PluginError(f"human review.rerolls[{index}].note cannot be blank", 2)
        if shot_id not in known_shots:
            raise PluginError(f"human review references unknown shot {shot_id}", 2)
        normalized_rerolls.append({"shotId": shot_id, "note": note})
    if decision == "approve" and normalized_rerolls:
        raise PluginError("an approval cannot also request shot rerolls", 2)
    if decision == "revise" and not notes and not normalized_rerolls:
        raise PluginError("a revision decision requires notes or at least one shot reroll", 2)
    required_evidence = {
        "technicalReview",
        "dialogueQc",
        "soundQc",
        "captions",
        "mediaInspection",
        "creativeReview",
    }
    evidence = as_map(binding.get("evidence"), "review binding.evidence")
    missing = sorted(required_evidence.difference(evidence))
    if missing:
        raise PluginError(f"human review is missing current evidence: {', '.join(missing)}", 2)
    technical = load_json(paths.reviews / "technical-qc.json")
    creative = load_json(paths.reviews / "creative-review.json")
    if decision == "approve" and (technical.get("passed") is not True or creative.get("decision") != "pass"):
        raise PluginError("human approval requires passing technical and independent creative review", 2)
    payload: JsonMap = {
        "contractVersion": "mere.run/film-human-review.v1",
        "projectId": project.get("projectId"),
        "createdAt": now_iso(),
        "recordedAt": now_iso(),
        "reviewer": reviewer,
        "decision": decision,
        "notes": notes,
        "rerolls": normalized_rerolls,
        "masterSha256": binding.get("masterSha256"),
        "reviewEvidenceDigest": binding.get("reviewEvidenceDigest"),
        "evidence": evidence,
    }
    output = paths.reviews / "human-review.json"
    if output.is_file():
        archive_unverified_output(paths, project, run, output, "human-review")
    write_json(output, payload)
    add_artifact(paths, project, run, output, "human-review", "application/json", source="explicit-human-decision")
    proof = as_map(project.get("proof"), "project.proof")
    proof["humanReview"] = decision == "approve"
    review_requests = as_list(project.setdefault("reviewRequests", []), "project.reviewRequests")
    review_requests.clear()
    if decision == "revise":
        review_requests.extend(
            {
                "shotId": item.get("shotId"),
                "note": item.get("note"),
                "status": "pending",
                "recordedAt": payload.get("recordedAt"),
            }
            for item in normalized_rerolls
        )
    if decision == "approve":
        project["status"] = "awaiting-approval"
        clear_issue(project, "human-review-revision")
        history(project, "human-review-approved", f"{reviewer} accepted the current cut and evidence for picture lock.")
    else:
        project["status"] = "revision-required"
        set_issue(
            project,
            "human-review-revision",
            f"{reviewer} requested revision; {len(normalized_rerolls)} targeted shot reroll(s) recorded.",
            True,
        )
        history(project, "human-review-revision", f"{reviewer} requested revision before picture lock.")
    save(paths, project, run)
    return payload


def prepare_review_package(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> pathlib.Path:
    rough_cut = paths.cuts / "rough-cut.mp4"
    if not rough_cut.is_file():
        raise PluginError("rough cut is missing; cannot prepare review package", 2)
    plan = production_plan(paths)
    technical_path = paths.reviews / "technical-qc.json"
    dialogue_path = paths.reviews / "dialogue-qc.json"
    sound_path = paths.reviews / "sound-qc.json"
    inspection_path = paths.reviews / "media-inspection.json"
    creative_path = paths.reviews / "creative-review.json"
    selection_path = paths.reviews / "take-selection.json"
    captions_path = paths.captions / "captions.json"
    technical = load_json(technical_path) if technical_path.is_file() else {}
    dialogue = load_json(dialogue_path) if dialogue_path.is_file() else {}
    sound = load_json(sound_path) if sound_path.is_file() else {}
    inspection = load_json(inspection_path) if inspection_path.is_file() else {}
    creative = load_json(creative_path) if creative_path.is_file() else {}
    selection = load_json(selection_path) if selection_path.is_file() else {}
    captions = load_json(captions_path) if captions_path.is_file() else {}
    dialogue_summary = as_map(dialogue.get("summary", {}), "dialogue summary")
    sound_summary = as_map(sound.get("summary", {}), "sound summary")
    inspection_summary = as_map(inspection.get("summary", {}), "inspection summary")
    captions_summary = as_map(captions.get("summary", {}), "captions summary")
    inspections = {
        str(item.get("shotId")): item
        for item in as_list(inspection.get("shots", []), "inspection shots")
        if isinstance(item, dict)
    }
    selections = {
        str(item.get("shotId")): item
        for item in as_list(selection.get("shots", []), "take selection shots")
        if isinstance(item, dict)
    }
    shot_cards: list[str] = []
    for shot in shot_items(plan):
        shot_id = as_string(shot.get("id"), "shot.id")
        result = as_map(inspections.get(shot_id, {}), f"inspection {shot_id}")
        take_result = as_map(selections.get(shot_id, {}), f"take selection {shot_id}")
        frame_value = optional_string(result.get("frame"))
        frame_href = f"../{html.escape(frame_value)}" if frame_value else ""
        mismatches = [
            as_map(item, "inspection mismatch")
            for item in as_list(result.get("mismatches", []), f"inspection {shot_id}.mismatches")
            if isinstance(item, dict)
        ]
        findings = "".join(
            f"<li><strong>{html.escape(str(item.get('severity') or 'review'))}</strong> "
            f"{html.escape(str(item.get('message') or item.get('code') or 'Unspecified finding'))}</li>"
            for item in mismatches
        ) or "<li>No local vision mismatches recorded.</li>"
        take_score = take_result.get("score") if "score" in take_result else "single-take"
        image = f'<img src="{frame_href}" alt="Inspection frame for {html.escape(shot_id)}">' if frame_href else ""
        shot_cards.append(
            '<article class="shot">'
            f"{image}<div><p class=eyebrow>{html.escape(shot_id)}</p>"
            f"<h3>{html.escape(str(shot.get('purpose') or 'Untitled shot'))}</h3>"
            f"<p><span class=decision>{html.escape(str(result.get('decision') or 'pending'))}</span> "
            f"confidence {html.escape(str(result.get('confidence') or 'n/a'))}</p>"
            f"<p>Selected candidate {html.escape(str(take_result.get('selectedCandidate') or 1))} "
            f"of {html.escape(str(len(as_list(take_result.get('candidates', []), 'take candidates')) or 1))} · "
            f"score {html.escape(str(take_score))}</p>"
            f"<ul>{findings}</ul></div></article>"
        )
    title = html.escape(str(project.get("title") or "Film review"))
    created = html.escape(now_iso())
    binding = current_review_binding(paths, project)
    caption_files = as_map(captions.get("files", {}), "caption files")
    vtt_entry = as_map(caption_files.get("vtt", {}), "caption vtt")
    vtt_value = optional_string(vtt_entry.get("path"))
    caption_track = (
        f'<track kind="captions" src="../{html.escape(vtt_value)}" srclang="{html.escape(str(captions.get("language") or "en"))}" label="Captions">'
        if vtt_value
        else ""
    )
    evidence_links = [
        '<a href="technical-qc.json">Technical JSON</a>',
        '<a href="dialogue-qc.json">Dialogue JSON</a>',
        '<a href="sound-qc.json">Sound JSON</a>',
        '<a href="media-inspection.json">Visual inspection JSON</a>',
        '<a href="creative-review.json">Critic JSON</a>',
    ]
    if selection_path.is_file():
        evidence_links.append('<a href="take-selection.json">Take selection JSON</a>')
    if captions_path.is_file():
        evidence_links.append('<a href="../captions/captions.json">Caption JSON</a>')
    binding_json = json.dumps(binding, separators=(",", ":"), sort_keys=True).replace("<", "\\u003c")
    review_controls = "".join(
        '<label class="reroll"><input type="checkbox" data-shot="'
        + html.escape(as_string(shot.get("id"), "shot.id"))
        + '"> Reroll '
        + html.escape(as_string(shot.get("id"), "shot.id"))
        + '<input type="text" data-note="'
        + html.escape(as_string(shot.get("id"), "shot.id"))
        + '" placeholder="What must change?"></label>'
        for shot in shot_items(plan)
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — picture-lock review</title>
<style>
:root{{--ink:#eef3f8;--muted:#9badbd;--panel:#111a22;--line:#263746;--accent:#ffb457;--bg:#081017}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 20% 0,#18303d 0,var(--bg) 42%);color:var(--ink);font:16px/1.5 ui-sans-serif,system-ui,sans-serif}}
main{{width:min(1180px,92vw);margin:0 auto;padding:56px 0 96px}}.eyebrow{{color:var(--accent);font-size:.72rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase}}
h1{{font-size:clamp(2.4rem,6vw,5.6rem);line-height:.94;margin:.2em 0}}.lede{{max-width:720px;color:var(--muted);font-size:1.08rem}}
video{{width:100%;margin:36px 0 20px;border:1px solid var(--line);border-radius:18px;background:#000;box-shadow:0 24px 80px #0008}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0 48px}}.metric,.shot{{background:#111a22dd;border:1px solid var(--line);border-radius:14px}}
.metric{{padding:18px}}.metric strong{{display:block;font-size:1.55rem}}.metric span{{color:var(--muted)}}h2{{margin-top:52px}}
.shots{{display:grid;gap:16px}}.shot{{display:grid;grid-template-columns:minmax(220px,42%) 1fr;overflow:hidden}}.shot img{{width:100%;height:100%;min-height:220px;object-fit:cover}}.shot>div{{padding:24px}}
.shot h3{{margin:.15em 0}}.shot ul{{padding-left:1.1em;color:var(--muted)}}.decision{{display:inline-block;padding:.2em .6em;border:1px solid var(--accent);border-radius:999px;color:var(--accent);font-weight:700}}
.gate{{margin-top:48px;padding:24px;border-left:4px solid var(--accent);background:#111a22}}a{{color:var(--accent)}}
.decision-form{{display:grid;gap:14px;margin-top:22px}}.decision-form input,.decision-form textarea{{width:100%;padding:11px;border:1px solid var(--line);border-radius:8px;background:#081017;color:var(--ink)}}
.decision-form button{{padding:12px 16px;border:1px solid var(--accent);border-radius:8px;background:var(--accent);color:#111;font-weight:800;cursor:pointer}}.decision-form button.secondary{{background:transparent;color:var(--accent)}}
.reroll{{display:grid;grid-template-columns:auto 110px 1fr;align-items:center;gap:10px;color:var(--muted)}}.reroll input[type=checkbox]{{width:auto}}
@media(max-width:720px){{.metrics{{grid-template-columns:1fr}}.shot{{grid-template-columns:1fr}}}}
</style></head><body><main>
<p class="eyebrow">Mere Film Studio · local review package</p><h1>{title}</h1>
<p class="lede">Watch the assembled cut, then inspect the independent technical, speech, and visual evidence. Generated {created}. This page is local and self-contained; no media is uploaded by the plugin.</p>
<video controls preload="metadata" src="../cuts/rough-cut.mp4">{caption_track}</video>
<section class="metrics">
<div class="metric"><strong>{'PASS' if technical.get('passed') is True else 'PENDING'}</strong><span>technical QC</span></div>
<div class="metric"><strong>{html.escape(str(dialogue_summary.get('lines', 0)))}</strong><span>dialogue lines · {html.escape(str(captions_summary.get('cues', 0)))} captions · {html.escape(str(sound_summary.get('cues', 0)))} SFX cues</span></div>
<div class="metric"><strong>{html.escape(str(inspection_summary.get('shots', 0)))}</strong><span>shots inspected · {html.escape(str(inspection_summary.get('review', 0)))} flagged</span></div>
<div class="metric"><strong>{html.escape(str(creative.get('decision') or 'PENDING')).upper()}</strong><span>independent critic verdict</span></div>
</section><h2>Shot evidence</h2><section class="shots">{''.join(shot_cards)}</section>
<div class="gate"><strong>Human gate:</strong> local checks and AI critics are evidence, not approval. Watch the master before explicitly granting picture lock.<br>
{' · '.join(evidence_links)}
<section class="decision-form"><h2>Record your decision</h2>
<input id="reviewer" placeholder="Reviewer name" autocomplete="name"><textarea id="notes" rows="4" placeholder="Overall notes"></textarea>
{review_controls}
<div><button id="approve">Download approval</button> <button class="secondary" id="revise">Download revision request</button></div>
<small>The downloaded JSON is hash-bound to this exact master and evidence set. Import it with <code>mere-film-tools review-decision … --input decision.json</code>.</small>
</section></div>
<script>
const binding={binding_json};
function downloadDecision(decision){{
  const reviewer=document.querySelector('#reviewer').value.trim();
  if(!reviewer){{alert('Enter the reviewer name.');return;}}
  const rerolls=[...document.querySelectorAll('[data-shot]:checked')].map(box=>{{
    const shotId=box.dataset.shot; const note=document.querySelector(`[data-note="${{shotId}}"]`).value.trim();
    return {{shotId,note}};
  }}).filter(item=>item.note);
  const notes=document.querySelector('#notes').value.trim();
  if(decision==='approve'&&rerolls.length){{alert('Clear reroll requests before approving.');return;}}
  if(decision==='revise'&&!notes&&!rerolls.length){{alert('Add revision notes or a shot reroll.');return;}}
  const payload={{contractVersion:'mere.run/film-human-review.v1',projectId:binding.projectId,
    masterSha256:binding.masterSha256,reviewEvidenceDigest:binding.reviewEvidenceDigest,
    decision,reviewer,notes,rerolls,createdAt:new Date().toISOString()}};
  const blob=new Blob([JSON.stringify(payload,null,2)+'\\n'],{{type:'application/json'}});
  const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download=`${{binding.projectId}}-review-decision.json`;
  link.click();URL.revokeObjectURL(link.href);
}}
document.querySelector('#approve').addEventListener('click',()=>downloadDecision('approve'));
document.querySelector('#revise').addEventListener('click',()=>downloadDecision('revise'));
</script></main></body></html>"""
    output = paths.reviews / "index.html"
    write_text(output, page)
    add_artifact(paths, project, run, output, "review-package", "text/html")
    history(project, "review-package-prepared", "Prepared the local picture-lock player and evidence dashboard.")
    save(paths, project, run)
    return output


def validate_picture_lock_evidence(paths: ProjectPaths, project: JsonMap) -> JsonMap:
    proof = as_map(project.get("proof"), "project.proof")
    required_proof = (
        "clips",
        "assembly",
        "dialogue",
        "sound",
        "captions",
        "inspection",
        "review",
        "humanReview",
    )
    missing_proof = [key for key in required_proof if not bool(proof.get(key))]
    if missing_proof:
        raise PluginError(f"picture lock is missing proof: {', '.join(missing_proof)}", 2)
    rough_cut = paths.cuts / "rough-cut.mp4"
    technical_path = paths.reviews / "technical-qc.json"
    dialogue_path = paths.reviews / "dialogue-qc.json"
    sound_path = paths.reviews / "sound-qc.json"
    inspection_path = paths.reviews / "media-inspection.json"
    creative_path = paths.reviews / "creative-review.json"
    review_package = paths.reviews / "index.html"
    human_review_path = paths.reviews / "human-review.json"
    captions_path = paths.captions / "captions.json"
    caption_sidecars = [*sorted(paths.captions.glob("subtitles.*.srt")), *sorted(paths.captions.glob("subtitles.*.vtt"))]
    if len(caption_sidecars) != 2:
        raise PluginError("picture lock requires exactly one current SRT and WebVTT caption sidecar", 2)
    required_files = (
        rough_cut,
        technical_path,
        dialogue_path,
        sound_path,
        captions_path,
        inspection_path,
        creative_path,
        review_package,
        human_review_path,
        *caption_sidecars,
    )
    missing_files = [str(path.relative_to(paths.root)) for path in required_files if not path.is_file()]
    if missing_files:
        raise PluginError(f"picture lock is missing current evidence files: {', '.join(missing_files)}", 2)
    technical = load_json(technical_path)
    technical_master = as_map(technical.get("master"), "technical review.master")
    dialogue = load_json(dialogue_path)
    sound = load_json(sound_path)
    captions = load_json(captions_path)
    inspection = load_json(inspection_path)
    creative = load_json(creative_path)
    human_review = load_json(human_review_path)
    current_master_hash = file_sha256(rough_cut)
    if technical.get("passed") is not True or technical_master.get("sha256") != current_master_hash:
        raise PluginError("technical QC does not pass against the current rough cut", 2)
    if (
        dialogue.get("complete") is not True
        or sound.get("complete") is not True
        or captions.get("complete") is not True
        or inspection.get("complete") is not True
    ):
        raise PluginError("dialogue, sound, caption, and generated-media inspection receipts must be complete", 2)
    if creative.get("decision") != "pass":
        raise PluginError("independent creative review has not recommended picture lock", 2)
    binding = current_review_binding(paths, project)
    if (
        human_review.get("decision") != "approve"
        or human_review.get("masterSha256") != binding.get("masterSha256")
        or human_review.get("reviewEvidenceDigest") != binding.get("reviewEvidenceDigest")
    ):
        raise PluginError("explicit human review approval is missing or stale", 2)
    artifacts: list[tuple[pathlib.Path, str]] = [
        (technical_path, "technical-review"),
        (dialogue_path, "dialogue-qc"),
        (sound_path, "sound-qc"),
        (captions_path, "caption-receipt"),
        (inspection_path, "media-inspection"),
        (creative_path, "creative-review"),
        (review_package, "review-package"),
        (human_review_path, "human-review"),
    ]
    artifacts.extend(
        (path, "subtitle-srt" if path.suffix == ".srt" else "subtitle-vtt")
        for path in caption_sidecars
    )
    stale = [kind for path, kind in artifacts if not matching_artifact(paths, project, path, kind)]
    if stale:
        raise PluginError(f"picture-lock evidence has unverified changes: {', '.join(stale)}", 2)
    return {
        "masterSha256": current_master_hash,
        "reviewPackageSha256": file_sha256(review_package),
        "technicalReviewSha256": file_sha256(technical_path),
        "dialogueQcSha256": file_sha256(dialogue_path),
        "soundQcSha256": file_sha256(sound_path),
        "captionsSha256": file_sha256(captions_path),
        "mediaInspectionSha256": file_sha256(inspection_path),
        "creativeReviewSha256": file_sha256(creative_path),
        "humanReviewSha256": file_sha256(human_review_path),
    }


def prepare_delivery(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> JsonMap:
    if gate(project, "picture-lock").get("status") != "approved":
        raise PluginError("picture-lock gate is not approved", 2)
    source = paths.cuts / "rough-cut.mp4"
    if not source.is_file():
        raise PluginError("locked rough cut is missing", 2)
    picture_lock = gate(project, "picture-lock")
    if picture_lock.get("masterSha256") != file_sha256(source):
        raise PluginError("rough cut changed after picture lock; rerun review before delivery", 2)
    review_package = paths.reviews / "index.html"
    if not review_package.is_file() or picture_lock.get("reviewPackageSha256") != file_sha256(review_package):
        raise PluginError("review package changed after picture lock; rerun review before delivery", 2)
    human_review = paths.reviews / "human-review.json"
    if not human_review.is_file() or picture_lock.get("humanReviewSha256") != file_sha256(human_review):
        raise PluginError("human review decision changed after picture lock; rerun review before delivery", 2)
    master = paths.delivery / f"{slug(str(project.get('title') or 'film'))}-master.mp4"
    master.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, master)
    technical = load_json(paths.reviews / "technical-qc.json")
    technical_master = as_map(technical.get("master"), "technical review.master")
    midpoint = as_number(technical_master.get("durationSeconds"), "technical review.master.durationSeconds") / 2
    marketing_assets: list[JsonMap] = []
    for label, filename, video_filter in (
        (
            "poster",
            f"{slug(str(project.get('title') or 'film'))}-poster.jpg",
            "scale=1200:-2:flags=lanczos",
        ),
        (
            "thumbnail",
            f"{slug(str(project.get('title') or 'film'))}-thumbnail.jpg",
            "scale=1280:720:force_original_aspect_ratio=increase:flags=lanczos,crop=1280:720",
        ),
    ):
        still = paths.delivery / filename
        command = [
            command_value(project, "ffmpeg"),
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{midpoint:.3f}",
            "-i",
            str(source),
            "-vf",
            video_filter,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(still),
        ]
        run_child(command, paths.root, paths.logs / "media" / f"delivery-{label}.log", 300)
        if not still.is_file() or still.stat().st_size == 0:
            raise PluginError(f"delivery {label} extraction did not produce {still}")
        add_artifact(paths, project, run, still, f"delivery-{label}", "image/jpeg", source="picture-lock")
        marketing_assets.append(
            {
                "kind": label,
                "path": str(still.relative_to(paths.root)),
                "sha256": file_sha256(still),
                "bytes": still.stat().st_size,
                "sourceTimeSeconds": round(midpoint, 3),
            }
        )
    caption_receipt_path = paths.captions / "captions.json"
    caption_receipt = load_json(caption_receipt_path)
    delivered_captions: list[JsonMap] = []
    for kind in ("srt", "vtt"):
        entry = as_map(as_map(caption_receipt.get("files"), "captions.files").get(kind), f"captions.files.{kind}")
        caption_source = paths.root / as_string(entry.get("path"), f"captions.files.{kind}.path")
        if not caption_source.is_file() or file_sha256(caption_source) != entry.get("sha256"):
            raise PluginError(f"locked {kind.upper()} caption sidecar is missing or changed", 2)
        caption_target = paths.delivery / f"{slug(str(project.get('title') or 'film'))}.{caption_receipt.get('language')}.{kind}"
        shutil.copy2(caption_source, caption_target)
        delivered_captions.append(
            {
                "kind": kind,
                "path": str(caption_target.relative_to(paths.root)),
                "sha256": file_sha256(caption_target),
                "bytes": caption_target.stat().st_size,
            }
        )
    manifest: JsonMap = {
        "contractVersion": "mere.run/film-delivery.v1",
        "projectId": project.get("projectId"),
        "title": project.get("title"),
        "createdAt": now_iso(),
        "master": {
            "path": str(master.relative_to(paths.root)),
            "sha256": file_sha256(master),
            "bytes": master.stat().st_size,
        },
        "sourceCut": {
            "path": str(source.relative_to(paths.root)),
            "sha256": file_sha256(source),
        },
        "captions": delivered_captions,
        "marketingAssets": marketing_assets,
        "projectManifest": str(paths.project.relative_to(paths.root)),
        "productionPlan": str(paths.production.relative_to(paths.root)),
        "reviews": [str(path.relative_to(paths.root)) for path in sorted(paths.reviews.glob("*.json"))],
        "reviewPackage": (
            {
                "path": str((paths.reviews / "index.html").relative_to(paths.root)),
                "sha256": file_sha256(paths.reviews / "index.html"),
            }
            if (paths.reviews / "index.html").is_file()
            else None
        ),
        "provenance": {
            "artifactCount": len(as_list(project.get("artifacts"), "project.artifacts")),
            "runManifest": str(paths.run.relative_to(paths.root)),
        },
    }
    manifest_path = paths.delivery / "delivery-manifest.json"
    write_json(manifest_path, manifest)
    add_artifact(paths, project, run, master, "final-master", "video/mp4", source="picture-lock")
    for item in delivered_captions:
        caption_target = paths.root / as_string(item.get("path"), "delivery caption.path")
        add_artifact(
            paths,
            project,
            run,
            caption_target,
            f"delivery-caption-{item.get('kind')}",
            "application/x-subrip" if item.get("kind") == "srt" else "text/vtt",
            source="picture-lock",
        )
    add_artifact(paths, project, run, manifest_path, "delivery-manifest", "application/json")
    as_map(project.get("proof"), "project.proof")["delivery"] = True
    project["phase"] = "delivery"
    set_gate_pending(project, "delivery", "Final master and checksum-backed delivery manifest are ready.")
    history(project, "delivery-prepared", "Copied the locked master and wrote its provenance manifest.")
    save(paths, project, run)
    return manifest


def archive_for_reroll(paths: ProjectPaths, project: JsonMap, run: JsonMap, shot_id: str, note: str) -> JsonMap:
    plan = production_plan(paths)
    shot = next((item for item in shot_items(plan) if item.get("id") == shot_id), None)
    if not shot:
        raise PluginError(f"unknown shot: {shot_id}", 2)
    take = as_int(shot.get("take", 1), "shot.take")
    archive = paths.root / "takes" / slug(shot_id) / f"take-{take:03d}"
    archive.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    shot_sources = (
        (frame_output(paths, shot_id), pathlib.Path("frames")),
        (clip_output(paths, shot_id), pathlib.Path("clips")),
        (paths.blocks / f"{slug(shot_id)}.mp4", pathlib.Path("blocks")),
        (paths.blocks / f"{slug(shot_id)}.json", pathlib.Path("blocks")),
    )
    for source, relative_parent in shot_sources:
        if source.is_file():
            target = archive / relative_parent / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            remove_artifact(paths, project, run, source)
            shutil.move(str(source), target)
            moved.append(str(target.relative_to(paths.root)))
            add_artifact(paths, project, run, target, "archived-take", "application/octet-stream", source="reroll-archive")
    candidate_directory = paths.clips / "candidates" / slug(shot_id)
    for source in sorted(candidate_directory.glob("*.mp4")):
        target = archive / "clips" / "candidates" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        remove_artifact(paths, project, run, source)
        shutil.move(str(source), target)
        moved.append(str(target.relative_to(paths.root)))
        add_artifact(paths, project, run, target, "archived-take", "video/mp4", source="reroll-archive")
    timeline_sources = [paths.cuts / "rough-cut.mp4"]
    timeline_sources.extend(path for path in paths.reviews.rglob("*") if path.is_file())
    timeline_sources.extend(path for path in paths.captions.rglob("*") if path.is_file())
    timeline_sources.extend(path for path in paths.delivery.rglob("*") if path.is_file())
    for source in timeline_sources:
        relative = source.relative_to(paths.root)
        target = archive / "prior-cut" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        remove_artifact(paths, project, run, source)
        shutil.move(str(source), target)
        moved.append(str(target.relative_to(paths.root)))
        add_artifact(
            paths,
            project,
            run,
            target,
            "archived-cut-evidence",
            "application/octet-stream",
            source="reroll-archive",
        )
    shot["take"] = take + 1
    shot["seed"] = as_int(shot.get("seed", 0), "shot.seed") + 1
    shot.pop("selectedCandidate", None)
    shot.pop("selectedSeed", None)
    for project_shot in [as_map(item, "project shot") for item in as_list(project.get("shots"), "project.shots")]:
        if project_shot.get("id") == shot_id:
            project_shot.update(shot)
            project_shot["status"] = "planned"
    for item in jobs(project):
        if item.get("id") == "assemble-rough-cut" or (
            item.get("subject") == shot_id
            and item.get("kind") in {"keyframe", "clip", "clip-candidate", "take-selection"}
        ):
            item["status"] = "planned"
            for key in ("error", "sha256", "completedAt", "completedSpecSha256", "selectedCandidate", "selectedSeed"):
                item.pop(key, None)
    proof = as_map(project.get("proof"), "project.proof")
    for key in (
        "clips",
        "assembly",
        "dialogue",
        "sound",
        "captions",
        "inspection",
        "review",
        "humanReview",
        "delivery",
    ):
        proof[key] = False
    for gate_name in ("picture-lock", "delivery"):
        approval = gate(project, gate_name)
        approval.clear()
        approval["status"] = "blocked"
    for raw_task in as_list(project.get("departments"), "project.departments"):
        review_task = as_map(raw_task, "department task")
        if review_task.get("phase") != "review":
            continue
        review_task["status"] = "blocked"
        for key in ("proposal", "completedAt", "failedAt", "startedAt", "error", "command"):
            review_task.pop(key, None)
    project["phase"] = "production"
    project["status"] = "planned"
    for raw_request in as_list(project.setdefault("reviewRequests", []), "project.reviewRequests"):
        request = as_map(raw_request, "project review request")
        if request.get("shotId") == shot_id and request.get("status") == "pending":
            request["status"] = "applied"
            request["appliedAt"] = now_iso()
            request["archivedTake"] = take
    write_json(paths.production, plan)
    add_artifact(paths, project, run, paths.production, "production-plan", "application/json", source="reroll-update")
    history(project, "shot-reroll-requested", f"Archived shot {shot_id} take {take}; {note}")
    save(paths, project, run)
    return {"shotId": shot_id, "archived": moved, "nextTake": take + 1, "seed": shot.get("seed")}

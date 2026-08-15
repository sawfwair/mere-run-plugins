from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
from dataclasses import dataclass

from .common import JsonMap, PluginError, as_list, as_map, as_string, now_iso, write_text
from .state import DEPARTMENT_CONTRACT, ProjectPaths

JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
INTERACTIVE_TOOLS = (
    "read",
    "grep",
    "find",
    "ls",
    "film_status",
    "film_update_brief",
    "film_approve",
    "film_configure",
    "film_preflight",
    "film_run",
    "film_recover",
    "film_delegate",
    "film_review",
    "film_record_review_decision",
    "film_reroll",
)


@dataclass(frozen=True)
class PiResult:
    payload: JsonMap
    command: list[str]
    attempts: int
    raw_output: str


def resource_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent / "resources" / "pi"


def role_prompt(role: str) -> str:
    path = resource_root() / "agents" / f"{role}.md"
    if not path.is_file():
        raise PluginError(f"missing bundled Pi role: {role}", 2)
    return path.read_text()


def parse_json_output(text: str) -> JsonMap:
    stripped = text.strip()
    match = JSON_FENCE.fullmatch(stripped)
    if match:
        stripped = match.group(1).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise PluginError(f"Pi returned non-JSON department output: {exc}") from None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as nested:
            raise PluginError(f"Pi returned invalid department JSON: {nested}") from None
    return as_map(value, "Pi department output")


def validate_department_result(payload: JsonMap, task: JsonMap) -> None:
    expected_task = as_string(task.get("id"), "task.id")
    expected_role = as_string(task.get("role"), "task.role")
    expected_phase = as_string(task.get("phase"), "task.phase")
    if payload.get("contractVersion") != DEPARTMENT_CONTRACT:
        raise PluginError(f"Pi result for {expected_task} has the wrong contractVersion")
    if payload.get("taskId") != expected_task:
        raise PluginError(f"Pi result taskId must be {expected_task}")
    if payload.get("role") != expected_role:
        raise PluginError(f"Pi result role must be {expected_role}")
    if payload.get("phase") != expected_phase:
        raise PluginError(f"Pi result phase must be {expected_phase}")
    as_string(payload.get("summary"), "department.summary")
    for key in ("decisions", "risks", "questions"):
        values = as_list(payload.get(key), f"department.{key}")
        if not all(isinstance(value, str) for value in values):
            raise PluginError(f"department.{key} must contain only strings")
    deliverables = as_map(payload.get("deliverables"), "department.deliverables")
    if expected_task == "treatment-synthesis":
        validate_treatment(as_map(deliverables.get("treatment"), "deliverables.treatment"))
    elif expected_task == "production-synthesis":
        validate_production_plan(as_map(deliverables.get("productionPlan"), "deliverables.productionPlan"))
    elif expected_task == "review-synthesis":
        validate_review(as_map(deliverables.get("review"), "deliverables.review"))


def validate_treatment(treatment: JsonMap) -> None:
    for key in ("title", "logline", "synopsis", "theme", "visualLanguage", "soundLanguage"):
        as_string(treatment.get(key), f"treatment.{key}")
    beats = as_list(treatment.get("beats"), "treatment.beats")
    if len(beats) < 3 or not all(isinstance(value, str) for value in beats):
        raise PluginError("treatment.beats must contain at least three strings")


def validate_production_plan(plan: JsonMap) -> None:
    for key in ("title", "scorePrompt"):
        as_string(plan.get(key), f"productionPlan.{key}")
    cast = as_list(plan.get("cast"), "productionPlan.cast")
    locations = as_list(plan.get("locations"), "productionPlan.locations")
    shots = as_list(plan.get("shots"), "productionPlan.shots")
    if not shots:
        raise PluginError("productionPlan.shots must not be empty")
    for label, values in (("cast", cast), ("locations", locations), ("shots", shots)):
        if not all(isinstance(value, dict) for value in values):
            raise PluginError(f"productionPlan.{label} must contain only objects")
    cast_ids: set[str] = set()
    for index, raw in enumerate(cast, start=1):
        person = as_map(raw, f"productionPlan.cast[{index}]")
        cast_id = as_string(person.get("id"), f"cast {index}.id")
        if cast_id in cast_ids:
            raise PluginError(f"duplicate cast id: {cast_id}")
        cast_ids.add(cast_id)
        for key in ("name", "visual", "voice"):
            as_string(person.get(key), f"cast {cast_id}.{key}")
    location_ids: set[str] = set()
    for index, raw in enumerate(locations, start=1):
        location = as_map(raw, f"productionPlan.locations[{index}]")
        location_id = as_string(location.get("id"), f"location {index}.id")
        if location_id in location_ids:
            raise PluginError(f"duplicate location id: {location_id}")
        location_ids.add(location_id)
        for key in ("name", "visual"):
            as_string(location.get(key), f"location {location_id}.{key}")
    seen: set[str] = set()
    for index, raw in enumerate(shots, start=1):
        shot = as_map(raw, f"productionPlan.shots[{index}]")
        shot_id = as_string(shot.get("id"), f"shot {index}.id")
        if shot_id in seen:
            raise PluginError(f"duplicate production shot id: {shot_id}")
        seen.add(shot_id)
        as_string(shot.get("prompt"), f"shot {shot_id}.prompt")
        as_string(shot.get("framePrompt"), f"shot {shot_id}.framePrompt")
        duration = shot.get("durationSeconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise PluginError(f"shot {shot_id}.durationSeconds must be positive")
        characters = as_list(shot.get("characters"), f"shot {shot_id}.characters")
        if not all(isinstance(value, str) for value in characters):
            raise PluginError(f"shot {shot_id}.characters must contain strings")
        unknown_characters = [str(value) for value in characters if value not in cast_ids]
        if unknown_characters:
            raise PluginError(f"shot {shot_id} references unknown cast ids: {', '.join(unknown_characters)}")
        location_id = as_string(shot.get("location"), f"shot {shot_id}.location")
        if location_id not in location_ids:
            raise PluginError(f"shot {shot_id} references unknown location id: {location_id}")
        transition = as_string(shot.get("transition"), f"shot {shot_id}.transition")
        if transition not in {"cut", "fade"}:
            raise PluginError(f"shot {shot_id}.transition must be cut or fade")
        dialogue = as_list(shot.get("dialogue"), f"shot {shot_id}.dialogue")
        for line_index, raw_line in enumerate(dialogue, start=1):
            line = as_map(raw_line, f"shot {shot_id}.dialogue[{line_index}]")
            speaker = as_string(line.get("speaker"), f"shot {shot_id} dialogue {line_index}.speaker")
            if speaker not in characters:
                raise PluginError(f"shot {shot_id} dialogue speaker {speaker} must appear in shot.characters")
            as_string(line.get("text"), f"shot {shot_id} dialogue {line_index}.text")
            as_string(line.get("delivery"), f"shot {shot_id} dialogue {line_index}.delivery")
            start = line.get("startSeconds")
            if not isinstance(start, (int, float)) or isinstance(start, bool) or start < 0 or start >= duration:
                raise PluginError(
                    f"shot {shot_id} dialogue {line_index}.startSeconds must be within the shot duration"
                )
        sound_effects_value = shot.get("soundEffects", [])
        sound_effects = as_list(sound_effects_value, f"shot {shot_id}.soundEffects")
        for cue_index, raw_cue in enumerate(sound_effects, start=1):
            cue = as_map(raw_cue, f"shot {shot_id}.soundEffects[{cue_index}]")
            as_string(cue.get("prompt"), f"shot {shot_id} sound effect {cue_index}.prompt")
            start = cue.get("startSeconds")
            cue_duration = cue.get("durationSeconds")
            level = cue.get("levelDb", -10)
            seed = cue.get("seed")
            if not isinstance(start, (int, float)) or isinstance(start, bool) or start < 0 or start >= duration:
                raise PluginError(f"shot {shot_id} sound effect {cue_index}.startSeconds must be within the shot")
            if (
                not isinstance(cue_duration, (int, float))
                or isinstance(cue_duration, bool)
                or cue_duration <= 0
                or cue_duration > duration
            ):
                raise PluginError(f"shot {shot_id} sound effect {cue_index}.durationSeconds must fit the shot")
            if not isinstance(level, (int, float)) or isinstance(level, bool) or level < -60 or level > 6:
                raise PluginError(f"shot {shot_id} sound effect {cue_index}.levelDb must be between -60 and 6")
            if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool) or seed < 0):
                raise PluginError(f"shot {shot_id} sound effect {cue_index}.seed must be a nonnegative integer")


def validate_review(review: JsonMap) -> None:
    decision = as_string(review.get("decision"), "review.decision")
    if decision not in {"pass", "revise"}:
        raise PluginError("review.decision must be pass or revise")
    issues = as_list(review.get("issues"), "review.issues")
    rerolls = as_list(review.get("rerolls"), "review.rerolls")
    if not all(isinstance(value, dict) for value in issues + rerolls):
        raise PluginError("review issues and rerolls must contain objects")


def expected_contract(task: JsonMap) -> str:
    task_id = as_string(task.get("id"), "task.id")
    base = """
Return exactly one JSON object and nothing else:
{
  "contractVersion": "mere.run/film-department-result.v1",
  "taskId": "TASK_ID",
  "role": "ROLE",
  "phase": "PHASE",
  "summary": "one concise paragraph",
  "decisions": ["specific decision"],
  "deliverables": {},
  "risks": ["specific risk"],
  "questions": ["only unresolved questions that materially change the film"]
}
""".replace("TASK_ID", task_id).replace("ROLE", as_string(task.get("role"), "task.role")).replace(
        "PHASE", as_string(task.get("phase"), "task.phase")
    )
    if task_id == "treatment-synthesis":
        return base + """
deliverables must contain a treatment object with: title, logline, synopsis,
theme, beats (at least three strings), visualLanguage, soundLanguage,
assumptions (array), and openQuestions (array).
"""
    if task_id == "production-synthesis":
        return base + """
deliverables must contain productionPlan with title, scorePrompt, cast,
locations, and shots. Each cast item has id, name, visual, wardrobe, and voice.
Each location has id, name, visual, and ambience. Each shot has a unique
lowercase-hyphen id, purpose, framePrompt, prompt, durationSeconds, seed,
characters (cast ids), location (location id), dialogue (an array of timed line
objects with speaker, text, startSeconds, and delivery), soundEffects (optional
timed cues with prompt, startSeconds, durationSeconds, levelDb, and optional
seed), and transition (`cut` or `fade`, where fade means a short fade-to-black
after the shot).
Keep total shot duration close to the brief target and make every prompt fully
self-contained, cinematic, physical, and usable by local image/video models.
"""
    if task_id == "review-synthesis":
        return base + """
deliverables must contain review with decision (pass or revise), issues (array
of objects with code, severity, message, and shotId when applicable), rerolls
(array of objects with shotId, reason, and direction), strengths (array), and
deliveryNotes (array). Never pass a film whose final playable asset is absent.
Never pass when technical QC, dialogue transcription evidence, or local
generated-media inspection is absent; cite unresolved receipt findings.
"""
    return base


def project_context(paths: ProjectPaths, task: JsonMap) -> str:
    candidates = [paths.brief, paths.treatment, paths.production, paths.project]
    proposal_dir = paths.proposals / as_string(task.get("phase"), "task.phase")
    if bool(task.get("synthesis")) and proposal_dir.is_dir():
        candidates.extend(sorted(proposal_dir.glob("*.json")))
    readable = [str(path) for path in candidates if path.is_file()]
    return "\n".join(f"- {path}" for path in readable)


def invoke_department(
    *,
    paths: ProjectPaths,
    task: JsonMap,
    pi_command: str,
    timeout_seconds: int,
    max_attempts: int = 2,
    extra_context: list[pathlib.Path] | None = None,
) -> PiResult:
    task_id = as_string(task.get("id"), "task.id")
    role = as_string(task.get("role"), "task.role")
    prompt = (
        f"You are the {role} department on film project {paths.root.name}.\n"
        f"Complete task {task_id}. Read the authoritative project files below.\n"
        "Do not edit any project file. The studio plugin alone accepts work into canon.\n\n"
        f"Project files:\n{project_context(paths, task)}\n\n"
        f"{expected_contract(task)}"
    )
    attachments = [path for path in (extra_context or []) if path.is_file()]
    last_error = ""
    last_output = ""
    for attempt in range(1, max_attempts + 1):
        attempt_prompt = prompt
        if last_error:
            attempt_prompt += f"\nYour prior response was rejected: {last_error}\nCorrect it and return the contract only."
        command = [
            pi_command,
            *local_provider_arguments(),
            "--print",
            "--no-session",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
            "--no-approve",
            "--tools",
            "read,grep,find,ls",
            "--system-prompt",
            role_prompt(role),
        ]
        command.extend(f"@{path}" for path in attachments)
        command.append(attempt_prompt)
        log_path = paths.logs / "agents" / f"{task_id}-attempt-{attempt}.txt"
        try:
            process = subprocess.run(
                command,
                cwd=paths.root,
                env=os.environ.copy(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            raise PluginError(f"Pi executable not found: {pi_command}", 3) from None
        except subprocess.TimeoutExpired:
            last_error = f"Pi department task timed out after {timeout_seconds} seconds"
            write_text(log_path, last_error)
            continue
        last_output = process.stdout.strip()
        diagnostic = process.stderr.strip()
        write_text(
            log_path,
            f"command: {' '.join(command[:2])} ...\nexit: {process.returncode}\n\nstdout:\n{last_output}\n\nstderr:\n{diagnostic}",
        )
        if process.returncode != 0:
            last_error = diagnostic or last_output or f"Pi exited {process.returncode}"
            continue
        try:
            payload = parse_json_output(last_output)
            validate_department_result(payload, task)
            payload["recordedAt"] = now_iso()
            return PiResult(payload=payload, command=command, attempts=attempt, raw_output=last_output)
        except PluginError as exc:
            last_error = str(exc)
    raise PluginError(f"Pi department {task_id} failed after {max_attempts} attempts: {last_error}")


def interactive_command(
    *,
    pi_command: str,
    title: str,
    run_manifest: pathlib.Path,
    isolated: bool,
    initial_message: str | None,
) -> list[str]:
    resources = resource_root()
    command = [pi_command, *local_provider_arguments()]
    if isolated:
        command.extend(
            [
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-context-files",
                "--no-approve",
            ]
        )
    command.extend(
        [
            "--tools",
            ",".join(INTERACTIVE_TOOLS),
            "--extension",
            str(resources / "extensions" / "film-studio.ts"),
            "--skill",
            str(resources / "skills" / "film-studio" / "SKILL.md"),
            "--prompt-template",
            str(resources / "prompts" / "film.md"),
            "--name",
            f"Mere Studio: {title}",
            f"@{run_manifest}",
            initial_message
            or "Open this film project. Inspect its status, resolve only material brief questions, and guide me to the next explicit approval gate.",
        ]
    )
    return command


def local_provider_arguments() -> list[str]:
    provider = os.environ.get("MERE_FILM_TOOLS_PI_PROVIDER", "").strip()
    model = os.environ.get("MERE_FILM_TOOLS_PI_MODEL", "").strip()
    if model and not provider:
        raise PluginError("MERE_FILM_TOOLS_PI_MODEL requires MERE_FILM_TOOLS_PI_PROVIDER", 2)
    arguments: list[str] = []
    if provider:
        arguments.extend(["--provider", provider])
    if model:
        arguments.extend(["--model", model])
    return arguments


def interactive_environment(run_manifest: pathlib.Path, plugin_command: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment["MERE_FILM_RUN_MANIFEST"] = str(run_manifest)
    environment["MERE_FILM_TOOLS_COMMAND"] = plugin_command
    return environment


def launch_interactive(
    *,
    paths: ProjectPaths,
    title: str,
    pi_command: str,
    plugin_command: str,
    isolated: bool,
    initial_message: str | None,
) -> int:
    command = interactive_command(
        pi_command=pi_command,
        title=title,
        run_manifest=paths.run,
        isolated=isolated,
        initial_message=initial_message,
    )
    try:
        process = subprocess.run(
            command,
            cwd=paths.root,
            env=interactive_environment(paths.run, plugin_command),
            check=False,
        )
    except FileNotFoundError:
        raise PluginError(f"Pi executable not found: {pi_command}", 3) from None
    return process.returncode

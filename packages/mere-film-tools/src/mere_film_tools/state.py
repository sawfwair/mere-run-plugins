from __future__ import annotations

import pathlib
from dataclasses import dataclass

from .common import (
    JsonMap,
    as_list,
    as_map,
    as_string,
    file_sha256,
    load_json,
    now_iso,
    object_sha256,
    optional_string,
    relative_or_absolute,
    slug,
    write_json,
)

PROJECT_CONTRACT = "mere.run/film-project.v1"
DEPARTMENT_CONTRACT = "mere.run/film-department-result.v1"
PLUGIN_RUN_CONTRACT = "mere.run/plugin-run.v1"
GATES = ("brief", "treatment", "production", "picture-lock", "delivery")
PHASES = ("intake", "development", "preproduction", "production", "postproduction", "review", "delivery", "completed")


@dataclass(frozen=True)
class ProjectPaths:
    root: pathlib.Path
    run: pathlib.Path
    project: pathlib.Path
    brief: pathlib.Path
    treatment: pathlib.Path
    production: pathlib.Path
    proposals: pathlib.Path
    canon: pathlib.Path
    frames: pathlib.Path
    clips: pathlib.Path
    blocks: pathlib.Path
    audio: pathlib.Path
    captions: pathlib.Path
    reviews: pathlib.Path
    cuts: pathlib.Path
    delivery: pathlib.Path
    logs: pathlib.Path


def paths_for_root(root: pathlib.Path, run_manifest: pathlib.Path | None = None) -> ProjectPaths:
    resolved = root.expanduser().resolve()
    return ProjectPaths(
        root=resolved,
        run=(run_manifest or (resolved / "run.json")).expanduser().resolve(),
        project=resolved / "film-project.json",
        brief=resolved / "brief.json",
        treatment=resolved / "treatment.json",
        production=resolved / "production-plan.json",
        proposals=resolved / "proposals",
        canon=resolved / "canon",
        frames=resolved / "frames",
        clips=resolved / "clips",
        blocks=resolved / "blocks",
        audio=resolved / "audio",
        captions=resolved / "captions",
        reviews=resolved / "reviews",
        cuts=resolved / "cuts",
        delivery=resolved / "delivery",
        logs=resolved / "logs",
    )


def paths_from_run(run_path: pathlib.Path, run: JsonMap | None = None) -> ProjectPaths:
    payload = run or load_json(run_path)
    local = as_map(payload.get("local"), "run.local")
    root = pathlib.Path(as_string(local.get("outputDirectory"), "run.local.outputDirectory"))
    return paths_for_root(root, run_path)


def task(task_id: str, role: str, phase: str, dependencies: list[str], synthesis: bool = False) -> JsonMap:
    return {
        "id": task_id,
        "role": role,
        "phase": phase,
        "dependsOn": dependencies,
        "synthesis": synthesis,
        "status": "blocked",
        "attempts": 0,
    }


def department_tasks() -> list[JsonMap]:
    development = [
        task("story-development", "story-editor", "development", []),
        task("visual-development", "production-designer", "development", []),
        task("production-constraints", "line-producer", "development", []),
    ]
    development_ids = [as_string(item["id"], "task.id") for item in development]
    preproduction = [
        task("screenplay", "screenwriter", "preproduction", []),
        task("cinematography", "cinematographer", "preproduction", []),
        task("sound-plan", "sound-designer", "preproduction", []),
        task("continuity-plan", "continuity-supervisor", "preproduction", []),
    ]
    preproduction_ids = [as_string(item["id"], "task.id") for item in preproduction]
    review = [
        task("story-review", "story-critic", "review", []),
        task("edit-review", "edit-critic", "review", []),
        task("continuity-review", "continuity-supervisor", "review", []),
    ]
    review_ids = [as_string(item["id"], "task.id") for item in review]
    return [
        *development,
        task("treatment-synthesis", "director", "development", development_ids, synthesis=True),
        *preproduction,
        task("production-synthesis", "director", "preproduction", preproduction_ids, synthesis=True),
        *review,
        task("review-synthesis", "director", "review", review_ids, synthesis=True),
    ]


def approval_map() -> JsonMap:
    approvals: JsonMap = {}
    for gate in GATES:
        approvals[gate] = {"status": "blocked" if gate != "brief" else "pending"}
    return approvals


def create_brief(
    *,
    title: str,
    idea: str,
    duration_seconds: int,
    width: int,
    height: int,
    fps: int,
    audience: str | None,
    genre: str | None,
    tone: str | None,
    rating: str | None,
    language: str,
    platform: str | None,
    usage: str | None,
    must_haves: list[str],
    exclusions: list[str],
    references: list[str],
) -> JsonMap:
    questions: list[str] = []
    if not audience:
        questions.append("Who is the primary audience?")
    if not genre:
        questions.append("What genre should govern the story grammar?")
    if not tone:
        questions.append("What should the audience feel at the end?")
    if not rating:
        questions.append("What content rating or safety boundary should the film observe?")
    if not references:
        questions.append("Are there visual, cinematic, musical, or pacing references to honor or avoid?")
    if not usage:
        questions.append("Is the intended use personal, noncommercial, or commercial?")
    return {
        "contractVersion": "mere.run/film-brief.v1",
        "title": title,
        "idea": idea,
        "target": {
            "durationSeconds": duration_seconds,
            "width": width,
            "height": height,
            "fps": fps,
            "aspectRatio": f"{width}:{height}",
            "audience": audience or "unspecified",
            "rating": rating or "unspecified",
            "language": language,
            "platform": platform or "master",
            "usage": usage or "unspecified",
        },
        "creative": {
            "genre": genre or "unspecified",
            "tone": tone or "unspecified",
            "mustHaves": must_haves,
            "exclusions": exclusions,
            "references": references,
        },
        "openQuestions": questions,
        "completeness": {
            "readyForGreenlight": not questions,
            "resolvedFields": 6 - len(questions),
            "totalFields": 6,
        },
    }


def create_project(
    *,
    project_id: str,
    title: str,
    idea: str,
    brief: JsonMap,
    production_config: JsonMap,
) -> JsonMap:
    created = now_iso()
    return {
        "contractVersion": PROJECT_CONTRACT,
        "projectId": project_id,
        "title": title,
        "idea": idea,
        "createdAt": created,
        "updatedAt": created,
        "status": "planned",
        "phase": "intake",
        "brief": brief,
        "approvals": approval_map(),
        "departments": department_tasks(),
        "shots": [],
        "reviewRequests": [],
        "jobs": [],
        "production": production_config,
        "artifacts": [],
        "proof": {
            "creation": False,
            "clips": False,
            "assembly": False,
            "dialogue": False,
            "sound": False,
            "captions": False,
            "inspection": False,
            "review": False,
            "humanReview": False,
            "delivery": False,
        },
        "issues": [],
        "history": [
            {
                "at": created,
                "event": "project-planned",
                "detail": "Created durable film project and held at the brief gate.",
            }
        ],
    }


def create_run_manifest(paths: ProjectPaths, run_id: str, project: JsonMap) -> JsonMap:
    created = now_iso()
    digest = object_sha256(project.get("brief"))
    return {
        "contractVersion": PLUGIN_RUN_CONTRACT,
        "runId": run_id,
        "plugin": {"name": "mere-film-tools", "version": "0.1.0"},
        "recipe": {
            "id": "pi-short-film-studio",
            "family": "film-production",
            "title": project.get("title"),
        },
        "status": "planned",
        "createdAt": created,
        "updatedAt": created,
        "dataset": {
            "path": str(paths.root),
            "pairCount": 1,
            "sha256": digest,
        },
        "command": ["mere-film-tools", "run", str(paths.run)],
        "local": {
            "outputDirectory": str(paths.root),
            "runManifest": str(paths.run),
            "projectManifest": str(paths.project),
        },
        "film": {
            "projectId": project.get("projectId"),
            "phase": project.get("phase"),
            "projectManifest": str(paths.project),
        },
        "artifacts": {
            "localDirectory": str(paths.root),
            "files": [str(paths.project), str(paths.brief)],
            "items": [],
            "sha256": {},
        },
        "cleanup": {"default": "none", "status": "not-started"},
    }


def initialize_project(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> None:
    for directory in (
        paths.root,
        paths.proposals,
        paths.canon / "cast",
        paths.canon / "locations",
        paths.frames,
        paths.clips,
        paths.blocks,
        paths.audio,
        paths.captions,
        paths.reviews,
        paths.cuts,
        paths.delivery,
        paths.logs / "agents",
        paths.logs / "media",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    write_json(paths.brief, project["brief"])
    write_json(paths.project, project)
    write_json(paths.run, run)
    add_artifact(paths, project, run, paths.brief, "brief", "application/json")
    save(paths, project, run)


def load_state(run_path: pathlib.Path) -> tuple[ProjectPaths, JsonMap, JsonMap]:
    resolved = run_path.expanduser().resolve()
    run = load_json(resolved)
    paths = paths_from_run(resolved, run)
    project_path = pathlib.Path(
        as_string(as_map(run.get("local"), "run.local").get("projectManifest"), "run.local.projectManifest")
    )
    project = load_json(project_path)
    if project.get("contractVersion") != PROJECT_CONTRACT:
        raise ValueError(f"unsupported film project contract: {project.get('contractVersion')}")
    return paths, project, run


def history(project: JsonMap, event: str, detail: str) -> None:
    as_list(project.setdefault("history", []), "project.history").append(
        {"at": now_iso(), "event": event, "detail": detail}
    )


def recover_interrupted_work(project: JsonMap) -> JsonMap:
    recovered_tasks: list[str] = []
    recovered_jobs: list[str] = []
    recovered_project_status = project.get("status") == "running"
    recovered_at = now_iso()
    for raw in as_list(project.get("departments"), "project.departments"):
        item = as_map(raw, "department task")
        if item.get("status") != "running":
            continue
        task_id = as_string(item.get("id"), "task.id")
        item["status"] = "failed"
        item["failedAt"] = recovered_at
        item["recoveredAt"] = recovered_at
        item["error"] = "Prior process ended while this task was running; safe to resume."
        recovered_tasks.append(task_id)
    for raw in as_list(project.get("jobs"), "project.jobs"):
        item = as_map(raw, "production job")
        if item.get("status") != "running":
            continue
        job_id = as_string(item.get("id"), "job.id")
        item["status"] = "failed"
        item["failedAt"] = recovered_at
        item["recoveredAt"] = recovered_at
        item["error"] = "Prior process ended while this job was running; output will be verified before reuse."
        recovered_jobs.append(job_id)
    if not recovered_tasks and not recovered_jobs and not recovered_project_status:
        return {"recovered": False, "tasks": [], "jobs": [], "projectStatus": False}
    if recovered_project_status:
        project["status"] = "planned"
    detail = (
        f"Recovered {len(recovered_tasks)} interrupted task(s), {len(recovered_jobs)} interrupted job(s), "
        f"and project running state: {str(recovered_project_status).lower()}."
    )
    history(project, "interrupted-work-recovered", detail)
    set_issue(
        project,
        "interrupted-work-recovered",
        detail + " Resume will retry from the last hash-verified artifact.",
        False,
    )
    return {
        "recovered": True,
        "tasks": recovered_tasks,
        "jobs": recovered_jobs,
        "projectStatus": recovered_project_status,
    }


def save(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> None:
    updated = now_iso()
    project["updatedAt"] = updated
    run["updatedAt"] = updated
    film = as_map(run.get("film"), "run.film")
    film["phase"] = project.get("phase")
    run_status = str(project.get("status"))
    if run_status == "completed":
        run["status"] = "succeeded"
    elif run_status == "failed":
        run["status"] = "failed"
    elif run_status in {"running", "revision-required"}:
        run["status"] = "running"
    else:
        run["status"] = "planned"
    write_json(paths.project, project)
    write_json(paths.run, run)


def add_artifact(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    path: pathlib.Path,
    kind: str,
    content_type: str,
    source: str = "mere-film-tools",
) -> JsonMap:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"artifact does not exist: {resolved}")
    item: JsonMap = {
        "path": relative_or_absolute(resolved, paths.root),
        "kind": kind,
        "contentType": content_type,
        "sha256": file_sha256(resolved),
        "bytes": resolved.stat().st_size,
        "source": source,
        "createdAt": now_iso(),
    }
    artifacts = as_list(project.setdefault("artifacts", []), "project.artifacts")
    prior = [entry for entry in artifacts if isinstance(entry, dict) and entry.get("path") == item["path"]]
    for entry in prior:
        artifacts.remove(entry)
    artifacts.append(item)
    run_artifacts = as_map(run.get("artifacts"), "run.artifacts")
    files = as_list(run_artifacts.setdefault("files", []), "run.artifacts.files")
    path_text = str(resolved)
    if path_text not in files:
        files.append(path_text)
    items = as_list(run_artifacts.setdefault("items", []), "run.artifacts.items")
    items[:] = [entry for entry in items if not (isinstance(entry, dict) and entry.get("path") == item["path"])]
    items.append(item.copy())
    hashes = as_map(run_artifacts.setdefault("sha256", {}), "run.artifacts.sha256")
    hashes[path_text] = item["sha256"]
    return item


def remove_artifact(paths: ProjectPaths, project: JsonMap, run: JsonMap, path: pathlib.Path) -> None:
    resolved = path.expanduser().resolve()
    relative = relative_or_absolute(resolved, paths.root)
    artifacts = as_list(project.setdefault("artifacts", []), "project.artifacts")
    artifacts[:] = [
        item for item in artifacts if not (isinstance(item, dict) and item.get("path") == relative)
    ]
    run_artifacts = as_map(run.get("artifacts"), "run.artifacts")
    absolute = str(resolved)
    files = as_list(run_artifacts.setdefault("files", []), "run.artifacts.files")
    files[:] = [item for item in files if item != absolute]
    items = as_list(run_artifacts.setdefault("items", []), "run.artifacts.items")
    items[:] = [
        item for item in items if not (isinstance(item, dict) and item.get("path") == relative)
    ]
    as_map(run_artifacts.setdefault("sha256", {}), "run.artifacts.sha256").pop(absolute, None)


def gate(project: JsonMap, gate_name: str) -> JsonMap:
    if gate_name not in GATES:
        raise ValueError(f"unknown film gate: {gate_name}")
    approvals = as_map(project.get("approvals"), "project.approvals")
    return as_map(approvals.get(gate_name), f"project.approvals.{gate_name}")


def gate_status(project: JsonMap, gate_name: str) -> str:
    return as_string(gate(project, gate_name).get("status"), f"gate {gate_name}.status")


def set_gate_pending(project: JsonMap, gate_name: str, summary: str) -> None:
    current = gate(project, gate_name)
    current.clear()
    current.update({"status": "pending", "summary": summary, "requestedAt": now_iso()})
    project["status"] = "awaiting-approval"
    history(project, "gate-requested", f"{gate_name}: {summary}")


def unblock_next_gate(project: JsonMap, gate_name: str) -> None:
    current = gate(project, gate_name)
    if current.get("status") == "blocked":
        current["status"] = "pending"


def approve(project: JsonMap, gate_name: str, note: str, approved_by: str) -> None:
    current = gate(project, gate_name)
    status = current.get("status")
    if status == "approved":
        return
    if status != "pending":
        raise ValueError(f"gate {gate_name} is {status}, not pending")
    if gate_name == "brief":
        questions = as_list(as_map(project.get("brief"), "project.brief").get("openQuestions"), "brief.openQuestions")
        if questions:
            raise ValueError("brief has unresolved questions; update the brief before approval")
    current.update({"status": "approved", "approvedAt": now_iso(), "approvedBy": approved_by, "note": note})
    project["status"] = "planned"
    history(project, "gate-approved", f"{gate_name} approved by {approved_by}: {note}")


def update_brief(
    project: JsonMap,
    *,
    audience: str | None,
    genre: str | None,
    tone: str | None,
    rating: str | None,
    language: str | None,
    platform: str | None,
    usage: str | None,
    must_haves: list[str],
    exclusions: list[str],
    references: list[str],
) -> None:
    brief = as_map(project.get("brief"), "project.brief")
    target = as_map(brief.get("target"), "brief.target")
    creative = as_map(brief.get("creative"), "brief.creative")
    updates = {
        "audience": audience,
        "rating": rating,
        "language": language,
        "platform": platform,
        "usage": usage,
    }
    for key, value in updates.items():
        if value:
            target[key] = value
    if genre:
        creative["genre"] = genre
    if tone:
        creative["tone"] = tone
    if must_haves:
        creative["mustHaves"] = must_haves
    if exclusions:
        creative["exclusions"] = exclusions
    if references:
        creative["references"] = references
    questions: list[str] = []
    if target.get("audience") == "unspecified":
        questions.append("Who is the primary audience?")
    if creative.get("genre") == "unspecified":
        questions.append("What genre should govern the story grammar?")
    if creative.get("tone") == "unspecified":
        questions.append("What should the audience feel at the end?")
    if target.get("rating") == "unspecified":
        questions.append("What content rating or safety boundary should the film observe?")
    if not as_list(creative.get("references"), "brief.creative.references"):
        questions.append("Are there visual, cinematic, musical, or pacing references to honor or avoid?")
    if target.get("usage") == "unspecified":
        questions.append("Is the intended use personal, noncommercial, or commercial?")
    brief["openQuestions"] = questions
    brief["completeness"] = {
        "readyForGreenlight": not questions,
        "resolvedFields": 6 - len(questions),
        "totalFields": 6,
    }
    history(project, "brief-updated", "Updated creative brief and recalculated greenlight readiness.")


def configure_production(
    project: JsonMap,
    *,
    mode: str | None,
    pi_command: str | None,
    mere_run_command: str | None,
    ffmpeg_command: str | None,
    ffprobe_command: str | None,
    image_master_model: str | None,
    image_shot_model: str | None,
    video_model: str | None,
    vision_inspector_model: str | None,
    speech_asr_model: str | None,
    speech_tts_model: str | None,
    sfx_model: str | None,
    music_model: str | None,
    takes_per_shot: int | None,
    generate_score: bool | None,
    inspect_generated_media: bool | None,
) -> None:
    production = as_map(project.get("production"), "project.production")
    commands = as_map(production.get("commands"), "project.production.commands")
    models = as_map(production.get("models"), "project.production.models")
    if mode:
        production["mode"] = mode
    for key, value in (
        ("pi", pi_command),
        ("mereRun", mere_run_command),
        ("ffmpeg", ffmpeg_command),
        ("ffprobe", ffprobe_command),
    ):
        if value:
            commands[key] = value
    for key, value in (
        ("imageMaster", image_master_model),
        ("imageShot", image_shot_model),
        ("video", video_model),
        ("visionInspector", vision_inspector_model),
        ("speechAsr", speech_asr_model),
        ("speechTts", speech_tts_model),
        ("sfx", sfx_model),
        ("music", music_model),
    ):
        if value is not None:
            models[key] = value
    if generate_score is not None:
        production["generateScore"] = generate_score
    if takes_per_shot is not None:
        if not 1 <= takes_per_shot <= 4:
            raise ValueError("takes per shot must be between 1 and 4")
        production["takesPerShot"] = takes_per_shot
    if inspect_generated_media is not None:
        production["inspectGeneratedMedia"] = inspect_generated_media
    history(project, "production-configured", f"Production mode is {production.get('mode')}.")


def tasks_for_phase(project: JsonMap, phase: str) -> list[JsonMap]:
    return [
        as_map(item, "department task")
        for item in as_list(project.get("departments"), "project.departments")
        if isinstance(item, dict) and item.get("phase") == phase
    ]


def task_by_id(project: JsonMap, task_id: str) -> JsonMap:
    for item in as_list(project.get("departments"), "project.departments"):
        if isinstance(item, dict) and item.get("id") == task_id:
            return as_map(item, "department task")
    raise ValueError(f"unknown department task: {task_id}")


def ready_tasks(project: JsonMap, phase: str) -> list[JsonMap]:
    tasks = tasks_for_phase(project, phase)
    completed = {
        as_string(item.get("id"), "task.id")
        for item in tasks
        if item.get("status") in {"succeeded", "accepted"}
    }
    ready: list[JsonMap] = []
    for item in tasks:
        status = item.get("status")
        dependencies = [str(value) for value in as_list(item.get("dependsOn"), "task.dependsOn")]
        if status in {"blocked", "failed"} and all(value in completed for value in dependencies):
            item["status"] = "ready"
            ready.append(item)
        elif status == "ready":
            ready.append(item)
    return ready


def production_config(project: JsonMap) -> JsonMap:
    return as_map(project.get("production"), "project.production")


def project_summary(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> JsonMap:
    approvals = as_map(project.get("approvals"), "project.approvals")
    tasks = [as_map(item, "department task") for item in as_list(project.get("departments"), "project.departments")]
    task_counts: dict[str, int] = {}
    for item in tasks:
        status = str(item.get("status"))
        task_counts[status] = task_counts.get(status, 0) + 1
    proof = as_map(project.get("proof"), "project.proof")
    next_gate = next(
        (
            name
            for name in GATES
            if as_map(approvals.get(name), f"approval {name}").get("status") == "pending"
        ),
        None,
    )
    return {
        "contractVersion": "mere.run/film-status.v1",
        "runId": run.get("runId"),
        "projectId": project.get("projectId"),
        "title": project.get("title"),
        "status": project.get("status"),
        "phase": project.get("phase"),
        "nextGate": next_gate,
        "openQuestions": as_map(project.get("brief"), "project.brief").get("openQuestions"),
        "approvals": approvals,
        "taskCounts": task_counts,
        "shots": len(as_list(project.get("shots"), "project.shots")),
        "reviewRequests": project.get("reviewRequests", []),
        "jobs": len(as_list(project.get("jobs"), "project.jobs")),
        "artifacts": len(as_list(project.get("artifacts"), "project.artifacts")),
        "issues": project.get("issues"),
        "proof": proof,
        "productionMode": production_config(project).get("mode"),
        "takesPerShot": production_config(project).get("takesPerShot", 1),
        "projectDirectory": str(paths.root),
        "runManifest": str(paths.run),
        "reviewPackage": str(paths.reviews / "index.html") if (paths.reviews / "index.html").is_file() else None,
    }


def artifact_path(paths: ProjectPaths, item: JsonMap) -> pathlib.Path:
    value = pathlib.Path(as_string(item.get("path"), "artifact.path"))
    return value if value.is_absolute() else paths.root / value


def find_artifact(project: JsonMap, kind: str) -> JsonMap | None:
    for raw in reversed(as_list(project.get("artifacts"), "project.artifacts")):
        if isinstance(raw, dict) and raw.get("kind") == kind:
            return as_map(raw, "artifact")
    return None


def set_issue(project: JsonMap, code: str, message: str, blocking: bool) -> None:
    issues = as_list(project.setdefault("issues", []), "project.issues")
    issues[:] = [item for item in issues if not (isinstance(item, dict) and item.get("code") == code)]
    issues.append({"code": code, "message": message, "blocking": blocking, "recordedAt": now_iso()})


def clear_issue(project: JsonMap, code: str) -> None:
    issues = as_list(project.setdefault("issues", []), "project.issues")
    issues[:] = [item for item in issues if not (isinstance(item, dict) and item.get("code") == code)]


def optional_project_title(project: JsonMap) -> str:
    return optional_string(project.get("title")) or slug(str(project.get("idea") or "film"))

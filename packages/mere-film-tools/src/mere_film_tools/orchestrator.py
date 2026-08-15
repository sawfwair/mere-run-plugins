from __future__ import annotations

import concurrent.futures
import hashlib
import pathlib

from .common import (
    JsonMap,
    PluginError,
    as_int,
    as_list,
    as_map,
    as_string,
    file_sha256,
    load_json,
    now_iso,
    write_json,
)
from .pi_harness import PiResult, invoke_department
from .production import prepare_review_package
from .state import (
    ProjectPaths,
    add_artifact,
    clear_issue,
    history,
    production_config,
    ready_tasks,
    save,
    set_gate_pending,
    set_issue,
    task_by_id,
    tasks_for_phase,
)


def proposal_path(paths: ProjectPaths, task: JsonMap) -> pathlib.Path:
    phase = as_string(task.get("phase"), "task.phase")
    task_id = as_string(task.get("id"), "task.id")
    return paths.proposals / phase / f"{task_id}.json"


def stable_seed(project_id: str, shot_id: str) -> int:
    digest = hashlib.sha256(f"{project_id}:{shot_id}".encode()).hexdigest()
    return int(digest[:12], 16) % 2_147_483_647


def normalize_production_plan(project: JsonMap, plan: JsonMap) -> JsonMap:
    normalized = plan.copy()
    normalized["contractVersion"] = "mere.run/film-production-plan.v1"
    normalized["projectId"] = project.get("projectId")
    normalized["createdAt"] = now_iso()
    target = as_map(as_map(project.get("brief"), "project.brief").get("target"), "brief.target")
    normalized["target"] = target.copy()
    project_id = as_string(project.get("projectId"), "project.projectId")
    shots: list[JsonMap] = []
    total_duration = 0.0
    for raw in as_list(normalized.get("shots"), "productionPlan.shots"):
        shot = as_map(raw, "production shot").copy()
        shot_id = as_string(shot.get("id"), "production shot.id")
        seed = shot.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            shot["seed"] = stable_seed(project_id, shot_id)
        shot.setdefault("dialogue", [])
        sound_effects = as_list(shot.setdefault("soundEffects", []), f"shot {shot_id}.soundEffects")
        normalized_effects: list[JsonMap] = []
        for index, raw_effect in enumerate(sound_effects, start=1):
            effect = as_map(raw_effect, f"shot {shot_id}.soundEffects[{index}]").copy()
            effect.setdefault("levelDb", -10)
            seed = effect.get("seed")
            if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
                effect["seed"] = stable_seed(project_id, f"{shot_id}:sfx:{index}")
            normalized_effects.append(effect)
        shot["soundEffects"] = normalized_effects
        shot.setdefault("transition", "cut")
        duration = shot.get("durationSeconds")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            total_duration += float(duration)
        shot["status"] = "planned"
        shot["take"] = 1
        shots.append(shot)
    normalized["shots"] = shots
    normalized["plannedDurationSeconds"] = round(total_duration, 3)
    return normalized


def accept_treatment(paths: ProjectPaths, project: JsonMap, run: JsonMap, result: PiResult) -> None:
    deliverables = as_map(result.payload.get("deliverables"), "director deliverables")
    treatment = as_map(deliverables.get("treatment"), "director treatment").copy()
    treatment["contractVersion"] = "mere.run/film-treatment.v1"
    treatment["projectId"] = project.get("projectId")
    treatment["createdAt"] = now_iso()
    write_json(paths.treatment, treatment)
    add_artifact(paths, project, run, paths.treatment, "treatment", "application/json", source="pi-director")
    for item in tasks_for_phase(project, "development"):
        if item.get("status") == "succeeded":
            item["status"] = "accepted"
    project["phase"] = "development"
    set_gate_pending(project, "treatment", "Treatment is synthesized and ready for creative approval.")
    clear_issue(project, "development-failed")
    history(project, "treatment-created", "Accepted the director synthesis into the durable treatment.")


def accept_production_plan(paths: ProjectPaths, project: JsonMap, run: JsonMap, result: PiResult) -> None:
    deliverables = as_map(result.payload.get("deliverables"), "director deliverables")
    raw_plan = as_map(deliverables.get("productionPlan"), "director productionPlan")
    plan = normalize_production_plan(project, raw_plan)
    write_json(paths.production, plan)
    add_artifact(paths, project, run, paths.production, "production-plan", "application/json", source="pi-director")
    project["shots"] = [as_map(item, "production shot").copy() for item in as_list(plan.get("shots"), "plan.shots")]
    for item in tasks_for_phase(project, "preproduction"):
        if item.get("status") == "succeeded":
            item["status"] = "accepted"
    as_map(project.get("proof"), "project.proof")["creation"] = True
    project["phase"] = "preproduction"
    set_gate_pending(project, "production", "Production plan, cast, locations, sound intent, and shot list are ready.")
    clear_issue(project, "preproduction-failed")
    history(project, "production-plan-created", "Accepted the director synthesis into the production plan.")


def accept_review(paths: ProjectPaths, project: JsonMap, run: JsonMap, result: PiResult) -> None:
    production = production_config(project)
    proof = as_map(project.get("proof"), "project.proof")
    technical_path = paths.reviews / "technical-qc.json"
    rough_cut = paths.cuts / "rough-cut.mp4"
    if not technical_path.is_file() or not rough_cut.is_file():
        raise PluginError("current technical QC and rough-cut evidence are required before accepting creative review")
    technical = load_json(technical_path)
    technical_master = as_map(technical.get("master"), "technical review.master")
    if technical.get("passed") is not True or technical_master.get("sha256") != file_sha256(rough_cut):
        raise PluginError("technical QC must pass against the current rough cut before accepting creative review")
    if bool(production.get("inspectGeneratedMedia", True)) and not bool(proof.get("inspection")):
        raise PluginError("local generated-media inspection proof is required before accepting creative review")
    if not bool(proof.get("dialogue")):
        raise PluginError("dialogue generation and transcription proof is required before accepting creative review")
    if not bool(proof.get("sound")):
        raise PluginError("generated sound-effect proof is required before accepting creative review")
    if not bool(proof.get("captions")):
        raise PluginError("caption sidecar proof is required before accepting creative review")
    deliverables = as_map(result.payload.get("deliverables"), "director deliverables")
    review = as_map(deliverables.get("review"), "director review").copy()
    review["contractVersion"] = "mere.run/film-creative-review.v1"
    review["projectId"] = project.get("projectId")
    review["createdAt"] = now_iso()
    path = paths.reviews / "creative-review.json"
    write_json(path, review)
    add_artifact(paths, project, run, path, "creative-review", "application/json", source="pi-director")
    for item in tasks_for_phase(project, "review"):
        if item.get("status") == "succeeded":
            item["status"] = "accepted"
    if review.get("decision") == "pass":
        proof["review"] = True
        project["phase"] = "review"
        set_gate_pending(project, "picture-lock", "Technical and independent creative review passed.")
        clear_issue(project, "creative-review")
        history(project, "review-passed", "Independent review recommended picture lock.")
    else:
        project["status"] = "revision-required"
        project["phase"] = "review"
        set_issue(project, "creative-review", "Independent review requires targeted revisions before picture lock.", True)
        history(project, "review-revision-required", "Independent review requested targeted revisions.")
    prepare_review_package(paths, project, run)


def accept_synthesis(paths: ProjectPaths, project: JsonMap, run: JsonMap, task: JsonMap, result: PiResult) -> None:
    task_id = as_string(task.get("id"), "task.id")
    if task_id == "treatment-synthesis":
        accept_treatment(paths, project, run, result)
    elif task_id == "production-synthesis":
        accept_production_plan(paths, project, run, result)
    elif task_id == "review-synthesis":
        accept_review(paths, project, run, result)
    else:
        raise PluginError(f"unknown synthesis task: {task_id}")


def record_result(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    task: JsonMap,
    result: PiResult,
) -> None:
    path = proposal_path(paths, task)
    write_json(path, result.payload)
    add_artifact(paths, project, run, path, "department-proposal", "application/json", source="pi-subagent")
    task["status"] = "succeeded"
    task["attempts"] = result.attempts
    task["proposal"] = str(path.relative_to(paths.root))
    task["completedAt"] = now_iso()
    task["command"] = [result.command[0], "--print", "..."]
    history(project, "department-completed", f"{task.get('id')} returned a validated structured proposal.")


def run_one(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    task: JsonMap,
    pi_command: str,
    timeout_seconds: int,
    extra_context: list[pathlib.Path] | None = None,
) -> PiResult:
    task["status"] = "running"
    task["startedAt"] = now_iso()
    task["attempts"] = as_int(task.get("attempts", 0), "task.attempts") + 1
    project["status"] = "running"
    save(paths, project, run)
    return invoke_department(
        paths=paths,
        task=task,
        pi_command=pi_command,
        timeout_seconds=timeout_seconds,
        extra_context=extra_context,
    )


def run_parallel(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    tasks: list[JsonMap],
    pi_command: str,
    timeout_seconds: int,
    max_parallel: int,
    extra_context: list[pathlib.Path] | None,
) -> None:
    for item in tasks:
        item["status"] = "running"
        item["startedAt"] = now_iso()
        item["attempts"] = as_int(item.get("attempts", 0), "task.attempts") + 1
    project["status"] = "running"
    save(paths, project, run)
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_parallel, len(tasks))) as executor:
        future_map: dict[concurrent.futures.Future[PiResult], JsonMap] = {
            executor.submit(
                invoke_department,
                paths=paths,
                task=item,
                pi_command=pi_command,
                timeout_seconds=timeout_seconds,
                extra_context=extra_context,
            ): item
            for item in tasks
        }
        for future in concurrent.futures.as_completed(future_map):
            item = future_map[future]
            try:
                record_result(paths, project, run, item, future.result())
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = str(exc)
                item["failedAt"] = now_iso()
                failures.append(f"{item.get('id')}: {exc}")
            save(paths, project, run)
    if failures:
        raise PluginError("; ".join(failures))


def run_phase(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    phase: str,
    pi_command: str,
    timeout_seconds: int,
    max_parallel: int,
    only_task: str | None = None,
    extra_context: list[pathlib.Path] | None = None,
) -> None:
    candidates = ready_tasks(project, phase)
    if only_task:
        selected = task_by_id(project, only_task)
        if selected.get("phase") != phase:
            raise PluginError(f"task {only_task} does not belong to phase {phase}", 2)
        if selected.get("status") not in {"ready", "failed"}:
            raise PluginError(f"task {only_task} is {selected.get('status')}, not ready", 2)
        candidates = [selected]
    regular = [item for item in candidates if not bool(item.get("synthesis"))]
    if regular:
        try:
            run_parallel(
                paths=paths,
                project=project,
                run=run,
                tasks=regular,
                pi_command=pi_command,
                timeout_seconds=timeout_seconds,
                max_parallel=max_parallel,
                extra_context=extra_context,
            )
        except PluginError:
            project["status"] = "failed"
            set_issue(project, f"{phase}-failed", f"One or more {phase} departments failed; resume is safe.", True)
            save(paths, project, run)
            raise
        if only_task:
            project["status"] = "planned"
            save(paths, project, run)
            return
    synthesis_ready = [item for item in ready_tasks(project, phase) if bool(item.get("synthesis"))]
    if only_task:
        synthesis_ready = [item for item in synthesis_ready if item.get("id") == only_task]
    for item in synthesis_ready:
        try:
            result = run_one(
                paths=paths,
                project=project,
                run=run,
                task=item,
                pi_command=pi_command,
                timeout_seconds=timeout_seconds,
                extra_context=extra_context,
            )
            record_result(paths, project, run, item, result)
            accept_synthesis(paths, project, run, item, result)
            save(paths, project, run)
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
            project["status"] = "failed"
            set_issue(project, f"{phase}-failed", f"{item.get('id')} failed: {exc}", True)
            save(paths, project, run)
            raise

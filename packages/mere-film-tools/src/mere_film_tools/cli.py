from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys

from . import __version__
from .common import (
    JsonMap,
    PluginError,
    as_int,
    as_list,
    as_map,
    as_string,
    load_json,
    now_iso,
    slug,
    validate_run_id,
    write_json,
)
from .handoff import export_animatic_handoff
from .locking import project_lock
from .orchestrator import run_phase
from .pi_harness import interactive_command, interactive_environment, launch_interactive
from .production import (
    archive_for_reroll,
    current_review_binding,
    execute_production,
    inspect_generated_media,
    prepare_delivery,
    prepare_review_attachments,
    prepare_review_package,
    record_human_review_decision,
    technical_review,
    validate_picture_lock_evidence,
    verify_production_models,
)
from .state import (
    GATES,
    ProjectPaths,
    add_artifact,
    approve,
    configure_production,
    create_brief,
    create_project,
    create_run_manifest,
    gate,
    initialize_project,
    load_state,
    paths_for_root,
    paths_from_run,
    production_config,
    project_summary,
    recover_interrupted_work,
    save,
    update_brief,
)

PLUGIN_NAME = "mere-film-tools"


def eprint(message: str) -> None:
    sys.stderr.write(message.rstrip() + "\n")


def print_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def default_run_id() -> str:
    return "film-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def working_title(idea: str) -> str:
    words = [word.strip(".,!?;:'\"") for word in idea.split() if word.strip(".,!?;:'\"")]
    return " ".join(words[:6]).title() or "Untitled Film"


def plugin_manifest() -> JsonMap:
    commands = [
        {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
        {"name": "doctor", "description": "Check Pi and local media-production readiness.", "stdout": "json"},
        {"name": "plan", "description": "Create a durable film project without invoking agents or media.", "stdout": "json"},
        {"name": "run", "description": "Advance through approved film phases and stop at the next gate.", "stdout": "json"},
        {"name": "resume", "description": "Inspect or continue a durable film run.", "stdout": "json"},
        {"name": "recover", "description": "Recover orphaned running work without advancing phases.", "stdout": "json"},
        {"name": "cleanup", "description": "Record the local no-op cleanup policy.", "stdout": "json"},
        {"name": "status", "description": "Read film phase, gates, tasks, artifacts, and proof.", "stdout": "json"},
        {"name": "brief", "description": "Record user-confirmed creative brief requirements.", "stdout": "json"},
        {"name": "approve", "description": "Record explicit user approval for a pending gate.", "stdout": "json"},
        {"name": "configure", "description": "Configure plan, draft, or final local production.", "stdout": "json"},
        {"name": "preflight", "description": "Resolve every model required by the accepted production plan.", "stdout": "json"},
        {"name": "delegate", "description": "Run one ready read-only Pi department task.", "stdout": "json"},
        {"name": "review", "description": "Run technical and independent creative review.", "stdout": "json"},
        {"name": "review-decision", "description": "Record a hash-bound explicit human review decision.", "stdout": "json"},
        {"name": "reroll", "description": "Archive a prior take and prepare a targeted shot reroll.", "stdout": "json"},
        {"name": "export-animatic", "description": "Verify and export selected film assets for Animatic.", "stdout": "json"},
        {"name": "agent", "description": "Launch the bundled interactive Pi producer-director.", "stdout": "text"},
    ]
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": PLUGIN_NAME,
        "description": "Pi-powered local short-film studio with durable production, review, and delivery proof.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-film-tools",
        "commands": commands,
        "capabilities": [
            "film",
            "short-film",
            "pi-agent",
            "multi-agent",
            "creative-brief",
            "screenplay",
            "shot-planning",
            "character-continuity",
            "image",
            "video",
            "speech",
            "sound-effects",
            "transcription",
            "music",
            "assembly",
            "generated-media-inspection",
            "multi-take-selection",
            "captions",
            "loudness-mastering",
            "model-readiness",
            "usage-policy-gates",
            "delivery-stills",
            "human-review-package",
            "human-review-decision",
            "crash-recovery",
            "review",
            "delivery",
            "resumable",
            "provenance",
        ],
        "stdout": {"machineReadableByDefault": True, "diagnostics": "stderr"},
        "security": {
            "usesUserCredentials": True,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def command_exists(value: str) -> bool:
    path = pathlib.Path(value).expanduser()
    return ((path.is_absolute() or "/" in value) and path.is_file()) or shutil.which(value) is not None


def executable_detail(value: str) -> str:
    path = pathlib.Path(value).expanduser()
    if (path.is_absolute() or "/" in value) and path.is_file():
        return str(path.resolve())
    return shutil.which(value) or "not found"


def managed_pi_command(mere_run_command: str) -> str | None:
    if not command_exists(mere_run_command):
        return None
    try:
        process = subprocess.run(
            [executable_detail(mere_run_command), "agent", "status", "--json"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        return None
    try:
        payload = as_map(json.loads(process.stdout), "mere.run agent status")
        pi = as_map(payload.get("pi"), "mere.run agent status.pi")
        path = as_string(pi.get("path"), "mere.run agent status.pi.path")
    except (json.JSONDecodeError, PluginError):
        return None
    if pi.get("installed") is not True or not command_exists(path):
        return None
    return executable_detail(path)


def resolved_pi_command(pi_command: str, mere_run_command: str) -> str:
    if command_exists(pi_command):
        return executable_detail(pi_command)
    if pi_command == "pi":
        return managed_pi_command(mere_run_command) or pi_command
    return pi_command


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    selected_pi = resolved_pi_command(args.pi_command, args.mere_run_command)
    checks: list[JsonMap] = []
    for name, command, required in (
        ("pi", selected_pi, True),
        ("mere.run", args.mere_run_command, True),
        ("ffmpeg", args.ffmpeg_command, True),
        ("ffprobe", args.ffprobe_command, True),
        ("mere-animatic-tools", "mere-animatic-tools", False),
        ("mere-vfx-tools", "mere-vfx-tools", False),
    ):
        checks.append(
            {
                "name": name,
                "ok": command_exists(command),
                "required": required,
                "detail": executable_detail(command),
            }
        )
    checks.append({"name": "python", "ok": True, "required": True, "detail": sys.version.split()[0]})
    ok = all(bool(item.get("ok")) for item in checks if bool(item.get("required")))
    print_json(
        {
            "ok": ok,
            "checks": checks,
            "note": "Pi provider credentials are managed by Pi and are never read or stored by mere-film-tools.",
        }
    )
    return 0 if ok else 3


def production_defaults(args: argparse.Namespace) -> JsonMap:
    mere_run_command = args.mere_run_command or os.environ.get("MERE_FILM_TOOLS_MERE_RUN", "mere.run")
    pi_command = args.pi_command or os.environ.get("MERE_FILM_TOOLS_PI", "pi")
    return {
        "mode": args.production_mode,
        "takesPerShot": args.takes_per_shot,
        "generateScore": not args.no_generate_score,
        "inspectGeneratedMedia": True,
        "maxParallelAgents": args.max_parallel,
        "piTimeoutSeconds": args.pi_timeout,
        "mediaTimeoutSeconds": args.media_timeout,
        "commands": {
            "pi": resolved_pi_command(pi_command, mere_run_command),
            "mereRun": mere_run_command,
            "ffmpeg": args.ffmpeg_command or os.environ.get("MERE_FILM_TOOLS_FFMPEG", "ffmpeg"),
            "ffprobe": args.ffprobe_command or os.environ.get("MERE_FILM_TOOLS_FFPROBE", "ffprobe"),
        },
        "models": {
            "imageMaster": args.image_master_model,
            "imageShot": args.image_shot_model,
            "video": args.video_model or "",
            "visionInspector": args.vision_inspector_model or "",
            "speechAsr": args.speech_asr_model or "",
            "speechTts": args.speech_tts_model,
            "sfx": args.sfx_model,
            "music": args.music_model,
        },
        "resourcePolicy": {
            "agentConcurrencyMaximum": 4,
            "mediaConcurrency": 1,
            "requiresProductionApproval": True,
            "planModeRunsMedia": False,
        },
    }


def create_from_args(args: argparse.Namespace) -> tuple[ProjectPaths, JsonMap, JsonMap]:
    idea = as_string(args.idea, "idea")
    title = args.title or working_title(idea)
    run_id = args.run_id
    validate_run_id(run_id)
    project_id = slug(args.project_id or title)
    paths = paths_for_root(args.output_dir, args.manifest)
    with project_lock(paths.root, "create-project"):
        if paths.run.exists() or paths.project.exists():
            raise PluginError(f"film project already exists in {paths.root}; use resume or agent --run-manifest", 2)
        brief = create_brief(
            title=title,
            idea=idea,
            duration_seconds=args.duration,
            width=args.width,
            height=args.height,
            fps=args.fps,
            audience=args.audience,
            genre=args.genre,
            tone=args.tone,
            rating=args.rating,
            language=args.language,
            platform=args.platform,
            usage=args.usage,
            must_haves=args.must_have,
            exclusions=args.exclude,
            references=args.reference,
        )
        project = create_project(
            project_id=project_id,
            title=title,
            idea=idea,
            brief=brief,
            production_config=production_defaults(args),
        )
        run = create_run_manifest(paths, run_id, project)
        initialize_project(paths, project, run)
    return paths, project, run


def command_plan(args: argparse.Namespace) -> int:
    paths, project, run = create_from_args(args)
    print_json(
        {
            "run": run,
            "status": project_summary(paths, project, run),
            "next": f"mere-film-tools agent --run-manifest {paths.run}",
        }
    )
    return 0


def command_status(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    print_json(project_summary(paths, project, run))
    return 0


def command_brief(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    if gate(project, "brief").get("status") == "approved":
        raise PluginError("brief is already approved; create a revision instead of silently changing canon", 2)
    update_brief(
        project,
        audience=args.audience,
        genre=args.genre,
        tone=args.tone,
        rating=args.rating,
        language=args.language,
        platform=args.platform,
        usage=args.usage,
        must_haves=args.must_have,
        exclusions=args.exclude,
        references=args.reference,
    )
    write_json(paths.brief, project["brief"])
    add_artifact(paths, project, run, paths.brief, "brief", "application/json")
    save(paths, project, run)
    print_json(project_summary(paths, project, run))
    return 0


def command_approve(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    picture_lock_evidence: JsonMap | None = None
    if args.gate == "picture-lock":
        picture_lock_evidence = validate_picture_lock_evidence(paths, project)
    if args.gate == "delivery":
        proof = as_map(project.get("proof"), "project.proof")
        if not bool(proof.get("delivery")):
            raise PluginError("delivery proof is absent; prepare delivery before approval", 2)
    try:
        approve(project, args.gate, args.note, args.approved_by)
    except ValueError as exc:
        raise PluginError(str(exc), 2) from None
    if args.gate == "delivery":
        project["status"] = "completed"
        project["phase"] = "completed"
    if picture_lock_evidence:
        gate(project, "picture-lock").update(picture_lock_evidence)
    save(paths, project, run)
    print_json(project_summary(paths, project, run))
    return 0


def command_configure(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    score: bool | None = None
    if args.generate_score:
        score = True
    elif args.no_generate_score:
        score = False
    inspect_media: bool | None = None
    if args.inspect_generated_media:
        inspect_media = True
    elif args.no_inspect_generated_media:
        inspect_media = False
    configure_production(
        project,
        mode=args.mode,
        pi_command=args.pi_command,
        mere_run_command=args.mere_run_command,
        ffmpeg_command=args.ffmpeg_command,
        ffprobe_command=args.ffprobe_command,
        image_master_model=args.image_master_model,
        image_shot_model=args.image_shot_model,
        video_model=args.video_model,
        vision_inspector_model=args.vision_inspector_model,
        speech_asr_model=args.speech_asr_model,
        speech_tts_model=args.speech_tts_model,
        sfx_model=args.sfx_model,
        music_model=args.music_model,
        takes_per_shot=args.takes_per_shot,
        generate_score=score,
        inspect_generated_media=inspect_media,
    )
    save(paths, project, run)
    print_json(project_summary(paths, project, run))
    return 0


def command_preflight(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    configured_timeout = as_int(
        production_config(project).get("mediaTimeoutSeconds"),
        "project.production.mediaTimeoutSeconds",
    )
    timeout = min(args.media_timeout or configured_timeout, 300)
    receipt_path = verify_production_models(paths, project, run, timeout)
    print_json(
        {
            "readiness": load_json(receipt_path),
            "status": project_summary(paths, project, run),
        }
    )
    return 0


def phase_for_task(project: JsonMap, task_id: str) -> str:
    for raw in as_list(project.get("departments"), "project.departments"):
        if isinstance(raw, dict) and raw.get("id") == task_id:
            return as_string(raw.get("phase"), "task.phase")
    raise PluginError(f"unknown department task: {task_id}", 2)


def ensure_phase_authorized(project: JsonMap, phase: str) -> None:
    required = {"development": "brief", "preproduction": "treatment", "review": "production"}.get(phase)
    if required and gate(project, required).get("status") != "approved":
        raise PluginError(f"{required} gate must be approved before {phase}", 2)
    if phase == "review" and not bool(as_map(project.get("proof"), "project.proof").get("assembly")):
        raise PluginError("assembled rough-cut proof is required before review", 2)


def command_delegate(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    phase = phase_for_task(project, args.task)
    ensure_phase_authorized(project, phase)
    production = production_config(project)
    run_phase(
        paths=paths,
        project=project,
        run=run,
        phase=phase,
        pi_command=args.pi_command or as_string(as_map(production.get("commands"), "commands").get("pi"), "commands.pi"),
        timeout_seconds=args.pi_timeout or as_int(production.get("piTimeoutSeconds"), "production.piTimeoutSeconds"),
        max_parallel=1,
        only_task=args.task,
        extra_context=review_attachments(paths, project, run) if phase == "review" else None,
    )
    print_json(project_summary(paths, project, run))
    return 0


def review_attachments(paths: ProjectPaths, project: JsonMap, run: JsonMap) -> list[pathlib.Path]:
    attachments = prepare_review_attachments(paths, project, run)
    dialogue_qc = paths.reviews / "dialogue-qc.json"
    if dialogue_qc.is_file():
        attachments.append(dialogue_qc)
    for evidence in (paths.reviews / "sound-qc.json", paths.captions / "captions.json"):
        if evidence.is_file():
            attachments.append(evidence)
    timeout = as_int(production_config(project).get("mediaTimeoutSeconds"), "production.mediaTimeoutSeconds")
    receipt = inspect_generated_media(paths, project, run, timeout)
    if receipt:
        attachments.append(receipt)
        attachments.extend(sorted((paths.reviews / "inspection-frames").glob("*.png")))
    prepare_review_package(paths, project, run)
    return attachments


def advance(
    *,
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    pi_command: str | None,
    max_parallel: int | None,
    pi_timeout: int | None,
    media_timeout: int | None,
) -> JsonMap:
    production = production_config(project)
    commands = as_map(production.get("commands"), "project.production.commands")
    selected_pi = pi_command or as_string(commands.get("pi"), "commands.pi")
    selected_parallel = max_parallel or as_int(production.get("maxParallelAgents"), "production.maxParallelAgents")
    selected_pi_timeout = pi_timeout or as_int(production.get("piTimeoutSeconds"), "production.piTimeoutSeconds")
    selected_media_timeout = media_timeout or as_int(
        production.get("mediaTimeoutSeconds"), "production.mediaTimeoutSeconds"
    )
    proof = as_map(project.get("proof"), "project.proof")
    if gate(project, "brief").get("status") != "approved":
        return {"action": "awaiting-brief-approval", "status": project_summary(paths, project, run)}
    if gate(project, "treatment").get("status") == "blocked":
        run_phase(
            paths=paths,
            project=project,
            run=run,
            phase="development",
            pi_command=selected_pi,
            timeout_seconds=selected_pi_timeout,
            max_parallel=selected_parallel,
        )
        return {"action": "treatment-created", "status": project_summary(paths, project, run)}
    if gate(project, "treatment").get("status") != "approved":
        return {"action": "awaiting-treatment-approval", "status": project_summary(paths, project, run)}
    if gate(project, "production").get("status") == "blocked":
        run_phase(
            paths=paths,
            project=project,
            run=run,
            phase="preproduction",
            pi_command=selected_pi,
            timeout_seconds=selected_pi_timeout,
            max_parallel=selected_parallel,
        )
        return {"action": "production-plan-created", "status": project_summary(paths, project, run)}
    if gate(project, "production").get("status") != "approved":
        return {"action": "awaiting-production-approval", "status": project_summary(paths, project, run)}
    if not bool(proof.get("assembly")):
        result = execute_production(
            paths=paths,
            project=project,
            run=run,
            timeout_seconds=selected_media_timeout,
        )
        return {"action": "production", "result": result, "status": project_summary(paths, project, run)}
    if not bool(proof.get("review")) and project.get("status") != "revision-required":
        technical = technical_review(paths, project, run)
        if not bool(technical.get("passed")):
            return {"action": "technical-review-failed", "review": technical, "status": project_summary(paths, project, run)}
        run_phase(
            paths=paths,
            project=project,
            run=run,
            phase="review",
            pi_command=selected_pi,
            timeout_seconds=selected_pi_timeout,
            max_parallel=selected_parallel,
            extra_context=review_attachments(paths, project, run),
        )
        return {"action": "independent-review", "status": project_summary(paths, project, run)}
    if not bool(proof.get("review")) and project.get("status") == "revision-required":
        return {
            "action": "revision-required",
            "review": str(paths.reviews / "creative-review.json"),
            "status": project_summary(paths, project, run),
        }
    if gate(project, "picture-lock").get("status") != "approved":
        return {"action": "awaiting-picture-lock", "status": project_summary(paths, project, run)}
    if not bool(proof.get("delivery")):
        delivery = prepare_delivery(paths, project, run)
        return {"action": "delivery-prepared", "delivery": delivery, "status": project_summary(paths, project, run)}
    if gate(project, "delivery").get("status") != "approved":
        return {"action": "awaiting-delivery-approval", "status": project_summary(paths, project, run)}
    project["status"] = "completed"
    project["phase"] = "completed"
    save(paths, project, run)
    return {"action": "completed", "status": project_summary(paths, project, run)}


def command_run(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    if args.dry_run:
        print_json({"action": "dry-run", "status": project_summary(paths, project, run), "run": run})
        return 0
    print_json(
        advance(
            paths=paths,
            project=project,
            run=run,
            pi_command=args.pi_command,
            max_parallel=args.max_parallel,
            pi_timeout=args.pi_timeout,
            media_timeout=args.media_timeout,
        )
    )
    return 0


def command_resume(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    if not args.execute:
        print_json(project_summary(paths, project, run))
        return 0
    print_json(
        advance(
            paths=paths,
            project=project,
            run=run,
            pi_command=args.pi_command,
            max_parallel=args.max_parallel,
            pi_timeout=args.pi_timeout,
            media_timeout=args.media_timeout,
        )
    )
    return 0


def command_recover(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    print_json(
        {
            "recovery": getattr(
                args,
                "recovery_payload",
                {"recovered": False, "tasks": [], "jobs": [], "projectStatus": False},
            ),
            "status": project_summary(paths, project, run),
        }
    )
    return 0


def command_review(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    technical = technical_review(paths, project, run)
    if not bool(technical.get("passed")) or args.technical_only:
        print_json({"technical": technical, "status": project_summary(paths, project, run)})
        return 0 if bool(technical.get("passed")) else 1
    production = production_config(project)
    commands = as_map(production.get("commands"), "commands")
    run_phase(
        paths=paths,
        project=project,
        run=run,
        phase="review",
        pi_command=args.pi_command or as_string(commands.get("pi"), "commands.pi"),
        timeout_seconds=args.pi_timeout or as_int(production.get("piTimeoutSeconds"), "production.piTimeoutSeconds"),
        max_parallel=args.max_parallel or as_int(production.get("maxParallelAgents"), "production.maxParallelAgents"),
        extra_context=review_attachments(paths, project, run),
    )
    print_json({"technical": technical, "status": project_summary(paths, project, run)})
    return 0


def command_review_decision(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    if args.input:
        payload = load_json(args.input)
    else:
        if not args.decision:
            raise PluginError("provide --input or --decision", 2)
        binding = current_review_binding(paths, project)
        rerolls: list[JsonMap] = []
        for value in args.reroll:
            shot_id, separator, note = value.partition(":")
            if not separator or not shot_id.strip() or not note.strip():
                raise PluginError("--reroll must use SHOT_ID:NOTE", 2)
            rerolls.append({"shotId": shot_id.strip(), "note": note.strip()})
        payload = {
            "contractVersion": "mere.run/film-human-review.v1",
            "projectId": project.get("projectId"),
            "createdAt": now_iso(),
            "masterSha256": binding.get("masterSha256"),
            "reviewEvidenceDigest": binding.get("reviewEvidenceDigest"),
            "decision": args.decision,
            "reviewer": args.reviewer,
            "notes": args.note,
            "rerolls": rerolls,
        }
    result = record_human_review_decision(paths, project, run, payload)
    print_json({"action": "human-review-recorded", "decision": result, "status": project_summary(paths, project, run)})
    return 0


def command_reroll(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    result = archive_for_reroll(paths, project, run, args.shot, args.note)
    print_json({"reroll": result, "status": project_summary(paths, project, run)})
    return 0


def command_export_animatic(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    print_json(export_animatic_handoff(paths, project, run, args.output))
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    paths, project, run = load_state(args.run_manifest)
    cleanup = as_map(run.get("cleanup"), "run.cleanup")
    cleanup.update(
        {
            "status": "skipped",
            "reason": "mere-film-tools creates only local resumable project artifacts; cleanup never deletes them",
        }
    )
    save(paths, project, run)
    print_json(run)
    return 0


def command_agent(args: argparse.Namespace) -> int:
    if args.run_manifest:
        paths, project, run = load_state(args.run_manifest)
    else:
        if not args.idea or not args.output_dir:
            raise PluginError("agent requires --run-manifest or both --idea and --output-dir", 2)
        paths, project, run = create_from_args(args)
    production = production_config(project)
    commands = as_map(production.get("commands"), "commands")
    pi_command = args.pi_command or as_string(commands.get("pi"), "commands.pi")
    plugin_command = args.plugin_command or PLUGIN_NAME
    command = interactive_command(
        pi_command=pi_command,
        title=as_string(project.get("title"), "project.title"),
        run_manifest=paths.run,
        isolated=args.isolated,
        initial_message=args.message,
    )
    if args.print_command:
        environment = interactive_environment(paths.run, plugin_command)
        print_json(
            {
                "command": command,
                "cwd": str(paths.root),
                "environment": {
                    "MERE_FILM_RUN_MANIFEST": environment["MERE_FILM_RUN_MANIFEST"],
                    "MERE_FILM_TOOLS_COMMAND": environment["MERE_FILM_TOOLS_COMMAND"],
                },
                "status": project_summary(paths, project, run),
            }
        )
        return 0
    return launch_interactive(
        paths=paths,
        title=as_string(project.get("title"), "project.title"),
        pi_command=pi_command,
        plugin_command=plugin_command,
        isolated=args.isolated,
        initial_message=args.message,
    )


def add_creation_args(parser: argparse.ArgumentParser, *, optional: bool = False) -> None:
    parser.add_argument("--idea", required=not optional)
    parser.add_argument("--title")
    parser.add_argument("--project-id")
    parser.add_argument("--output-dir", required=not optional, type=pathlib.Path)
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--duration", type=int, default=45)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--audience")
    parser.add_argument("--genre")
    parser.add_argument("--tone")
    parser.add_argument("--rating")
    parser.add_argument("--language", default="en")
    parser.add_argument("--platform")
    parser.add_argument("--usage", choices=("personal", "noncommercial", "commercial"))
    parser.add_argument("--must-have", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--production-mode", choices=("plan", "draft", "final"), default="plan")
    parser.add_argument(
        "--takes-per-shot",
        type=int,
        choices=range(1, 5),
        default=1,
        help="Generate one to four deterministic candidates per shot before local selection.",
    )
    parser.add_argument("--image-master-model", default="image-zimage-max")
    parser.add_argument("--image-shot-model", default="image-klein-9b")
    parser.add_argument("--video-model", default="video-ltx23-av-mlx")
    parser.add_argument("--vision-inspector-model", default="auto-qwen3-vl-2b")
    parser.add_argument("--speech-asr-model", default="speech-asr-parakeet")
    parser.add_argument("--speech-tts-model", default="speech-tts-qwen3-nano")
    parser.add_argument("--sfx-model", default="sfx-woosh-dflow")
    parser.add_argument("--music-model", default="music-acestep")
    parser.add_argument("--no-generate-score", action="store_true")
    parser.add_argument("--max-parallel", type=int, choices=range(1, 5), default=3)
    parser.add_argument("--pi-timeout", type=int, default=900)
    parser.add_argument("--media-timeout", type=int, default=14400)
    command_default = None if optional else os.environ.get("MERE_FILM_TOOLS_PI", "pi")
    parser.add_argument("--pi-command", default=command_default)
    parser.add_argument(
        "--mere-run-command",
        default=None if optional else os.environ.get("MERE_FILM_TOOLS_MERE_RUN", "mere.run"),
    )
    parser.add_argument(
        "--ffmpeg-command",
        default=None if optional else os.environ.get("MERE_FILM_TOOLS_FFMPEG", "ffmpeg"),
    )
    parser.add_argument(
        "--ffprobe-command",
        default=None if optional else os.environ.get("MERE_FILM_TOOLS_FFPROBE", "ffprobe"),
    )


def add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("run_manifest", type=pathlib.Path)
    parser.add_argument("--pi-command")
    parser.add_argument("--max-parallel", type=int, choices=range(1, 5))
    parser.add_argument("--pi-timeout", type=int)
    parser.add_argument("--media-timeout", type=int)


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    for name in ("run_manifest", "output_dir", "manifest", "output"):
        value = getattr(args, name, None)
        if value is not None:
            setattr(args, name, value.expanduser().resolve())
    for name in ("duration", "width", "height", "fps"):
        value = getattr(args, name, None)
        if value is not None and value <= 0:
            raise PluginError(f"--{name.replace('_', '-')} must be positive", 2)
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PLUGIN_NAME)
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print the plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check Pi and local media readiness.")
    doctor.add_argument("--pi-command", default=os.environ.get("MERE_FILM_TOOLS_PI", "pi"))
    doctor.add_argument("--mere-run-command", default=os.environ.get("MERE_FILM_TOOLS_MERE_RUN", "mere.run"))
    doctor.add_argument("--ffmpeg-command", default=os.environ.get("MERE_FILM_TOOLS_FFMPEG", "ffmpeg"))
    doctor.add_argument("--ffprobe-command", default=os.environ.get("MERE_FILM_TOOLS_FFPROBE", "ffprobe"))
    doctor.set_defaults(func=command_doctor)

    plan = sub.add_parser("plan", help="Create a film project without executing work.")
    add_creation_args(plan)
    plan.set_defaults(func=command_plan)

    status = sub.add_parser("status", help="Read authoritative film state.")
    status.add_argument("run_manifest", type=pathlib.Path)
    status.set_defaults(func=command_status)

    brief = sub.add_parser("brief", help="Update unresolved brief requirements.")
    brief.add_argument("run_manifest", type=pathlib.Path)
    for name in ("audience", "genre", "tone", "rating", "language", "platform"):
        brief.add_argument(f"--{name}")
    brief.add_argument("--usage", choices=("personal", "noncommercial", "commercial"))
    brief.add_argument("--must-have", action="append", default=[])
    brief.add_argument("--exclude", action="append", default=[])
    brief.add_argument("--reference", action="append", default=[])
    brief.set_defaults(func=command_brief)

    approve_parser = sub.add_parser("approve", help="Approve one pending production gate.")
    approve_parser.add_argument("run_manifest", type=pathlib.Path)
    approve_parser.add_argument("--gate", required=True, choices=GATES)
    approve_parser.add_argument("--note", default="Explicitly approved.")
    approve_parser.add_argument("--approved-by", default="user")
    approve_parser.set_defaults(func=command_approve)

    configure = sub.add_parser("configure", help="Configure local production execution.")
    configure.add_argument("run_manifest", type=pathlib.Path)
    configure.add_argument("--mode", choices=("plan", "draft", "final"))
    configure.add_argument("--pi-command")
    configure.add_argument("--mere-run-command")
    configure.add_argument("--ffmpeg-command")
    configure.add_argument("--ffprobe-command")
    configure.add_argument("--image-master-model")
    configure.add_argument("--image-shot-model")
    configure.add_argument("--video-model")
    configure.add_argument("--vision-inspector-model")
    configure.add_argument("--speech-asr-model")
    configure.add_argument("--speech-tts-model")
    configure.add_argument("--sfx-model")
    configure.add_argument("--music-model")
    configure.add_argument("--takes-per-shot", type=int, choices=range(1, 5))
    score = configure.add_mutually_exclusive_group()
    score.add_argument("--generate-score", action="store_true")
    score.add_argument("--no-generate-score", action="store_true")
    inspection = configure.add_mutually_exclusive_group()
    inspection.add_argument("--inspect-generated-media", action="store_true")
    inspection.add_argument("--no-inspect-generated-media", action="store_true")
    configure.set_defaults(func=command_configure)

    preflight = sub.add_parser("preflight", help="Resolve required production models without generating media.")
    preflight.add_argument("run_manifest", type=pathlib.Path)
    preflight.add_argument("--media-timeout", type=int)
    preflight.set_defaults(func=command_preflight)

    run_parser = sub.add_parser("run", help="Advance through approved phases.")
    add_run_args(run_parser)
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.set_defaults(func=command_run)

    resume = sub.add_parser("resume", help="Inspect or continue a run.")
    add_run_args(resume)
    resume.add_argument("--execute", action="store_true")
    resume.set_defaults(func=command_resume)

    recover = sub.add_parser("recover", help="Recover interrupted work without advancing the film.")
    recover.add_argument("run_manifest", type=pathlib.Path)
    recover.set_defaults(func=command_recover)

    delegate = sub.add_parser("delegate", help="Run one ready Pi department task.")
    delegate.add_argument("run_manifest", type=pathlib.Path)
    delegate.add_argument("--task", required=True)
    delegate.add_argument("--pi-command")
    delegate.add_argument("--pi-timeout", type=int)
    delegate.set_defaults(func=command_delegate)

    review = sub.add_parser("review", help="Run technical and creative review.")
    review.add_argument("run_manifest", type=pathlib.Path)
    review.add_argument("--technical-only", action="store_true")
    review.add_argument("--pi-command")
    review.add_argument("--pi-timeout", type=int)
    review.add_argument("--max-parallel", type=int, choices=range(1, 5))
    review.set_defaults(func=command_review)

    review_decision = sub.add_parser("review-decision", help="Record a hash-bound human review decision.")
    review_decision.add_argument("run_manifest", type=pathlib.Path)
    review_decision.add_argument("--input", type=pathlib.Path)
    review_decision.add_argument("--decision", choices=("approve", "revise"))
    review_decision.add_argument("--reviewer", default="user")
    review_decision.add_argument("--note", default="")
    review_decision.add_argument("--reroll", action="append", default=[], metavar="SHOT_ID:NOTE")
    review_decision.set_defaults(func=command_review_decision)

    reroll = sub.add_parser("reroll", help="Archive a take and prepare a shot reroll.")
    reroll.add_argument("run_manifest", type=pathlib.Path)
    reroll.add_argument("--shot", required=True)
    reroll.add_argument("--note", required=True)
    reroll.set_defaults(func=command_reroll)

    export_animatic = sub.add_parser("export-animatic", help="Verify and export a film handoff for Animatic.")
    export_animatic.add_argument("run_manifest", type=pathlib.Path)
    export_animatic.add_argument("--output", type=pathlib.Path)
    export_animatic.set_defaults(func=command_export_animatic)

    cleanup = sub.add_parser("cleanup", help="Record local no-op cleanup.")
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.set_defaults(func=command_cleanup)

    agent = sub.add_parser("agent", help="Launch the Pi producer-director.")
    agent.add_argument("--run-manifest", type=pathlib.Path)
    add_creation_args(agent, optional=True)
    agent.add_argument("--plugin-command")
    context = agent.add_mutually_exclusive_group()
    context.add_argument("--isolated", dest="isolated", action="store_true", default=True)
    context.add_argument(
        "--with-pi-context",
        dest="isolated",
        action="store_false",
        help="Also discover normal Pi resources; explicit film tools remain allowlisted.",
    )
    agent.add_argument("--message")
    agent.add_argument("--print-command", action="store_true")
    agent.set_defaults(func=command_agent)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args = normalize_args(args)
        if command_requires_project_lock(args):
            paths = paths_from_run(args.run_manifest)
            with project_lock(paths.root, str(args.command)):
                locked_paths, project, run = load_state(args.run_manifest)
                recovery = recover_interrupted_work(project)
                args.recovery_payload = recovery
                if bool(recovery.get("recovered")):
                    save(locked_paths, project, run)
                return int(args.func(args))
        return int(args.func(args))
    except PluginError as exc:
        eprint(f"Error: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        eprint("Interrupted.")
        return 130
    except Exception as exc:
        eprint(f"Unexpected error: {exc}")
        return 1


def command_requires_project_lock(args: argparse.Namespace) -> bool:
    command = str(getattr(args, "command", ""))
    if command in {
        "brief",
        "approve",
        "configure",
        "preflight",
        "delegate",
        "review",
        "review-decision",
        "reroll",
        "export-animatic",
        "cleanup",
        "recover",
    }:
        return True
    if command == "run":
        return not bool(getattr(args, "dry_run", False))
    if command == "resume":
        return bool(getattr(args, "execute", False))
    return False

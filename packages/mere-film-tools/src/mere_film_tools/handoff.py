from __future__ import annotations

import os
import pathlib

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
    write_json,
)
from .state import ProjectPaths

CONTRACT_VERSION = "mere.run/film-animatic-handoff.v1"
EXPORTED_KINDS = {
    "cast-master",
    "location-master",
    "shot-keyframe",
    "shot-clip",
    "dialogue",
    "sound-effect",
    "score",
    "subtitle-srt",
    "subtitle-vtt",
    "caption-receipt",
    "edit-block",
    "edit-block-receipt",
    "rough-cut",
    "final-master",
    "delivery-master",
    "poster",
    "thumbnail",
    "technical-review",
    "creative-review",
    "media-inspection",
    "inspection-frame",
    "review-frame",
    "dialogue-qc",
    "sound-qc",
    "take-selection",
    "production-readiness",
    "review-package",
    "human-review",
    "delivery",
}


def export_animatic_handoff(
    paths: ProjectPaths,
    project: JsonMap,
    run: JsonMap,
    output: pathlib.Path | None = None,
) -> JsonMap:
    plan = load_json(paths.root / "production-plan.json")
    if plan.get("contractVersion") != "mere.run/film-production-plan.v1":
        raise PluginError("an accepted mere.run/film-production-plan.v1 is required for Animatic export", 2)

    destination = (output or paths.root / "exports" / "animatic" / "film-animatic-handoff.json").resolve()
    root = paths.root.resolve()
    try:
        destination.relative_to(root)
    except ValueError:
        raise PluginError("Animatic handoff output must stay inside the film project", 2) from None

    artifacts_by_path: dict[str, JsonMap] = {}
    for raw in as_list(project.get("artifacts"), "project.artifacts"):
        artifact = as_map(raw, "project.artifacts[]")
        kind = as_string(artifact.get("kind"), "artifact.kind")
        if kind in EXPORTED_KINDS:
            artifacts_by_path[as_string(artifact.get("path"), "artifact.path")] = artifact

    assets: list[JsonMap] = []
    asset_ids_by_path: dict[str, str] = {}
    for relative_path in sorted(artifacts_by_path):
        artifact = artifacts_by_path[relative_path]
        file_path = verified_artifact_path(root, relative_path, artifact)
        expected = as_string(artifact.get("sha256"), "artifact.sha256")
        asset_id = "film_asset_" + object_sha256({"path": relative_path, "sha256": expected})[7:27]
        asset_ids_by_path[relative_path] = asset_id
        assets.append(
            {
                "id": asset_id,
                "kind": as_string(artifact.get("kind"), "artifact.kind"),
                "relativePath": relative_path,
                "sha256": expected,
                "bytes": file_path.stat().st_size,
                "contentType": as_string(artifact.get("contentType"), "artifact.contentType"),
                "source": as_string(artifact.get("source"), "artifact.source"),
            }
        )

    shots: list[JsonMap] = []
    cursor_milliseconds = 0
    for order, raw in enumerate(as_list(plan.get("shots"), "productionPlan.shots")):
        shot = as_map(raw, "productionPlan.shots[]")
        shot_id = as_string(shot.get("id"), "shot.id")
        duration_milliseconds = round(as_number(shot.get("durationSeconds"), "shot.durationSeconds") * 1000)
        shots.append(
            {
                "id": shot_id,
                "order": order,
                "purpose": as_string(shot.get("purpose"), "shot.purpose"),
                "prompt": as_string(shot.get("prompt"), "shot.prompt"),
                "framePrompt": as_string(shot.get("framePrompt"), "shot.framePrompt"),
                "timelineStartMilliseconds": cursor_milliseconds,
                "durationMilliseconds": duration_milliseconds,
                "characterIds": as_list(shot.get("characters"), "shot.characters"),
                "locationId": as_string(shot.get("location"), "shot.location"),
                "transition": as_string(shot.get("transition"), "shot.transition"),
                "take": as_int(shot.get("take", 1), "shot.take"),
                "seed": as_int(shot.get("selectedSeed", shot.get("seed")), "shot.seed"),
                "keyframeAssetId": asset_ids_by_path.get(f"frames/{shot_id}.png"),
                "clipAssetId": asset_ids_by_path.get(f"clips/{shot_id}.mp4"),
                "dialogue": as_list(shot.get("dialogue", []), "shot.dialogue"),
                "soundEffects": as_list(shot.get("soundEffects", []), "shot.soundEffects"),
            }
        )
        cursor_milliseconds += duration_milliseconds

    target = as_map(plan.get("target"), "productionPlan.target")
    treatment_path = paths.root / "treatment.json"
    treatment = load_json(treatment_path) if treatment_path.is_file() else {}
    project_root = os.path.relpath(root, destination.parent)
    payload: JsonMap = {
        "contractVersion": CONTRACT_VERSION,
        "exportedAt": now_iso(),
        "source": {
            "projectId": as_string(project.get("projectId"), "project.projectId"),
            "projectRoot": project_root,
            "runManifest": str(paths.run.relative_to(root)),
            "projectContractVersion": as_string(project.get("contractVersion"), "project.contractVersion"),
            "updatedAt": as_string(project.get("updatedAt"), "project.updatedAt"),
        },
        "project": {
            "title": as_string(project.get("title"), "project.title"),
            "idea": as_string(project.get("idea"), "project.idea"),
            "logline": treatment.get("logline"),
            "synopsis": treatment.get("synopsis"),
            "theme": treatment.get("theme"),
            "durationMilliseconds": cursor_milliseconds,
            "fps": as_int(target.get("fps", 24), "target.fps"),
            "aspectRatio": target.get("aspectRatio", "16:9"),
            "width": target.get("width"),
            "height": target.get("height"),
        },
        "cast": as_list(plan.get("cast"), "productionPlan.cast"),
        "locations": as_list(plan.get("locations"), "productionPlan.locations"),
        "shots": shots,
        "assets": assets,
        "proof": as_map(project.get("proof"), "project.proof"),
    }
    write_json(destination, payload)
    return {
        "ok": True,
        "contractVersion": CONTRACT_VERSION,
        "manifest": str(destination),
        "manifestSha256": file_sha256(destination),
        "projectId": project.get("projectId"),
        "shots": len(shots),
        "assets": len(assets),
        "bytes": destination.stat().st_size,
        "runId": run.get("runId"),
    }


def verified_artifact_path(root: pathlib.Path, relative_path: str, artifact: JsonMap) -> pathlib.Path:
    relative = pathlib.PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise PluginError(f"unsafe Animatic artifact path: {relative_path}", 2)
    path = (root / pathlib.Path(*relative.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise PluginError(f"Animatic artifact escapes the project: {relative_path}", 2) from None
    if not path.is_file():
        raise PluginError(f"missing Animatic artifact: {relative_path}", 2)
    expected = as_string(artifact.get("sha256"), "artifact.sha256")
    actual = file_sha256(path)
    if actual != expected:
        raise PluginError(f"Animatic artifact hash mismatch for {relative_path}: expected {expected}, got {actual}", 2)
    recorded_bytes = as_int(artifact.get("bytes"), "artifact.bytes")
    if path.stat().st_size != recorded_bytes:
        raise PluginError(
            f"Animatic artifact size mismatch for {relative_path}: expected {recorded_bytes}, got {path.stat().st_size}",
            2,
        )
    return path

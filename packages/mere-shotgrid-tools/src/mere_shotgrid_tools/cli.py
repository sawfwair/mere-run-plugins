from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys
import time
from dataclasses import dataclass
from typing import Protocol, cast

from . import __version__

JsonMap = dict[str, object]
JsonList = list[object]
ShotGridFilters = list[list[object]]

PLUGIN_NAME = "mere-shotgrid-tools"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
MOVIE_EXTENSIONS = {".mov", ".mp4", ".m4v", ".webm", ".avi", ".mkv"}
SHOTGRID_URL_ENV = ("MERE_SHOTGRID_URL", "SHOTGRID_URL", "SG_URL")
SCRIPT_NAME_ENV = ("MERE_SHOTGRID_SCRIPT_NAME", "SHOTGRID_SCRIPT_NAME", "SG_SCRIPT_NAME")
API_KEY_ENV = ("MERE_SHOTGRID_API_KEY", "SHOTGRID_API_KEY", "SG_API_KEY")
LOGIN_ENV = ("MERE_SHOTGRID_LOGIN", "SHOTGRID_LOGIN", "SG_LOGIN")
PASSWORD_ENV = ("MERE_SHOTGRID_PASSWORD", "SHOTGRID_PASSWORD", "SG_PASSWORD")


class PluginError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ShotGridClient(Protocol):
    def find_one(self, entity_type: str, filters: ShotGridFilters, fields: list[str]) -> JsonMap | None: ...

    def find(self, entity_type: str, filters: ShotGridFilters, fields: list[str], *, limit: int) -> list[JsonMap]: ...

    def create(self, entity_type: str, data: JsonMap) -> JsonMap: ...

    def update(self, entity_type: str, entity_id: int, data: JsonMap, **kwargs: object) -> JsonMap: ...

    def upload(self, entity_type: str, entity_id: int, path: str, **kwargs: object) -> object: ...

    def upload_thumbnail(self, entity_type: str, entity_id: int, path: str) -> object: ...

    def delete(self, entity_type: str, entity_id: int) -> object: ...


@dataclass(frozen=True)
class ShotGridConfig:
    site_url: str | None
    script_name: str | None
    api_key: str | None
    login: str | None
    password: str | None

    @property
    def auth_mode(self) -> str | None:
        if self.script_name and self.api_key:
            return "script"
        if self.login and self.password:
            return "user"
        return None


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


def as_map(value: object, context: str) -> JsonMap:
    if not isinstance(value, dict):
        raise PluginError(f"{context} must be a JSON object", 2)
    return cast(JsonMap, value)


def as_list(value: object, context: str) -> JsonList:
    if not isinstance(value, list):
        raise PluginError(f"{context} must be a JSON array", 2)
    return cast(JsonList, value)


def optional_map(value: object, context: str) -> JsonMap | None:
    if value is None:
        return None
    return as_map(value, context)


def string_field(mapping: JsonMap, key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise PluginError(f"{context}.{key} must be a string", 2)
    return value


def int_value(value: object, context: str) -> int:
    if isinstance(value, bool):
        raise PluginError(f"{context} must be an integer", 2)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise PluginError(f"{context} must be an integer", 2)


def load_json(path: pathlib.Path) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), f"JSON file {path}")
    except json.JSONDecodeError as exc:
        raise PluginError(f"invalid JSON in {path}: {exc}", 2) from None


def load_env_file(path: pathlib.Path | None) -> None:
    if path is None or not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def env_first(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def config_from_args(args: argparse.Namespace) -> ShotGridConfig:
    load_env_file(getattr(args, "env_file", None))
    return ShotGridConfig(
        site_url=getattr(args, "site_url", None) or env_first(SHOTGRID_URL_ENV),
        script_name=getattr(args, "script_name", None) or env_first(SCRIPT_NAME_ENV),
        api_key=getattr(args, "api_key", None) or env_first(API_KEY_ENV),
        login=getattr(args, "login", None) or env_first(LOGIN_ENV),
        password=getattr(args, "password", None) or env_first(PASSWORD_ENV),
    )


def validate_config(config: ShotGridConfig) -> None:
    if not config.site_url:
        raise PluginError("ShotGrid site URL is required; set MERE_SHOTGRID_URL or pass --site-url", 3)
    if not config.auth_mode:
        raise PluginError(
            "ShotGrid credentials are required; use script name/API key or login/password",
            3,
        )


def redacted_config(config: ShotGridConfig) -> JsonMap:
    return {
        "siteUrl": config.site_url,
        "authMode": config.auth_mode,
        "hasScriptName": bool(config.script_name),
        "hasApiKey": bool(config.api_key),
        "hasLogin": bool(config.login),
        "hasPassword": bool(config.password),
    }


def make_shotgrid_client(config: ShotGridConfig) -> ShotGridClient:  # pragma: no cover
    validate_config(config)
    try:
        import shotgun_api3
    except ImportError as exc:
        raise PluginError(
            "shotgun_api3 is not installed; reinstall mere-shotgrid-tools or pipx inject shotgun-api3",
            3,
        ) from exc
    if config.auth_mode == "script":
        return cast(ShotGridClient, shotgun_api3.Shotgun(config.site_url, script_name=config.script_name, api_key=config.api_key))
    return cast(ShotGridClient, shotgun_api3.Shotgun(config.site_url, login=config.login, password=config.password))


def file_sha256(path: pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def combined_sha256(values: list[str]) -> str:
    hasher = hashlib.sha256()
    for value in values:
        encoded = value.encode("utf-8")
        hasher.update(len(encoded).to_bytes(4, "big"))
        hasher.update(encoded)
    return "sha256:" + hasher.hexdigest()


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise PluginError(
            "--run-id must start with a letter or digit and contain only letters, digits, '.', '_', or '-'",
            2,
        )


def default_run_id() -> str:
    return "shotgrid-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def default_manifest_path(output_dir: pathlib.Path) -> pathlib.Path:
    return output_dir / "run.json"


def int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def entity_ref(entity_type: str, entity_id: int) -> JsonMap:
    return {"type": entity_type, "id": int(entity_id)}


def ref_from_payload(value: object) -> JsonMap | None:
    if not isinstance(value, dict):
        return None
    entity_type = value.get("type")
    entity_id = int_or_none(value.get("id"))
    if isinstance(entity_type, str) and entity_type and entity_id:
        return entity_ref(entity_type, entity_id)
    return None


def parse_key_value(values: list[str]) -> JsonMap:
    parsed: JsonMap = {}
    for raw in values:
        if "=" not in raw:
            raise PluginError(f"field override must use key=value syntax: {raw}", 2)
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise PluginError(f"field override has an empty key: {raw}", 2)
        try:
            parsed[key] = json.loads(value)
        except json.JSONDecodeError:
            parsed[key] = value
    return parsed


def plugin_manifest() -> JsonMap:
    return {
        "contractVersion": "mere.run/plugin.v1",
        "name": PLUGIN_NAME,
        "version": __version__,
        "executable": "mere-shotgrid-tools",
        "description": "Publish local mere.run artifacts to ShotGrid review Versions and pull task-backed jobs.",
        "homepage": "https://github.com/sawfwair/mere-run-plugins/tree/main/packages/mere-shotgrid-tools",
        "commands": [
            {"name": "manifest", "description": "Print the plugin manifest.", "stdout": "json"},
            {"name": "doctor", "description": "Check local ShotGrid API readiness and optional project access.", "stdout": "json"},
            {"name": "plan", "description": "Write a ShotGrid publish manifest without remote mutations.", "stdout": "json"},
            {"name": "run", "description": "Execute a planned ShotGrid publish manifest.", "stdout": "json"},
            {"name": "resume", "description": "Inspect a recorded ShotGrid publish manifest.", "stdout": "json"},
            {"name": "cleanup", "description": "Skip cleanup or explicitly delete plugin-created records.", "stdout": "json"},
            {"name": "publish", "description": "Plan and run a ShotGrid Version publish.", "stdout": "json"},
            {"name": "pull-tasks", "description": "Query ShotGrid Tasks and write local JSONL job requests.", "stdout": "json"},
        ],
        "capabilities": [
            "production-tracking",
            "shotgrid",
            "flow-production-tracking",
            "version-publish",
            "review-upload",
            "note-create",
            "playlist-link",
            "task-status",
            "task-query",
            "jsonl-jobs",
        ],
        "stdout": {
            "machineReadableByDefault": True,
            "diagnostics": "stderr",
        },
        "security": {
            "usesUserCredentials": True,
            "storesSecrets": False,
            "createsPaidResources": False,
            "cleanupDefault": "none",
        },
    }


def artifact_kind(path: pathlib.Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MOVIE_EXTENSIONS:
        return "movie"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "file"


def artifact_item(path: pathlib.Path, *, label: str | None = None, allow_missing: bool = False) -> JsonMap:
    path = path.expanduser().resolve()
    if not path.is_file():
        if allow_missing:
            return {
                "path": str(path),
                "name": path.name,
                "kind": artifact_kind(path),
                "label": label or path.stem,
                "sha256": None,
                "bytes": None,
                "missing": True,
                "fieldName": None,
            }
        raise PluginError(f"artifact does not exist: {path}", 2)
    return {
        "path": str(path),
        "name": path.name,
        "kind": artifact_kind(path),
        "label": label or path.stem,
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
        "missing": False,
        "fieldName": None,
    }


def collect_paths_from_manifest(path: pathlib.Path) -> list[pathlib.Path]:
    payload = load_json(path)
    artifacts = as_map(payload.get("artifacts", {}), "source manifest artifacts")
    candidates: list[pathlib.Path] = []

    def add(value: object) -> None:
        if isinstance(value, str) and value:
            candidates.append(pathlib.Path(value))
        elif isinstance(value, dict):
            item_path = value.get("path")
            if isinstance(item_path, str) and item_path:
                candidates.append(pathlib.Path(item_path))

    for item in as_list(artifacts.get("items", []), "source manifest artifacts.items"):
        add(item)
    for item in as_list(artifacts.get("files", []), "source manifest artifacts.files"):
        add(item)
    for key in ("image", "movie", "video", "lora", "mask", "thumbnail"):
        add(artifacts.get(key))
    return candidates


def collect_paths_from_bundle(path: pathlib.Path) -> list[pathlib.Path]:
    payload = load_json(path)
    files = payload.get("files", [])
    candidates: list[pathlib.Path] = []
    for item in as_list(files, "artifact bundle files"):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            candidates.append(pathlib.Path(item["path"]))
        elif isinstance(item, str):
            candidates.append(pathlib.Path(item))
    return candidates


def load_request(args: argparse.Namespace) -> JsonMap:
    if not getattr(args, "request_json", None):
        return {}
    return load_json(args.request_json)


def collect_artifacts(args: argparse.Namespace) -> list[JsonMap]:
    paths: list[pathlib.Path] = []
    paths.extend(getattr(args, "artifact", None) or [])
    if getattr(args, "source_run_manifest", None):
        paths.extend(collect_paths_from_manifest(args.source_run_manifest))
    if getattr(args, "artifact_bundle", None):
        paths.extend(collect_paths_from_bundle(args.artifact_bundle))
    seen: set[pathlib.Path] = set()
    items: list[JsonMap] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        items.append(artifact_item(resolved, allow_missing=getattr(args, "allow_missing_artifacts", False)))
    if getattr(args, "review_upload_field", None):
        for item in items:
            if item["kind"] in {"movie", "image"} and not item.get("missing"):
                item["fieldName"] = args.review_upload_field
                break
    return items


def first_image_artifact(artifacts: list[JsonMap]) -> pathlib.Path | None:
    for item in artifacts:
        if item["kind"] == "image" and not item.get("missing"):
            return pathlib.Path(string_field(item, "path", "artifact"))
    return None


def project_target(args: argparse.Namespace, request: JsonMap) -> JsonMap:
    project = request.get("project") if isinstance(request.get("project"), dict) else {}
    project_ref = ref_from_payload(project)
    project_id = args.project_id or (project_ref or {}).get("id") or int_or_none(request.get("project_id") or request.get("projectId"))
    return {
        "type": "Project",
        "id": project_id,
        "code": args.project_code or request.get("project_code") or request.get("projectCode"),
        "name": args.project_name or request.get("project_name") or request.get("projectName"),
    }


def entity_target(args: argparse.Namespace, request: JsonMap) -> JsonMap | None:
    raw_payload = request.get("entity")
    payload = as_map(raw_payload, "request.entity") if isinstance(raw_payload, dict) else {}
    ref = ref_from_payload(payload)
    entity_type = args.entity_type or (ref or {}).get("type") or payload.get("type") or request.get("entity_type")
    entity_id = args.entity_id or (ref or {}).get("id") or int_or_none(payload.get("id") or request.get("entity_id"))
    entity_code = args.entity_code or payload.get("code") or payload.get("name") or request.get("entity_code")
    if not entity_type and not entity_id and not entity_code:
        return None
    if not entity_type:
        raise PluginError("--entity-type is required when linking an entity", 2)
    return {"type": entity_type, "id": entity_id, "code": entity_code}


def task_target(args: argparse.Namespace, request: JsonMap) -> JsonMap | None:
    raw_payload = request.get("task")
    payload = as_map(raw_payload, "request.task") if isinstance(raw_payload, dict) else {}
    ref = ref_from_payload(payload)
    task_id = args.task_id or (ref or {}).get("id") or int_or_none(payload.get("id") or request.get("task_id"))
    task_name = args.task_name or payload.get("content") or payload.get("name") or request.get("task_name")
    if not task_id and not task_name:
        return None
    return {"type": "Task", "id": task_id, "name": task_name}


def playlist_target(args: argparse.Namespace, request: JsonMap) -> JsonMap | None:
    raw_payload = request.get("playlist")
    payload = as_map(raw_payload, "request.playlist") if isinstance(raw_payload, dict) else {}
    ref = ref_from_payload(payload)
    playlist_id = args.playlist_id or (ref or {}).get("id") or int_or_none(payload.get("id") or request.get("playlist_id"))
    playlist_code = args.playlist_code or payload.get("code") or payload.get("name") or request.get("playlist_code")
    if not playlist_id and not playlist_code:
        return None
    return {"type": "Playlist", "id": playlist_id, "code": playlist_code, "createIfMissing": args.create_playlist}


def version_code(args: argparse.Namespace, target: JsonMap | None) -> str:
    if args.version_code:
        return str(args.version_code)
    if target and target.get("code"):
        return f"{target['code']}_{args.run_id}"
    if target and target.get("id"):
        return f"{target['type']}_{target['id']}_{args.run_id}"
    return str(args.run_id)


def make_publish_command(args: argparse.Namespace, command_name: str) -> list[str]:
    command = ["mere-shotgrid-tools", command_name, "--output-dir", str(args.output_dir), "--run-id", args.run_id]
    for name in (
        "project_id",
        "project_code",
        "project_name",
        "entity_type",
        "entity_id",
        "entity_code",
        "task_id",
        "task_name",
        "playlist_id",
        "playlist_code",
        "version_code",
        "status",
        "task_status",
        "user_id",
        "site_url",
    ):
        value = getattr(args, name, None)
        if value is not None:
            command.extend(["--" + name.replace("_", "-"), str(value)])
    if args.create_playlist:
        command.append("--create-playlist")
    if args.description:
        command.extend(["--description", args.description])
    if args.note:
        command.extend(["--note", args.note])
    if args.note_subject:
        command.extend(["--note-subject", args.note_subject])
    if args.source_run_manifest:
        command.extend(["--source-run-manifest", str(args.source_run_manifest)])
    if args.artifact_bundle:
        command.extend(["--artifact-bundle", str(args.artifact_bundle)])
    if args.thumbnail:
        command.extend(["--thumbnail", str(args.thumbnail)])
    for artifact in args.artifact or []:
        command.extend(["--artifact", str(artifact)])
    for field in args.version_field or []:
        command.extend(["--version-field", field])
    if args.no_review_upload_field:
        command.append("--no-review-upload-field")
    elif args.review_upload_field:
        command.extend(["--review-upload-field", args.review_upload_field])
    return command


def planned_operations(manifest: JsonMap) -> list[JsonMap]:
    shotgrid = as_map(manifest.get("shotgrid"), "manifest.shotgrid")
    operations: list[JsonMap] = [
        {
            "action": "create",
            "entityType": "Version",
            "description": "Create review Version linked to the resolved Project, entity, and Task.",
        }
    ]
    for raw_item in as_list(shotgrid.get("uploads"), "manifest.shotgrid.uploads"):
        item = as_map(raw_item, "manifest.shotgrid.uploads[]")
        operations.append({
            "action": "upload",
            "entityType": "Version",
            "path": item["path"],
            "fieldName": item.get("fieldName"),
        })
    thumbnail = optional_map(shotgrid.get("thumbnail"), "manifest.shotgrid.thumbnail")
    if thumbnail:
        operations.append({"action": "upload-thumbnail", "entityType": "Version", "path": thumbnail["path"]})
    if shotgrid.get("note"):
        operations.append({"action": "create", "entityType": "Note", "description": "Create review note linked to the Version."})
    if shotgrid.get("playlist"):
        operations.append({"action": "playlist-link", "entityType": "Playlist", "description": "Add Version to Playlist."})
    if shotgrid.get("taskUpdate"):
        operations.append({"action": "update", "entityType": "Task", "field": "sg_status_list"})
    return operations


def make_publish_manifest(args: argparse.Namespace, command_name: str = "plan") -> JsonMap:
    request = load_request(args)
    artifacts = collect_artifacts(args)
    project = project_target(args, request)
    target = entity_target(args, request)
    task = task_target(args, request)
    playlist = playlist_target(args, request)
    if not project.get("id") and not project.get("code") and not project.get("name"):
        raise PluginError("a ShotGrid project id, code, or name is required", 2)
    if target and target.get("id") is None and not target.get("code"):
        raise PluginError("linked entity requires --entity-id or --entity-code", 2)
    thumbnail_path = args.thumbnail or first_image_artifact(artifacts)
    thumbnail = artifact_item(thumbnail_path, label="thumbnail") if thumbnail_path else None
    created = now_iso()
    output_dir = args.output_dir
    manifest_path = args.manifest or default_manifest_path(output_dir)
    version_fields = parse_key_value(args.version_field or [])
    base_description = args.description or f"mere.run artifact publish {args.run_id}"
    version = {
        "code": version_code(args, target),
        "description": base_description,
        "sg_status_list": args.status,
        "extraFields": version_fields,
    }
    if args.user_id:
        version["user"] = entity_ref("HumanUser", args.user_id)
    sha_values = [str(item.get("sha256") or item["path"]) for item in artifacts]
    if thumbnail:
        sha_values.append(str(thumbnail.get("sha256") or thumbnail["path"]))
    if not sha_values:
        sha_values.append(json.dumps(request, sort_keys=True))
    manifest: JsonMap = {
        "contractVersion": "mere.run/plugin-run.v1",
        "runId": args.run_id,
        "plugin": {"name": PLUGIN_NAME, "version": __version__},
        "recipe": {"id": "shotgrid-version-publish", "family": "production-tracking", "title": "ShotGrid Version publish"},
        "status": "planned",
        "createdAt": created,
        "updatedAt": created,
        "dataset": {
            "path": str(pathlib.Path(string_field(artifacts[0], "path", "artifact")).parent if artifacts else output_dir),
            "pairCount": max(1, len(artifacts)),
            "sha256": combined_sha256(sha_values),
        },
        "command": make_publish_command(args, command_name),
        "local": {
            "outputDirectory": str(output_dir),
            "runManifest": str(manifest_path),
            "sourceRunManifest": str(args.source_run_manifest) if args.source_run_manifest else None,
            "artifactBundle": str(args.artifact_bundle) if args.artifact_bundle else None,
        },
        "shotgrid": {
            "siteUrl": args.site_url or env_first(SHOTGRID_URL_ENV),
            "authMode": "external",
            "mode": "publish-version",
            "project": project,
            "entity": target,
            "task": task,
            "playlist": playlist,
            "version": version,
            "uploads": artifacts,
            "thumbnail": thumbnail,
            "note": {
                "subject": args.note_subject or f"Review {version['code']}",
                "content": args.note,
            } if args.note else None,
            "taskUpdate": {"sg_status_list": args.task_status} if args.task_status else None,
            "request": request,
            "plannedOperations": [],
            "resolved": {},
            "result": {"created": [], "uploads": [], "updates": []},
        },
        "artifacts": {
            "localDirectory": str(output_dir),
            "files": [item["path"] for item in artifacts],
            "thumbnail": thumbnail["path"] if thumbnail else None,
        },
        "cleanup": {"default": "none", "status": "not-started"},
    }
    shotgrid = as_map(manifest.get("shotgrid"), "manifest.shotgrid")
    shotgrid["plannedOperations"] = planned_operations(manifest)
    return manifest


def update_manifest(path: pathlib.Path, manifest: JsonMap, **updates: object) -> None:
    manifest.update(updates)
    manifest["updatedAt"] = now_iso()
    write_json(path, manifest)


def require_existing_uploads(manifest: JsonMap) -> None:
    shotgrid = as_map(manifest.get("shotgrid", {}), "manifest.shotgrid")
    for raw_item in as_list(shotgrid.get("uploads", []), "manifest.shotgrid.uploads"):
        item = as_map(raw_item, "manifest.shotgrid.uploads[]")
        path = pathlib.Path(string_field(item, "path", "upload"))
        if not path.is_file():
            raise PluginError(f"upload artifact does not exist: {path}", 2)
    thumbnail = optional_map(shotgrid.get("thumbnail"), "manifest.shotgrid.thumbnail")
    if thumbnail and not pathlib.Path(string_field(thumbnail, "path", "thumbnail")).is_file():
        raise PluginError(f"thumbnail does not exist: {thumbnail['path']}", 2)


def resolve_project(sg: ShotGridClient, project: JsonMap) -> JsonMap:
    if project.get("id"):
        return entity_ref("Project", int_value(project["id"], "project.id"))
    result = None
    if project.get("code"):
        try:
            result = sg.find_one("Project", [["code", "is", project["code"]]], ["id", "name"])
        except Exception:
            result = None
        if not result:
            result = sg.find_one("Project", [["name", "is", project["code"]]], ["id", "name"])
    elif project.get("name"):
        result = sg.find_one("Project", [["name", "is", project["name"]]], ["id", "name"])
    else:
        raise PluginError("project id, code, or name is required", 2)
    if not result:
        raise PluginError(f"ShotGrid project not found: {project}", 4)
    return entity_ref("Project", int_value(result["id"], "ShotGrid Project.id"))


def resolve_linked_entity(sg: ShotGridClient, project_ref: JsonMap, target: JsonMap | None) -> JsonMap | None:
    if not target:
        return None
    if target.get("id"):
        return entity_ref(string_field(target, "type", "target"), int_value(target["id"], "target.id"))
    target_type = string_field(target, "type", "target")
    filters: ShotGridFilters = [["project", "is", project_ref], ["code", "is", target["code"]]]
    result = sg.find_one(target_type, filters, ["id", "code"])
    if not result:
        raise PluginError(f"ShotGrid {target_type} not found by code: {target['code']}", 4)
    return entity_ref(target_type, int_value(result["id"], f"ShotGrid {target_type}.id"))


def resolve_task(sg: ShotGridClient, project_ref: JsonMap, entity: JsonMap | None, task: JsonMap | None) -> JsonMap | None:
    if not task:
        return None
    if task.get("id"):
        return entity_ref("Task", int_value(task["id"], "task.id"))
    filters: ShotGridFilters = [["project", "is", project_ref], ["content", "is", task["name"]]]
    if entity:
        filters.append(["entity", "is", entity])
    result = sg.find_one("Task", filters, ["id", "content"])
    if not result:
        raise PluginError(f"ShotGrid Task not found: {task['name']}", 4)
    return entity_ref("Task", int_value(result["id"], "ShotGrid Task.id"))


def resolve_playlist(sg: ShotGridClient, project_ref: JsonMap, playlist: JsonMap | None) -> tuple[JsonMap | None, bool]:
    if not playlist:
        return None, False
    if playlist.get("id"):
        return entity_ref("Playlist", int_value(playlist["id"], "playlist.id")), False
    result = sg.find_one("Playlist", [["project", "is", project_ref], ["code", "is", playlist["code"]]], ["id", "code"])
    if result:
        return entity_ref("Playlist", int_value(result["id"], "ShotGrid Playlist.id")), False
    if not playlist.get("createIfMissing"):
        raise PluginError(f"ShotGrid Playlist not found: {playlist['code']}", 4)
    created = sg.create("Playlist", {"project": project_ref, "code": playlist["code"]})
    return entity_ref("Playlist", int_value(created["id"], "created Playlist.id")), True


def build_version_data(manifest: JsonMap, project: JsonMap, entity: JsonMap | None, task: JsonMap | None) -> JsonMap:
    shotgrid = as_map(manifest.get("shotgrid"), "manifest.shotgrid")
    source = as_map(shotgrid.get("version"), "manifest.shotgrid.version")
    data: JsonMap = {
        "project": project,
        "code": source["code"],
        "description": source["description"],
        "sg_status_list": source["sg_status_list"],
    }
    if entity:
        data["entity"] = entity
    if task:
        data["sg_task"] = task
    if source.get("user"):
        data["user"] = source["user"]
    data.update(as_map(source.get("extraFields", {}), "manifest.shotgrid.version.extraFields"))
    return data


def upload_with_retry(sg: ShotGridClient, *, entity_type: str, entity_id: int, item: JsonMap) -> int:
    path = string_field(item, "path", "upload")
    kwargs: JsonMap = {"display_name": item.get("name") or pathlib.Path(path).name}
    if item.get("fieldName"):
        kwargs["field_name"] = item["fieldName"]
    for attempt in range(2):
        try:
            return int_value(sg.upload(entity_type, entity_id, path, **kwargs), "ShotGrid upload id")
        except Exception:
            if attempt:
                raise
            time.sleep(0.25)
    raise AssertionError("unreachable")


def record_created(manifest: JsonMap, entity: JsonMap, label: str) -> None:
    shotgrid = as_map(manifest.get("shotgrid"), "manifest.shotgrid")
    result = as_map(shotgrid.get("result"), "manifest.shotgrid.result")
    created = as_list(result.get("created"), "manifest.shotgrid.result.created")
    created.append({"type": entity["type"], "id": entity["id"], "label": label})


def execute_manifest(
    manifest_path: pathlib.Path,
    manifest: JsonMap,
    *,
    sg: ShotGridClient | None = None,
    config: ShotGridConfig | None = None,
) -> JsonMap:
    require_existing_uploads(manifest)
    if sg is None:
        sg = make_shotgrid_client(config or ShotGridConfig(None, None, None, None, None))
    update_manifest(manifest_path, manifest, status="running")
    try:
        shotgrid = as_map(manifest.get("shotgrid"), "manifest.shotgrid")
        result = as_map(shotgrid.get("result"), "manifest.shotgrid.result")
        project = resolve_project(sg, as_map(shotgrid.get("project"), "manifest.shotgrid.project"))
        entity = resolve_linked_entity(sg, project, optional_map(shotgrid.get("entity"), "manifest.shotgrid.entity"))
        task = resolve_task(sg, project, entity, optional_map(shotgrid.get("task"), "manifest.shotgrid.task"))
        playlist, playlist_created = resolve_playlist(sg, project, optional_map(shotgrid.get("playlist"), "manifest.shotgrid.playlist"))
        shotgrid["resolved"] = {
            "project": project,
            "entity": entity,
            "task": task,
            "playlist": playlist,
        }
        if playlist and playlist_created:
            record_created(manifest, playlist, "playlist")
        update_manifest(manifest_path, manifest)

        version = sg.create("Version", build_version_data(manifest, project, entity, task))
        version_ref = entity_ref("Version", int_value(version["id"], "created Version.id"))
        result["version"] = version_ref
        record_created(manifest, version_ref, "version")
        update_manifest(manifest_path, manifest)

        uploads = as_list(result.get("uploads"), "manifest.shotgrid.result.uploads")
        for raw_item in as_list(shotgrid.get("uploads", []), "manifest.shotgrid.uploads"):
            item = as_map(raw_item, "manifest.shotgrid.uploads[]")
            attachment_id = upload_with_retry(
                sg,
                entity_type="Version",
                entity_id=int_value(version_ref["id"], "Version.id"),
                item=item,
            )
            uploads.append({
                "type": "Attachment",
                "id": attachment_id,
                "path": item["path"],
                "fieldName": item.get("fieldName"),
            })
            update_manifest(manifest_path, manifest)

        thumbnail = optional_map(shotgrid.get("thumbnail"), "manifest.shotgrid.thumbnail")
        if thumbnail:
            attachment_id = int_value(
                sg.upload_thumbnail(
                    "Version",
                    int_value(version_ref["id"], "Version.id"),
                    string_field(thumbnail, "path", "thumbnail"),
                ),
                "ShotGrid thumbnail upload id",
            )
            result["thumbnail"] = {"type": "Attachment", "id": attachment_id, "path": thumbnail["path"]}
            update_manifest(manifest_path, manifest)

        note = optional_map(shotgrid.get("note"), "manifest.shotgrid.note")
        if note:
            links = [version_ref]
            for ref in (entity, task):
                if ref:
                    links.append(ref)
            note_data = {
                "project": project,
                "subject": note["subject"],
                "content": note["content"],
                "note_links": links,
            }
            created_note = sg.create("Note", note_data)
            note_ref = entity_ref("Note", int_value(created_note["id"], "created Note.id"))
            result["note"] = note_ref
            record_created(manifest, note_ref, "note")
            update_manifest(manifest_path, manifest)

        if playlist:
            sg.update(
                "Playlist",
                int_value(playlist["id"], "Playlist.id"),
                {"versions": [version_ref]},
                multi_entity_update_modes={"versions": "add"},
            )
            as_list(result.get("updates"), "manifest.shotgrid.result.updates").append({
                "type": "Playlist",
                "id": playlist["id"],
                "field": "versions",
            })
            update_manifest(manifest_path, manifest)

        task_update = optional_map(shotgrid.get("taskUpdate"), "manifest.shotgrid.taskUpdate")
        if task and task_update:
            sg.update("Task", int_value(task["id"], "Task.id"), task_update)
            as_list(result.get("updates"), "manifest.shotgrid.result.updates").append({
                "type": "Task",
                "id": task["id"],
                "fields": sorted(task_update),
            })
            update_manifest(manifest_path, manifest)

        update_manifest(manifest_path, manifest, status="succeeded")
        return manifest
    except Exception as exc:
        manifest["error"] = str(exc)
        update_manifest(manifest_path, manifest, status="failed")
        if isinstance(exc, PluginError):
            raise
        raise PluginError(f"ShotGrid publish failed: {exc}", 4) from None


def cleanup_created_records(manifest_path: pathlib.Path, manifest: JsonMap, sg: ShotGridClient) -> JsonMap:
    cleanup = as_map(
        manifest.setdefault("cleanup", {"default": "none", "status": "not-started"}),
        "manifest.cleanup",
    )
    cleanup["status"] = "attempted"
    update_manifest(manifest_path, manifest)
    deleted: list[JsonMap] = []
    shotgrid = as_map(manifest.get("shotgrid", {}), "manifest.shotgrid")
    result = as_map(shotgrid.get("result", {}), "manifest.shotgrid.result")
    created = as_list(result.get("created", []), "manifest.shotgrid.result.created")
    for raw_item in reversed(created):
        item = as_map(raw_item, "manifest.shotgrid.result.created[]")
        item_type = string_field(item, "type", "created record")
        item_id = int_value(item["id"], "created record.id")
        sg.delete(item_type, item_id)
        deleted.append({"type": item["type"], "id": item["id"]})
        cleanup["deleted"] = deleted
        update_manifest(manifest_path, manifest)
    cleanup["status"] = "succeeded"
    update_manifest(manifest_path, manifest)
    return manifest


def command_manifest(args: argparse.Namespace) -> int:
    if not args.json:
        eprint("manifest output is JSON; pass --json to make that explicit")
    print_json(plugin_manifest())
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    try:
        import shotgun_api3
        api_ok = True
        api_detail = getattr(shotgun_api3, "__version__", "installed")
    except ImportError:
        api_ok = False
        api_detail = "not installed"
    checks = [
        {"name": "python", "ok": True, "detail": sys.version.split()[0]},
        {"name": "shotgun_api3", "ok": api_ok, "detail": api_detail},
        {"name": "site-url", "ok": bool(config.site_url), "detail": config.site_url or "missing"},
        {"name": "credentials", "ok": bool(config.auth_mode), "detail": config.auth_mode or "missing"},
    ]
    if args.live and api_ok and config.site_url and config.auth_mode:
        try:
            sg = make_shotgrid_client(config)
            project = None
            if args.project_id:
                project = sg.find_one("Project", [["id", "is", args.project_id]], ["id", "name"])
            elif args.project_name:
                project = sg.find_one("Project", [["name", "is", args.project_name]], ["id", "name"])
            checks.append({"name": "live-api", "ok": True, "detail": "connected"})
            if args.project_id or args.project_name:
                checks.append({"name": "project-access", "ok": bool(project), "detail": project or "not found"})
        except Exception as exc:
            checks.append({"name": "live-api", "ok": False, "detail": str(exc)})
    ok = all(item["ok"] for item in checks) or args.allow_missing_credentials
    print_json({"ok": ok, "config": redacted_config(config), "checks": checks})
    return 0 if ok else 3


def command_plan(args: argparse.Namespace) -> int:
    manifest = make_publish_manifest(args, "plan")
    local = as_map(manifest.get("local"), "manifest.local")
    write_json(pathlib.Path(string_field(local, "runManifest", "manifest.local")), manifest)
    print_json(manifest)
    return 0


def command_publish(args: argparse.Namespace) -> int:
    manifest = make_publish_manifest(args, "publish")
    local = as_map(manifest.get("local"), "manifest.local")
    manifest_path = pathlib.Path(string_field(local, "runManifest", "manifest.local"))
    write_json(manifest_path, manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    manifest = execute_manifest(manifest_path, manifest, config=config_from_args(args))
    print_json(manifest)
    return 0


def command_run(args: argparse.Namespace) -> int:
    manifest = load_json(args.run_manifest)
    if args.dry_run:
        print_json(manifest)
        return 0
    manifest = execute_manifest(args.run_manifest, manifest, config=config_from_args(args))
    print_json(manifest)
    return 0


def command_resume(args: argparse.Namespace) -> int:
    manifest = load_json(args.run_manifest)
    shotgrid = as_map(manifest.get("shotgrid", {}), "manifest.shotgrid")
    result = as_map(shotgrid.get("result", {}), "manifest.shotgrid.result")
    payload: JsonMap = {
        "runId": manifest.get("runId"),
        "status": manifest.get("status"),
        "shotgrid": result,
        "cleanup": manifest.get("cleanup"),
    }
    if args.live:
        config = config_from_args(args)
        sg = make_shotgrid_client(config)
        version = optional_map(result.get("version"), "manifest.shotgrid.result.version")
        if version:
            payload["liveVersion"] = sg.find_one(
                "Version",
                [["id", "is", version["id"]]],
                ["id", "code", "sg_status_list", "entity", "sg_task"],
            )
    print_json(payload)
    return 0


def command_cleanup(args: argparse.Namespace) -> int:
    manifest = load_json(args.run_manifest)
    cleanup = as_map(
        manifest.setdefault("cleanup", {"default": "none", "status": "not-started"}),
        "manifest.cleanup",
    )
    if not args.delete_created_records:
        cleanup["status"] = "skipped"
        cleanup["reason"] = "ShotGrid cleanup is destructive; pass --delete-created-records with --confirm-run-id to retire plugin-created records"
        update_manifest(args.run_manifest, manifest)
        print_json(manifest)
        return 0
    if args.confirm_run_id != manifest.get("runId"):
        raise PluginError("--confirm-run-id must match the manifest runId before deleting ShotGrid records", 2)
    sg = make_shotgrid_client(config_from_args(args))
    manifest = cleanup_created_records(args.run_manifest, manifest, sg)
    print_json(manifest)
    return 0


def task_filters(args: argparse.Namespace, project: JsonMap) -> ShotGridFilters:
    filters: ShotGridFilters = [["project", "is", project]]
    if args.status:
        filters.append(["sg_status_list", "in", args.status])
    if args.assignee_id:
        filters.append(["task_assignees", "is", entity_ref("HumanUser", args.assignee_id)])
    if args.entity_type and args.entity_id:
        filters.append(["entity", "is", entity_ref(args.entity_type, args.entity_id)])
    return filters


def task_to_job(task: JsonMap, *, project: JsonMap, tool: str) -> JsonMap:
    entity = optional_map(task.get("entity"), "task.entity") or {}
    entity_label = entity.get("name") or entity.get("code") or entity.get("id") or "entity"
    prompt = f"{task.get('content') or 'Task'} for {entity.get('type') or 'Shot'} {entity_label}"
    return {
        "tool": tool,
        "inputs": {
            "prompt": prompt,
            "shotgrid": {
                "project": project,
                "task": entity_ref("Task", int_value(task["id"], "Task.id")),
                "entity": entity if isinstance(entity, dict) else None,
                "status": task.get("sg_status_list"),
            },
            "task": task,
        },
        "options": {"source": "shotgrid"},
    }


def pull_tasks(args: argparse.Namespace, *, sg: ShotGridClient | None = None, config: ShotGridConfig | None = None) -> JsonMap:
    if sg is None:
        sg = make_shotgrid_client(config or config_from_args(args))
    project = resolve_project(sg, project_target(args, {}))
    fields = ["id", "content", "entity", "project", "sg_status_list", "step", "task_assignees", "description"]
    tasks = sg.find("Task", task_filters(args, project), fields, limit=args.limit)
    jobs = [task_to_job(task, project=project, tool=args.tool) for task in tasks]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(job, sort_keys=True) + "\n" for job in jobs))
    return {
        "ok": True,
        "project": project,
        "count": len(jobs),
        "output": str(args.output),
        "tool": args.tool,
    }


def command_pull_tasks(args: argparse.Namespace) -> int:
    print_json(pull_tasks(args))
    return 0


def add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env-file", type=pathlib.Path)
    parser.add_argument("--site-url")
    parser.add_argument("--script-name")
    parser.add_argument("--api-key")
    parser.add_argument("--login")
    parser.add_argument("--password")


def add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--project-code")
    parser.add_argument("--project-name")
    parser.add_argument("--entity-type")
    parser.add_argument("--entity-id", type=int)
    parser.add_argument("--entity-code")
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--task-name")


def add_publish_args(parser: argparse.ArgumentParser) -> None:
    add_config_args(parser)
    add_target_args(parser)
    parser.add_argument("--request-json", type=pathlib.Path)
    parser.add_argument("--source-run-manifest", type=pathlib.Path)
    parser.add_argument("--artifact-bundle", type=pathlib.Path)
    parser.add_argument("--artifact", action="append", type=pathlib.Path, default=[])
    parser.add_argument("--thumbnail", type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--manifest", type=pathlib.Path)
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--version-code")
    parser.add_argument("--description")
    parser.add_argument("--status", default="rev")
    parser.add_argument("--note")
    parser.add_argument("--note-subject")
    parser.add_argument("--playlist-id", type=int)
    parser.add_argument("--playlist-code")
    parser.add_argument("--create-playlist", action="store_true")
    parser.add_argument("--task-status")
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--version-field", action="append", default=[])
    parser.add_argument("--review-upload-field", default="sg_uploaded_movie")
    parser.add_argument("--no-review-upload-field", action="store_true")
    parser.add_argument("--allow-missing-artifacts", action="store_true")


def normalize_paths(args: argparse.Namespace) -> argparse.Namespace:
    for name in (
        "env_file",
        "request_json",
        "source_run_manifest",
        "artifact_bundle",
        "thumbnail",
        "output_dir",
        "manifest",
        "run_manifest",
        "output",
    ):
        if hasattr(args, name):
            value = getattr(args, name)
            if value is not None:
                setattr(args, name, value.expanduser().resolve())
    if hasattr(args, "artifact") and args.artifact:
        args.artifact = [path.expanduser().resolve() for path in args.artifact]
    if hasattr(args, "run_id"):
        validate_run_id(args.run_id)
    if getattr(args, "no_review_upload_field", False):
        args.review_upload_field = None
    if hasattr(args, "output_dir") and getattr(args, "manifest", None) is None:
        args.manifest = default_manifest_path(args.output_dir).resolve()
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mere-shotgrid-tools")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="Print plugin manifest.")
    manifest.add_argument("--json", action="store_true")
    manifest.set_defaults(func=command_manifest)

    doctor = sub.add_parser("doctor", help="Check local ShotGrid readiness.")
    add_config_args(doctor)
    doctor.add_argument("--live", action="store_true")
    doctor.add_argument("--allow-missing-credentials", action="store_true")
    doctor.add_argument("--project-id", type=int)
    doctor.add_argument("--project-name")
    doctor.set_defaults(func=command_doctor)

    plan = sub.add_parser("plan", help="Create a ShotGrid publish plan.")
    add_publish_args(plan)
    plan.set_defaults(func=command_plan)

    run = sub.add_parser("run", help="Execute a planned ShotGrid publish manifest.")
    add_config_args(run)
    run.add_argument("run_manifest", type=pathlib.Path)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run)

    resume = sub.add_parser("resume", help="Inspect a ShotGrid publish manifest.")
    add_config_args(resume)
    resume.add_argument("run_manifest", type=pathlib.Path)
    resume.add_argument("--live", action="store_true")
    resume.set_defaults(func=command_resume)

    cleanup = sub.add_parser("cleanup", help="Skip cleanup or retire plugin-created records.")
    add_config_args(cleanup)
    cleanup.add_argument("run_manifest", type=pathlib.Path)
    cleanup.add_argument("--delete-created-records", action="store_true")
    cleanup.add_argument("--confirm-run-id")
    cleanup.set_defaults(func=command_cleanup)

    publish = sub.add_parser("publish", help="Plan and run a ShotGrid Version publish.")
    add_publish_args(publish)
    publish.add_argument("--dry-run", action="store_true")
    publish.set_defaults(func=command_publish)

    pull = sub.add_parser("pull-tasks", help="Query ShotGrid Tasks into JSONL jobs.")
    add_config_args(pull)
    pull.add_argument("--output", required=True, type=pathlib.Path)
    pull.add_argument("--tool", default="shot-kit")
    pull.add_argument("--limit", type=int, default=50)
    pull.add_argument("--status", action="append", default=[])
    pull.add_argument("--assignee-id", type=int)
    pull.add_argument("--project-id", type=int)
    pull.add_argument("--project-code")
    pull.add_argument("--project-name")
    pull.add_argument("--entity-type")
    pull.add_argument("--entity-id", type=int)
    pull.set_defaults(func=command_pull_tasks)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args = normalize_paths(args)
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

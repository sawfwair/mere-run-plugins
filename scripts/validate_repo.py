#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import NoReturn, cast

from jsonschema import Draft202012Validator, FormatChecker

ROOT = pathlib.Path(__file__).resolve().parents[1]
JsonMap = dict[str, object]
JsonList = list[object]


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def as_map(value: object, label: str) -> JsonMap:
    if isinstance(value, dict):
        return cast(JsonMap, value)
    fail(f"{label}: expected object")


def as_list(value: object, label: str) -> JsonList:
    if isinstance(value, list):
        return value
    fail(f"{label}: expected list")


def load_json(path: pathlib.Path) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), str(path))
    except json.JSONDecodeError as exc:
        fail(f"{path}: invalid JSON: {exc}")


def validate_schema(path: pathlib.Path, schema: JsonMap, payload: JsonMap) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "$"
        fail(f"{path}: schema validation failed at {location}: {error.message}")


def contract_schema(name: str) -> JsonMap:
    return load_json(ROOT / "contracts" / name)


def require_keys(path: pathlib.Path, payload: JsonMap, keys: list[str]) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        fail(f"{path}: missing keys: {', '.join(missing)}")


def validate_contracts() -> None:
    for path in sorted((ROOT / "contracts").glob("*.json")):
        payload = load_json(path)
        require_keys(path, payload, ["$schema", "$id", "title", "type"])
        try:
            Draft202012Validator.check_schema(payload)
        except Exception as exc:
            fail(f"{path}: invalid JSON schema: {exc}")


def validate_recipes() -> None:
    required = [
        "contractVersion",
        "id",
        "family",
        "models",
        "dataset",
        "captioning",
        "training",
        "evaluation",
    ]
    seen: set[str] = set()
    schema = contract_schema("recipe.v1.schema.json")
    for path in sorted((ROOT / "recipes").glob("*.json")):
        recipe = load_json(path)
        validate_schema(path, schema, recipe)
        require_keys(path, recipe, required)
        if recipe["contractVersion"] != "mere.run/recipe.v1":
            fail(f"{path}: wrong contractVersion")
        recipe_id = str(recipe["id"])
        models = as_map(recipe["models"], f"{path}: models")
        captioning = as_map(recipe["captioning"], f"{path}: captioning")
        if recipe_id in seen:
            fail(f"{path}: duplicate recipe id {recipe_id}")
        seen.add(recipe_id)
        if models["train"] != "image-klein-base-9b":
            fail(f"{path}: Klein LoRA recipes must train on image-klein-base-9b")
        if models["apply"] != "image-klein-9b":
            fail(f"{path}: Klein LoRA recipes must apply on image-klein-9b")
        if "same " in " ".join(str(item) for item in as_list(captioning.get("examples", []), f"{path}: examples")).lower():
            fail(f"{path}: caption examples should not use same/previous phrasing")
        package_path = ROOT / "packages" / "mere-runpod" / "src" / "mere_runpod" / "recipes" / path.name
        if not package_path.is_file():
            fail(f"{package_path}: bundled recipe missing")
        if load_json(package_path) != recipe:
            fail(f"{package_path}: bundled recipe does not match {path}")


def validate_eval_recipes() -> None:
    schema = contract_schema("eval-recipe.v1.schema.json")
    seen: set[str] = set()
    for path in sorted((ROOT / "eval-recipes").glob("*.json")):
        recipe = load_json(path)
        validate_schema(path, schema, recipe)
        recipe_id = str(recipe["id"])
        models = as_map(recipe["models"], f"{path}: models")
        if recipe_id in seen:
            fail(f"{path}: duplicate eval recipe id {recipe_id}")
        seen.add(recipe_id)
        if models["apply"] != "image-klein-9b":
            fail(f"{path}: Klein eval recipes must apply on image-klein-9b")
        serialized = json.dumps(recipe)
        if "/Users/" in serialized:
            fail(f"{path}: public eval recipe must not contain workstation paths")


def validate_catalog() -> None:
    path = ROOT / "catalog" / "plugins.v1.json"
    catalog = load_json(path)
    validate_schema(path, contract_schema("catalog.v1.schema.json"), catalog)
    require_keys(path, catalog, ["contractVersion", "defaultChannel", "plugins"])
    if catalog["contractVersion"] != "mere.run/plugin-catalog.v1":
        fail(f"{path}: wrong contractVersion")
    seen: set[str] = set()
    default_channel = str(catalog["defaultChannel"])
    for raw_plugin in as_list(catalog["plugins"], f"{path}: plugins"):
        plugin = as_map(raw_plugin, f"{path}: plugin")
        require_keys(path, plugin, ["id", "entrypoint", "channels"])
        plugin_id = str(plugin["id"])
        channels = as_map(plugin["channels"], f"{path}: {plugin_id}.channels")
        if plugin_id in seen:
            fail(f"{path}: duplicate plugin id {plugin_id}")
        seen.add(plugin_id)
        if default_channel not in channels:
            fail(f"{path}: {plugin_id} missing default channel {default_channel}")
        install = as_map(channels[default_channel], f"{path}: {plugin_id}.{default_channel}")
        if install["manager"] != "pipx":
            fail(f"{path}: only pipx installs are currently supported")
        if "#subdirectory=" not in str(install["spec"]):
            fail(f"{path}: install spec should pin a package subdirectory")
        package_dir = ROOT / str(plugin["subdirectory"])
        if not package_dir.is_dir():
            fail(f"{path}: plugin subdirectory does not exist: {plugin['subdirectory']}")
        if not (package_dir / "pyproject.toml").is_file():
            fail(f"{path}: plugin subdirectory missing pyproject.toml: {plugin['subdirectory']}")


def plugin_env() -> dict[str, str]:
    env = dict(**os.environ)
    package_paths = [
        ROOT / "packages" / "mere-runpod" / "src",
        ROOT / "packages" / "mere-image-tools" / "src",
        ROOT / "packages" / "mere-face-tools" / "src",
        ROOT / "packages" / "mere-workflow-tools" / "src",
        ROOT / "packages" / "mere-animatic-tools" / "src",
        ROOT / "packages" / "mere-shotgrid-tools" / "src",
        ROOT / "packages" / "mere-perform" / "src",
        ROOT / "packages" / "mere-vfx-tools" / "src",
    ]
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in package_paths)
    return env


def write_dataset(path: pathlib.Path, count: int) -> None:
    path.mkdir()
    for index in range(1, count + 1):
        stem = f"{index:03d}"
        (path / f"{stem}.png").write_bytes(b"not-a-real-image-but-plan-only")
        (path / f"{stem}.txt").write_text("testtrigger, a test image\n")


def validate_plugin_manifest(module: str, executable: str, required_commands: set[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", module, "manifest", "--json"],
        cwd=ROOT,
        env=plugin_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    manifest = json.loads(result.stdout)
    validate_schema(pathlib.Path(f"{executable} manifest"), contract_schema("plugin.v1.schema.json"), manifest)
    require_keys(
        pathlib.Path(f"{executable} manifest"),
        manifest,
        ["contractVersion", "name", "version", "commands", "security"],
    )
    if manifest["executable"] != executable:
        fail(f"{executable} manifest reported executable {manifest['executable']}")
    command_names = {command["name"] for command in manifest["commands"]}
    for required in required_commands:
        if required not in command_names:
            fail(f"{executable} manifest missing command {required}")


def validate_plugin_manifests() -> None:
    validate_plugin_manifest(
        "mere_runpod",
        "mere-runpod",
        {"manifest", "doctor", "volume", "plan", "run", "resume", "cleanup"},
    )
    validate_plugin_manifest(
        "mere_image_tools",
        "mere-image-tools",
        {"manifest", "doctor", "plan", "run", "resume", "cleanup", "knockout"},
    )
    validate_plugin_manifest(
        "mere_face_tools",
        "mere-face-tools",
        {"manifest", "doctor", "plan", "run", "resume", "cleanup", "index", "search"},
    )
    validate_plugin_manifest(
        "mere_animatic_tools",
        "mere-animatic-tools",
        {
            "manifest",
            "doctor",
            "plan",
            "run",
            "resume",
            "cleanup",
            "character-knockout",
            "reference-pack",
            "continuity-check",
            "shot-kit",
            "storyboard-repair",
            "edit-doctor",
            "actor-voice-kit",
            "location-plates",
            "style-lock",
            "delivery-prep",
        },
    )
    validate_plugin_manifest(
        "mere_shotgrid_tools",
        "mere-shotgrid-tools",
        {"manifest", "doctor", "plan", "run", "resume", "cleanup", "publish", "pull-tasks"},
    )
    validate_plugin_manifest(
        "mere_perform",
        "mere-perform",
        {"manifest", "doctor", "plan", "run", "resume", "cleanup", "stage", "devices", "show-template", "perform"},
    )
    validate_plugin_manifest(
        "mere_vfx_tools",
        "mere-vfx-tools",
        {
            "manifest", "doctor", "plan", "run", "resume", "cleanup", "roto", "matte-refine",
            "track-export", "key", "shot-qc", "inbetween", "turntable", "character-sheet",
            "pose-sequence",
            "motion-pass",
            "clean-plate",
            "set-extension", "restore",
            "depth-normal",
            "relight",
            "video-depth",
            "multiview-geometry",
            "image-to-3d",
            "multiview-image-to-3d",
        },
    )
    workflow_tools = [
        ("mere_workflow_tools.doc_cli", "mere-doc-tools", "process"),
        ("mere_workflow_tools.media_cli", "mere-media-scrub", "scrub"),
        ("mere_workflow_tools.dataset_cli", "mere-dataset-tools", "caption"),
        ("mere_workflow_tools.transcript_cli", "mere-transcript-tools", "transcribe"),
        ("mere_workflow_tools.image_compose_cli", "mere-image-compose", "generate"),
        ("mere_workflow_tools.batch_cli", "mere-batch-runner", "run-jobs"),
    ]
    for module, executable, one_shot in workflow_tools:
        validate_plugin_manifest(
            module,
            executable,
            {"manifest", "doctor", "plan", "run", "resume", "cleanup", one_shot},
        )


def validate_graph_provider() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mere_workflow_tools.dataset_cli", "graph", "catalog", "--json"],
        cwd=ROOT,
        env=plugin_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    catalog = as_map(json.loads(result.stdout), "mere-dataset-tools graph catalog")
    validate_schema(
        pathlib.Path("mere-dataset-tools graph catalog"),
        contract_schema("graph-node-provider.v1.schema.json"),
        catalog,
    )
    if catalog["provider_id"] != "mere-dataset-tools":
        fail("dataset graph provider reported the wrong provider id")
    nodes = as_list(catalog["nodes"], "dataset graph nodes")
    if len(nodes) != 1 or as_map(nodes[0], "dataset graph node")["kind"] != "dataset.prepare":
        fail("dataset graph provider must expose dataset.prepare")


def validate_runpod_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        dataset = root / "dataset"
        output = root / "run"
        write_dataset(dataset, 16)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mere_runpod",
                "plan",
                "--recipe",
                "klein-style-lora",
                "--data",
                str(dataset),
                "--output",
                str(output),
                "--run-id",
                "validate-plan",
            ],
            cwd=ROOT,
            env=plugin_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        manifest = json.loads(result.stdout)
        validate_schema(pathlib.Path("mere-runpod plan"), contract_schema("run-manifest.v1.schema.json"), manifest)
        if manifest["status"] != "planned":
            fail("plan manifest should have status planned")
        if manifest["dataset"]["pairCount"] != 16:
            fail("plan manifest should count 16 dataset pairs")
        if not (output / "run.json").is_file():
            fail("plan should write run.json")
        if "--recipe" not in manifest["command"] or "klein-fast-style" not in manifest["command"]:
            fail("style recipe command should use the current Klein training preset")
        if "--sample-model" not in manifest["command"] or "image-klein-9b" not in manifest["command"]:
            fail("style recipe command should sample against image-klein-9b")


def validate_image_tools_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        source = root / "frame.png"
        output = root / "subject.png"
        source.write_bytes(b"not-a-real-image-but-plan-only")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mere_image_tools",
                "plan",
                "--input",
                str(source),
                "--output",
                str(output),
                "--run-id",
                "validate-knockout",
                "--mere-run-command",
                "fake-mere-run",
            ],
            cwd=ROOT,
            env=plugin_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        manifest = json.loads(result.stdout)
        validate_schema(pathlib.Path("mere-image-tools plan"), contract_schema("run-manifest.v1.schema.json"), manifest)
        if manifest["status"] != "planned":
            fail("image-tools plan manifest should have status planned")
        if manifest["tool"]["name"] != "knockout":
            fail("image-tools plan should record knockout tool")
        if manifest["tool"]["backend"] != "mere.run/vision-segment":
            fail("image-tools plan should call mere.run vision segment")
        if manifest["cleanup"]["default"] != "none":
            fail("image-tools cleanup default should be none")
        if not (root / "subject.run.json").is_file():
            fail("image-tools plan should write default run manifest")


def validate_face_tools_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        photos = root / "photos"
        photos.mkdir()
        (photos / "face.jpg").write_bytes(b"not-a-real-image-but-plan-only")
        database = root / "faces.sqlite3"
        output = root / "face-index"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mere_face_tools",
                "plan",
                "--photos",
                str(photos),
                "--database",
                str(database),
                "--output-dir",
                str(output),
                "--run-id",
                "validate-face-index",
                "--mere-run-command",
                "fake-mere-run",
            ],
            cwd=ROOT,
            env=plugin_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        manifest = json.loads(result.stdout)
        validate_schema(pathlib.Path("mere-face-tools plan"), contract_schema("run-manifest.v1.schema.json"), manifest)
        if manifest["status"] != "planned":
            fail("face-tools plan manifest should have status planned")
        if manifest["tool"]["backend"] != "mere.run/vision-face-batch":
            fail("face-tools plan should call mere.run vision face batch")
        if manifest["dataset"]["pairCount"] != 1:
            fail("face-tools plan should count supported photos")
        if not (output / "run.json").is_file():
            fail("face-tools plan should write run.json")


def validate_workflow_tools_plans() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        image = root / "scan.png"
        image.write_bytes(b"fake")
        frames = root / "frames"
        frames.mkdir()
        (frames / "001.png").write_bytes(b"fake")
        audio = root / "meeting.wav"
        audio.write_bytes(b"fake wav")
        jobs = root / "jobs.jsonl"
        jobs.write_text(json.dumps({
            "argv": ["text", "anonymize", "--output", str(root / "batch.txt")],
            "outputs": {"text": str(root / "batch.txt")},
        }) + "\n")
        cases = [
            (
                "mere_workflow_tools.doc_cli",
                "mere-doc-tools",
                ["plan", "--input", str(image), "--output-dir", str(root / "doc")],
            ),
            (
                "mere_workflow_tools.media_cli",
                "mere-media-scrub",
                ["plan", "--input", str(frames), "--output-dir", str(root / "media")],
            ),
            (
                "mere_workflow_tools.dataset_cli",
                "mere-dataset-tools",
                ["plan", "--input", str(frames), "--output-dir", str(root / "dataset"), "--trigger-token", "STYLE"],
            ),
            (
                "mere_workflow_tools.transcript_cli",
                "mere-transcript-tools",
                ["plan", "--input", str(audio), "--output-dir", str(root / "transcript")],
            ),
            (
                "mere_workflow_tools.image_compose_cli",
                "mere-image-compose",
                ["plan", "--prompt", "a local image", "--output-dir", str(root / "image")],
            ),
            (
                "mere_workflow_tools.batch_cli",
                "mere-batch-runner",
                ["plan", "--jobs", str(jobs), "--output-dir", str(root / "batch")],
            ),
        ]
        for module, executable, args in cases:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    module,
                    *args,
                    "--run-id",
                    f"validate-{executable}",
                    "--mere-run-command",
                    "fake-mere-run",
                ],
                cwd=ROOT,
                env=plugin_env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            manifest = json.loads(result.stdout)
            validate_schema(pathlib.Path(f"{executable} plan"), contract_schema("run-manifest.v1.schema.json"), manifest)
            if manifest["plugin"]["name"] != executable:
                fail(f"{executable} plan reported plugin {manifest['plugin']['name']}")
            if manifest["status"] != "planned":
                fail(f"{executable} plan manifest should have status planned")
            if manifest["tool"]["backend"] != "mere.run":
                fail(f"{executable} plan should call mere.run")
            if not pathlib.Path(manifest["local"]["runManifest"]).is_file():
                fail(f"{executable} plan should write run manifest")


def validate_animatic_tools_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        request = root / "request.json"
        request.write_text(json.dumps({"inputs": {"prompt": "validate a short animatic beat"}}))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mere_animatic_tools",
                "plan",
                "--tool",
                "shot-kit",
                "--request-json",
                str(request),
                "--output-dir",
                str(root / "animatic"),
                "--run-id",
                "validate-animatic-tools",
            ],
            cwd=ROOT,
            env=plugin_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        manifest = json.loads(result.stdout)
        validate_schema(pathlib.Path("mere-animatic-tools plan"), contract_schema("run-manifest.v1.schema.json"), manifest)
        if manifest["plugin"]["name"] != "mere-animatic-tools":
            fail("animatic tools plan reported wrong plugin name")
        if manifest["status"] != "planned":
            fail("animatic tools plan manifest should have status planned")
        if manifest["tool"]["name"] != "shot-kit":
            fail("animatic tools plan should record requested tool")
        if not (root / "animatic" / "run.json").is_file():
            fail("animatic tools plan should write run manifest")


def validate_shotgrid_tools_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        review = root / "review.mov"
        output = root / "shotgrid"
        review.write_bytes(b"not-a-real-movie-but-plan-only")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mere_shotgrid_tools",
                "plan",
                "--project-id",
                "123",
                "--entity-type",
                "Shot",
                "--entity-id",
                "456",
                "--artifact",
                str(review),
                "--output-dir",
                str(output),
                "--run-id",
                "validate-shotgrid",
            ],
            cwd=ROOT,
            env=plugin_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        manifest = json.loads(result.stdout)
        validate_schema(pathlib.Path("mere-shotgrid-tools plan"), contract_schema("run-manifest.v1.schema.json"), manifest)
        if manifest["plugin"]["name"] != "mere-shotgrid-tools":
            fail("shotgrid-tools plan reported wrong plugin name")
        if manifest["status"] != "planned":
            fail("shotgrid-tools plan manifest should have status planned")
        if manifest["shotgrid"]["version"]["code"] != "Shot_456_validate-shotgrid":
            fail("shotgrid-tools plan should derive a stable Version code")
        if manifest["shotgrid"]["uploads"][0]["fieldName"] != "sg_uploaded_movie":
            fail("shotgrid-tools movie upload should plan sg_uploaded_movie field")
        if not (output / "run.json").is_file():
            fail("shotgrid-tools plan should write run manifest")


def validate_perform_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        show = root / "show.json"
        output = root / "perform"
        show.write_text(json.dumps({
            "contractVersion": "mere.run/perform-show.v1",
            "title": "Validate Heart",
            "durationSeconds": 0.2,
            "promptStrategy": {"resetAfterPrompt": True, "promptDebounceMs": 0},
            "midi": {
                "noteOffset": 7,
                "keyboard": {"enabled": True, "baseNote": 60, "octaveRange": 2},
                "gate": {"enabled": True, "releaseMs": 800},
                "pads": [{"id": "pad-one", "label": "1", "sceneId": "one"}],
                "activity": {"demoNotes": [60, 64, 67]},
            },
            "prompts": [{"id": "pulse", "role": "texture", "mode": "jam", "text": "drumless glassy arpeggios", "x": 0.5, "y": 0.2, "cfgMusicCoCa": 2.4}],
            "scenes": [{"id": "one", "durationSeconds": 0.2, "promptId": "pulse"}],
        }))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mere_perform",
                "plan",
                "--show",
                str(show),
                "--output-dir",
                str(output),
                "--run-id",
                "validate-perform",
                "--mere-run-command",
                "fake-mere-run",
                "--no-play",
            ],
            cwd=ROOT,
            env=plugin_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        manifest = json.loads(result.stdout)
        validate_schema(pathlib.Path("mere-perform plan"), contract_schema("run-manifest.v1.schema.json"), manifest)
        if manifest["plugin"]["name"] != "mere-perform":
            fail("perform plan reported wrong plugin name")
        if manifest["status"] != "planned":
            fail("perform plan manifest should have status planned")
        if manifest["runtime"]["backend"] != "mere.run/music-realtime":
            fail("perform plan should call mere.run music realtime")
        if "--no-play" not in manifest["command"]:
            fail("perform plan should preserve no-play capture mode")
        if "--midi-note-offset" not in manifest["command"]:
            fail("perform plan should pass native MIDI note offset")
        show_payload = as_map(as_map(manifest["performance"], "performance")["show"], "perform show")
        midi = as_map(show_payload["midi"], "perform midi")
        if midi["noteOffset"] != 7:
            fail("perform plan should preserve MIDI note offset")
        if as_map(midi["keyboard"], "perform midi keyboard")["baseNote"] != 60:
            fail("perform plan should preserve MIDI keyboard base note")
        if as_map(midi["gate"], "perform midi gate")["releaseMs"] != 800:
            fail("perform plan should preserve MIDI gate release")
        scene = as_map(as_list(show_payload["scenes"], "perform scenes")[0], "perform scene")
        if scene["promptId"] != "pulse":
            fail("perform plan should preserve promptId scene references")
        if scene["cfgMusicCoCa"] != 2.4:
            fail("perform plan should inherit prompt strength from prompt anchors")
        if not (output / "run.json").is_file():
            fail("perform plan should write run manifest")


def validate_vfx_tools_plan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        frames = root / "frames"
        frames.mkdir()
        (frames / "frame.png").write_bytes(b"plan-only")
        request = root / "request.json"
        request.write_text(json.dumps({"inputs": {"masks": str(frames)}, "options": {"featherRadius": 1.5}}))
        output = root / "vfx"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mere_vfx_tools",
                "plan",
                "--tool",
                "matte-refine",
                "--request-json",
                str(request),
                "--output-dir",
                str(output),
                "--run-id",
                "validate-vfx-tools",
                "--mere-run-command",
                "fake-mere-run",
                "--ffmpeg-command",
                "fake-ffmpeg",
            ],
            cwd=ROOT,
            env=plugin_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        manifest = json.loads(result.stdout)
        validate_schema(pathlib.Path("mere-vfx-tools plan"), contract_schema("run-manifest.v1.schema.json"), manifest)
        if manifest["plugin"]["name"] != "mere-vfx-tools":
            fail("vfx tools plan reported wrong plugin name")
        if manifest["tool"]["name"] != "matte-refine":
            fail("vfx tools plan reported wrong workflow")
        if manifest["status"] != "planned":
            fail("vfx tools plan should have planned status")
        if not (output / "run.json").is_file():
            fail("vfx tools plan should write run manifest")


def validate_volume_dry_run() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mere_runpod",
            "volume",
            "ensure",
            "--name",
            "mere-klein-cache",
            "--data-center-id",
            "US-KS-2",
            "--size-gb",
            "512",
            "--dry-run",
            "--env-file",
            "/tmp/mere-runpod-missing-env",
        ],
        cwd=ROOT,
        env=plugin_env(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(result.stdout)
    if payload.get("dryRun") is not True:
        fail("volume ensure --dry-run should report dryRun true")
    if payload.get("createsPaidResource") is not True:
        fail("volume ensure --dry-run should declare paid-resource behavior")
    if payload.get("request", {}).get("dataCenterId") != "US-KS-2":
        fail("volume ensure --dry-run should include the planned data center")


def main() -> int:
    validate_contracts()
    validate_catalog()
    validate_recipes()
    validate_eval_recipes()
    validate_plugin_manifests()
    validate_graph_provider()
    validate_runpod_plan()
    validate_image_tools_plan()
    validate_face_tools_plan()
    validate_workflow_tools_plans()
    validate_animatic_tools_plan()
    validate_shotgrid_tools_plan()
    validate_perform_plan()
    validate_vfx_tools_plan()
    validate_volume_dry_run()
    sys.stdout.write("validate_repo: ok\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

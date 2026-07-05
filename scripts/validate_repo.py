#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker


ROOT = pathlib.Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(message)


def load_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"{path}: invalid JSON: {exc}")


def validate_schema(path: pathlib.Path, schema: dict, payload: dict) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "$"
        fail(f"{path}: schema validation failed at {location}: {error.message}")


def contract_schema(name: str) -> dict:
    return load_json(ROOT / "contracts" / name)


def require_keys(path: pathlib.Path, payload: dict, keys: list[str]) -> None:
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
        if recipe["id"] in seen:
            fail(f"{path}: duplicate recipe id {recipe['id']}")
        seen.add(recipe["id"])
        if recipe["models"]["train"] != "image-klein-base-9b":
            fail(f"{path}: Klein LoRA recipes must train on image-klein-base-9b")
        if recipe["models"]["apply"] != "image-klein-9b":
            fail(f"{path}: Klein LoRA recipes must apply on image-klein-9b")
        if "same " in " ".join(recipe["captioning"].get("examples", [])).lower():
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
        if recipe["id"] in seen:
            fail(f"{path}: duplicate eval recipe id {recipe['id']}")
        seen.add(recipe["id"])
        if recipe["models"]["apply"] != "image-klein-9b":
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
    for plugin in catalog["plugins"]:
        require_keys(path, plugin, ["id", "entrypoint", "channels"])
        if plugin["id"] in seen:
            fail(f"{path}: duplicate plugin id {plugin['id']}")
        seen.add(plugin["id"])
        if catalog["defaultChannel"] not in plugin["channels"]:
            fail(f"{path}: {plugin['id']} missing default channel {catalog['defaultChannel']}")
        install = plugin["channels"][catalog["defaultChannel"]]
        if install["manager"] != "pipx":
            fail(f"{path}: only pipx installs are currently supported")
        if "#subdirectory=" not in install["spec"]:
            fail(f"{path}: install spec should pin a package subdirectory")
        package_dir = ROOT / plugin["subdirectory"]
        if not package_dir.is_dir():
            fail(f"{path}: plugin subdirectory does not exist: {plugin['subdirectory']}")
        if not (package_dir / "pyproject.toml").is_file():
            fail(f"{path}: plugin subdirectory missing pyproject.toml: {plugin['subdirectory']}")


def plugin_env() -> dict[str, str]:
    env = dict(**os.environ)
    package_paths = [
        ROOT / "packages" / "mere-runpod" / "src",
        ROOT / "packages" / "mere-image-tools" / "src",
        ROOT / "packages" / "mere-shotgrid-tools" / "src",
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
        "mere_shotgrid_tools",
        "mere-shotgrid-tools",
        {"manifest", "doctor", "plan", "run", "resume", "cleanup", "publish", "pull-tasks"},
    )


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
    validate_runpod_plan()
    validate_image_tools_plan()
    validate_shotgrid_tools_plan()
    validate_volume_dry_run()
    print("validate_repo: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

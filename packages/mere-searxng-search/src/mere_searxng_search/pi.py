from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import uuid
from typing import cast


class PiError(RuntimeError):
    pass


LINK_NAME = "mere-searxng-search.ts"
SOURCE_SUFFIX = ("mere_searxng_search", "resources", "pi", "extensions", "searxng-search.ts")


def agent_extension_directory() -> pathlib.Path:
    command = shutil.which("mere.run")
    if not command:
        raise PiError("mere.run is not on PATH; install it before enabling the Pi tool")
    try:
        result = subprocess.run([command, "agent", "status", "--json"], capture_output=True,
                                text=True, timeout=15, check=True)
        status = json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as error:
        raise PiError("could not read mere.run agent status --json") from error
    if not isinstance(status, dict) or not isinstance(status.get("provider"), dict):
        raise PiError("mere.run agent status has no provider settings")
    provider = cast(dict[str, object], status["provider"])
    raw_path = provider.get("extensionPath")
    if not isinstance(raw_path, str) or not raw_path:
        raise PiError("mere.run agent status has no Pi extension path")
    path = pathlib.Path(raw_path).expanduser()
    if not path.is_absolute() or path.name != "mere-run-local-provider.ts" or path.parent.name != "extensions" or path.parent.parent.name != "agent" or path.parent.parent.parent.name != ".pi":
        raise PiError("mere.run reported an unexpected Pi extension path")
    return path.parent


def is_ours(link: pathlib.Path) -> bool:
    if not link.is_symlink():
        return False
    target = pathlib.Path(os.readlink(link))
    return target.is_absolute() and tuple(target.parts[-len(SOURCE_SUFFIX):]) == SOURCE_SUFFIX


def manage(action: str, source: pathlib.Path, directory: pathlib.Path | None = None) -> dict[str, object]:
    if not source.is_file():
        raise PiError("bundled Pi extension is missing")
    directory = directory or agent_extension_directory()
    link = directory / LINK_NAME
    if action == "enable":
        directory.mkdir(parents=True, exist_ok=True)
        if (link.exists() or link.is_symlink()) and not is_ours(link):
            raise PiError("Pi extension path is occupied by a file this plugin does not own")
        temporary = directory / f".{LINK_NAME}.{uuid.uuid4().hex}"
        try:
            temporary.symlink_to(source)
            os.replace(temporary, link)
        finally:
            if temporary.is_symlink():
                temporary.unlink()
    elif action == "disable":
        if (link.exists() or link.is_symlink()) and not is_ours(link):
            raise PiError("Pi extension path is occupied by a file this plugin does not own")
        if link.is_symlink():
            link.unlink()
    elif action != "status":
        raise PiError("unknown Pi action")
    return {"enabled": is_ours(link) and link.resolve() == source.resolve(),
            "extensionPath": str(link), "sourcePath": str(source)}

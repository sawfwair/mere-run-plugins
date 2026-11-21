"""Resolve the local mere.run executable for workflow commands."""

import os
import pathlib
import shlex
import shutil


def runtime_command() -> list[str]:
    override = os.environ.get("MERE_WORKFLOW_TOOLS_MERE_RUN")
    if override:
        return shlex.split(override)
    executable = os.environ.get("MERE_RUN_EXECUTABLE") or shutil.which("mere.run")
    if executable:
        return [executable]
    mac_app = pathlib.Path("/Applications/MereRun.app/Contents/Helpers/mere.run")
    return [str(mac_app)] if mac_app.is_file() else ["mere.run"]

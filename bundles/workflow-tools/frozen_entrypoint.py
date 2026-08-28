"""Dispatch only the reviewed plugin modules inside the frozen runtime."""
from __future__ import annotations

import importlib
import sys

MODULES = {
    "mere_workflow_tools.doc_cli",
    "mere_workflow_tools.media_cli",
    "mere_workflow_tools.dataset_cli",
    "mere_workflow_tools.transcript_cli",
    "mere_workflow_tools.image_compose_cli",
    "mere_workflow_tools.batch_cli",
    "mere_workflow_tools.identity_cli",
}

if len(sys.argv) < 2 or sys.argv[1] not in MODULES:
    raise SystemExit("Run a bundled mere-* entrypoint.")
sys.dont_write_bytecode = True
module = importlib.import_module(sys.argv.pop(1))
raise SystemExit(module.main())

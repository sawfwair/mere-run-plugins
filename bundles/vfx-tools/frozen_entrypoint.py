"""Dispatch only the reviewed plugin modules inside the frozen runtime."""
from __future__ import annotations

import importlib
import sys

MODULES = {"mere_vfx_tools.cli"}

if len(sys.argv) < 2 or sys.argv[1] not in MODULES:
    raise SystemExit("Run a bundled mere-* entrypoint.")
sys.dont_write_bytecode = True
module = importlib.import_module(sys.argv.pop(1))
raise SystemExit(module.main())

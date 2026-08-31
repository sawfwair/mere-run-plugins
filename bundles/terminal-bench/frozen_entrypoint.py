"""Dispatch only the reviewed plugin module inside the frozen runtime."""
from __future__ import annotations

import importlib
import sys

MODULES = {"mere_terminal_bench.cli"}

if len(sys.argv) < 2 or sys.argv[1] not in MODULES:
    raise SystemExit("Run the bundled mere-terminal-bench entrypoint.")
sys.dont_write_bytecode = True
module = importlib.import_module(sys.argv.pop(1))
raise SystemExit(module.main())

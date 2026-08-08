#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MERE_PLUGIN_PYTHON="${MERE_PLUGIN_PYTHON:-python3}"
FAST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/mere-run-plugins-fast.XXXXXX")"
trap 'rm -rf "$FAST_TMP"' EXIT

export PYTHONPATH="$ROOT/packages/mere-runpod/src:$ROOT/packages/mere-image-tools/src:$ROOT/packages/mere-face-tools/src:$ROOT/packages/mere-workflow-tools/src:$ROOT/packages/mere-geo-tools/src:$ROOT/packages/mere-animatic-tools/src:$ROOT/packages/mere-shotgrid-tools/src:$ROOT/packages/mere-perform/src:$ROOT/packages/mere-vfx-tools/src"

"$MERE_PLUGIN_PYTHON" -m ruff check .
"$MERE_PLUGIN_PYTHON" -m mypy
"$MERE_PLUGIN_PYTHON" -m compileall -q packages scripts
"$MERE_PLUGIN_PYTHON" scripts/check_structure.py
"$MERE_PLUGIN_PYTHON" scripts/validate_repo.py

suites=(
  mere-runpod
  mere-image-tools
  mere-face-tools
  mere-workflow-tools
  mere-geo-tools
  mere-animatic-tools
  mere-shotgrid-tools
  mere-perform
  mere-vfx-tools
)
pids=()
for suite in "${suites[@]}"; do
  "$MERE_PLUGIN_PYTHON" -m unittest discover -s "packages/$suite/tests" >"$FAST_TMP/$suite.log" 2>&1 &
  pids+=("$!")
done

test_status=0
for index in "${!pids[@]}"; do
  if ! wait "${pids[$index]}"; then
    test_status=1
    echo "Fast test failure: ${suites[$index]}" >&2
    sed -n '1,240p' "$FAST_TMP/${suites[$index]}.log" >&2
  fi
done
if [[ "$test_status" -ne 0 ]]; then
  exit "$test_status"
fi

echo "check-fast: ok (${#suites[@]} package suites)"

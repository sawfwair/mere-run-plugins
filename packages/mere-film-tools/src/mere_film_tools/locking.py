from __future__ import annotations

import contextlib
import fcntl
import json
import os
import pathlib
import socket
import time
from collections.abc import Iterator
from typing import TextIO

from .common import PluginError, now_iso

LOCK_FILENAME = ".mere-film.lock"
DEFAULT_LOCK_TIMEOUT_SECONDS = 2.0


def configured_lock_timeout() -> float:
    raw = os.environ.get("MERE_FILM_LOCK_TIMEOUT_SECONDS")
    if raw is None:
        return DEFAULT_LOCK_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise PluginError("MERE_FILM_LOCK_TIMEOUT_SECONDS must be a number", 2) from exc
    if value < 0:
        raise PluginError("MERE_FILM_LOCK_TIMEOUT_SECONDS must not be negative", 2)
    return value


def lock_owner(handle: TextIO) -> str:
    handle.seek(0)
    value = handle.read().strip()
    if not value:
        return "unknown owner"
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return value[:200]
    if not isinstance(payload, dict):
        return value[:200]
    pid = payload.get("pid", "unknown")
    operation = payload.get("operation", "unknown")
    host = payload.get("host", "unknown")
    acquired = payload.get("acquiredAt", "unknown")
    return f"pid {pid} on {host}, operation {operation}, acquired {acquired}"


def write_owner(handle: TextIO, operation: str) -> None:
    payload = {
        "contractVersion": "mere.run/film-project-lock.v1",
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "operation": operation,
        "acquiredAt": now_iso(),
    }
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


@contextlib.contextmanager
def project_lock(
    project_root: pathlib.Path,
    operation: str,
    timeout_seconds: float | None = None,
) -> Iterator[pathlib.Path]:
    root = project_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / LOCK_FILENAME
    timeout = configured_lock_timeout() if timeout_seconds is None else timeout_seconds
    deadline = time.monotonic() + timeout
    handle = lock_path.open("a+", encoding="utf-8")
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    owner = lock_owner(handle)
                    raise PluginError(
                        f"film project is busy ({owner}); wait for that operation or inspect its process before retrying",
                        1,
                    ) from None
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        write_owner(handle, operation)
        yield lock_path
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

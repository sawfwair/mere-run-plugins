"""Own and bound every process started by an archive investigation."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from types import FrameType


class InvestigationInterrupted(RuntimeError):
    def __init__(self, signum: int) -> None:
        super().__init__(f"Investigation interrupted by {signal.Signals(signum).name}.")
        self.exit_code = 128 + signum


def interrupt(signum: int, _frame: FrameType | None) -> None:
    raise InvestigationInterrupted(signum)


class Processes:
    def __init__(self) -> None:
        self.children: list[subprocess.Popen[str]] = []
        self.peak_rss_bytes = 0
        self.missed_memory_samples = 0
        self.last_sample: float | None = None

    @contextmanager
    def signals(self) -> Iterator[None]:
        previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            yield
        finally:
            # A second signal must not interrupt process-tree cleanup.
            for sig in previous:
                signal.signal(sig, signal.SIG_IGN)
            try:
                self.close()
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)

    def start(self, command: list[str], *, cwd: str | None = None,
              env: dict[str, str] | None = None, discard_output: bool = False) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            command, cwd=cwd, env=env, text=True, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL if discard_output else subprocess.PIPE,
            stderr=subprocess.DEVNULL if discard_output else subprocess.PIPE, start_new_session=True,
        )
        self.children.append(process)
        return process

    def stop(self, process: subprocess.Popen[str]) -> None:
        # Children inherit the dedicated process group even after their parent exits.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2)
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        if process in self.children:
            self.children.remove(process)

    def close(self) -> None:
        for process in reversed(self.children.copy()):
            self.stop(process)

    def sample_memory(self) -> None:
        if self.last_sample is not None and time.monotonic() - self.last_sample < 0.5:
            return
        self.last_sample = time.monotonic()
        try:
            result = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,rss="], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2, check=True,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            # Observational telemetry must not cancel an otherwise valid run.
            self.missed_memory_samples += 1
            return
        rows = [tuple(int(value) for value in line.split()) for line in result.stdout.splitlines()]
        owned = {os.getpid(), *(process.pid for process in self.children)}
        while True:
            descendants = {pid for pid, parent, _rss in rows if parent in owned}
            if descendants.issubset(owned):
                break
            owned.update(descendants)
        rss = sum(rss * 1024 for pid, _parent, rss in rows if pid in owned)
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss)

    def run(self, command: list[str], *, timeout: float, stdin: str | None = None,
            cwd: str | None = None, env: dict[str, str] | None = None,
            poll: Callable[[], None] | None = None) -> subprocess.CompletedProcess[str]:
        process = self.start(command, cwd=cwd, env=env)
        deadline = time.monotonic() + timeout
        try:
            while True:
                self.sample_memory()
                if poll is not None:
                    poll()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command[0], timeout)
                try:
                    stdout, stderr = process.communicate(input=stdin, timeout=min(0.1, remaining))
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    stdin = None
        finally:
            self.stop(process)

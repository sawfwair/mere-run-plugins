"""Capture a local World session as portable media and a camera recipe."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import math
import os
import pathlib
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageOps

JsonMap = dict[str, object]
SCHEMA = "mere.run/world-handoff.v1"
MOVES = {"hold", "forward", "backward", "strafeLeft", "strafeRight", "yawLeft", "yawRight", "custom"}
DEFAULTS: dict[str, JsonMap] = {
    "dreamx": {"width": 512, "height": 320, "num_frames": 17, "steps": 40, "guidance_scale": 5,
               "shift": 5, "seed": 42, "fps": 24},
    "cosmos3": {"width": 320, "height": 176, "num_frames": 17, "steps": 30, "guidance_scale": 1,
                "shift": 3, "seed": 0, "fps": 30},
}


def as_object(value: object, label: str) -> JsonMap:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(JsonMap, value)


def uuid_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"World response is missing {label}")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ValueError(f"World response has an invalid {label}") from None


def local_file(value: object, label: str) -> pathlib.Path:
    if not isinstance(value, str):
        raise ValueError(f"World response is missing {label}")
    url = urlsplit(value)
    if url.scheme != "file" or url.netloc or url.query or url.fragment or not url.path.startswith("/"):
        raise ValueError(f"World response must use a local file URL for {label}")
    path = pathlib.Path(unquote(url.path))
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"World response points to missing or linked {label}")
    return path.resolve()


def finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(cast(float, value))


def endpoint_address(endpoint: object) -> tuple[str, int]:
    if not isinstance(endpoint, str):
        raise ValueError("World endpoint must be an HTTP URL")
    url = urlsplit(endpoint)
    try:
        host = ipaddress.ip_address(url.hostname or "")
        port = url.port
    except ValueError:
        raise ValueError("World endpoint requires a numeric loopback address and a valid port") from None
    if (url.scheme != "http" or not host.is_loopback or url.username is not None
            or url.path not in ("", "/") or url.query or url.fragment or port == 0):
        raise ValueError("World endpoint must be a local HTTP origin such as http://127.0.0.1:8791")
    return str(host), port or 80


class WorldClient:
    def __init__(self, endpoint: object) -> None:
        self.host, self.port = endpoint_address(endpoint)
        self.token = os.environ.get("MERE_WORLD_API_KEY") or os.environ.get("MERERUN_API_KEY")

    def request(self, path: str, payload: JsonMap | None = None, *, timeout: float = 10) -> JsonMap:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, allow_nan=False).encode()
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            connection.request("POST" if payload is not None else "GET", path, body, headers)
            with connection.getresponse() as response:
                expected = 202 if payload is not None else 200
                if response.status != expected:
                    raise ValueError(f"local World runtime returned HTTP {response.status} for {path}")
                data = response.read(4 * 1024 * 1024 + 1)
                if len(data) > 4 * 1024 * 1024:
                    raise ValueError("local World runtime response exceeds 4 MiB")
                return as_object(json.loads(data), "World response")
        except (OSError, http.client.HTTPException) as exc:
            raise ValueError(f"local World runtime request failed for {path} ({type(exc).__name__})") from None
        finally:
            connection.close()

    def complete(self, job_id: str, timeout: int) -> JsonMap:
        path = f"/v1/world/jobs/{job_id}"
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            job = self.request(path, timeout=min(10, remaining))
            if uuid_text(job.get("job_id"), "job ID") != job_id:
                raise ValueError("World runtime returned a different job")
            status = job.get("status")
            if status == "completed":
                return as_object(job.get("receipt"), "transition receipt")
            if status not in ("queued", "generating", "cancelling"):
                raise ValueError(f"World job {job_id} ended with status {status!r}. Check the World server log.")
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise ValueError(f"World job {job_id} exceeded the wait limit. Inspect it on the server before starting another capture.")


def recipe_moves(value: object) -> list[JsonMap]:
    if not isinstance(value, list) or not value:
        raise ValueError("request.options.moves must contain at least one camera move")
    result = []
    for index, item in enumerate(value, 1):
        move = as_object(item, f"move {index}")
        if set(move) != {"prompt", "camera"}:
            raise ValueError(f"move {index} requires a prompt and camera")
        prompt = move["prompt"]
        camera = as_object(move["camera"], f"move {index} camera")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"move {index} requires a nonempty prompt")
        if (set(camera) != {"motion", "translationMeters", "rotationDegrees"}
                or not isinstance(camera["motion"], str) or camera["motion"] not in MOVES):
            raise ValueError(f"move {index} requires a supported motion, translationMeters, and rotationDegrees")
        for key in ("translationMeters", "rotationDegrees"):
            vector = camera[key]
            if not isinstance(vector, list) or len(vector) != 3 or not all(
                finite(component) and abs(cast(float, component)) <= 1e6 for component in vector
            ):
                raise ValueError(f"move {index} {key} requires three finite XYZ values")
        result.append(move)
    return result


def sampling_settings(backend: str, value: object) -> JsonMap:
    requested = as_object(value, "sampling")
    defaults = DEFAULTS[backend]
    if set(requested) - defaults.keys():
        raise ValueError("sampling contains unsupported World runtime options")
    settings = {**defaults, **requested}
    for key in ("width", "height", "num_frames", "steps", "fps"):
        number = settings[key]
        if type(number) is not int or number < 1:
            raise ValueError(f"sampling {key} must be a positive integer")
    seed = settings["seed"]
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("sampling seed must be an unsigned 64-bit integer")
    for key in ("guidance_scale", "shift"):
        setting = settings[key]
        if not finite(setting) or not 0 < cast(float, setting) <= 1e6:
            raise ValueError(f"sampling {key} must be positive and finite")
    return settings


def pin(path: pathlib.Path, root: pathlib.Path) -> JsonMap:
    hasher = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return {"path": path.relative_to(root).as_posix(), "sha256": f"sha256:{hasher.hexdigest()}",
            "bytes": path.stat().st_size}


def write_receipt(path: pathlib.Path, value: JsonMap) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_png(path: pathlib.Path) -> None:
    with Image.open(path) as image:
        if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
            raise ValueError("World terminal frame must be a single PNG image")
        image.verify()


def collect_transition(
    receipt: JsonMap, job_id: str, parent: str | None, index: int, clip: pathlib.Path,
    state_dir: pathlib.Path, frame: pathlib.Path, camera: JsonMap,
) -> tuple[str, int, int]:
    previous = receipt.get("previous_state_id")
    if previous is not None:
        previous = uuid_text(previous, "previous state ID")
    next_state = uuid_text(receipt.get("state_id"), "state ID")
    native_index = receipt.get("transition_index")
    if previous != parent or next_state == parent or type(native_index) is not int or native_index <= index:
        raise ValueError(f"World job {job_id} did not continue the expected camera path")
    seed = receipt.get("seed")
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError(f"World job {job_id} did not report a valid effective seed")
    actual_camera = as_object(receipt.get("camera"), "completed camera")
    if actual_camera.get("motion") != camera["motion"]:
        raise ValueError(f"World job {job_id} did not apply the requested camera motion")
    for key, response_key in (("translationMeters", "translation_meters"), ("rotationDegrees", "rotation_degrees")):
        values = actual_camera.get(response_key)
        expected = cast(list[float], camera[key])
        if not isinstance(values, list) or len(values) != 3 or any(
            not finite(value) or not math.isclose(value, requested, rel_tol=1e-6, abs_tol=1e-7)
            for value, requested in zip(values, expected)
        ):
            raise ValueError(f"World job {job_id} did not apply the requested camera vector")
    if local_file(receipt.get("output_url"), "transition video") != clip:
        raise ValueError(f"World job {job_id} reported an unexpected video path")
    with clip.open("rb") as stream:
        if stream.read(8)[4:] != b"ftyp":
            raise ValueError(f"World job {job_id} did not produce an MP4")
    terminal = local_file(receipt.get("terminal_frame_url"), "terminal frame")
    if terminal.parent != state_dir or not terminal.name.startswith("state-") or terminal.suffix != ".png":
        raise ValueError(f"World job {job_id} reported a terminal frame outside the configured state directory")
    shutil.copyfile(terminal, frame)
    verify_png(frame)
    return next_state, native_index, seed


@contextmanager
def capture_lock(output: pathlib.Path) -> Iterator[None]:
    import fcntl

    with (output / ".world-capture.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("a World capture is already using this output directory") from None
        yield


def capture(source: pathlib.Path, options: JsonMap, output: pathlib.Path) -> tuple[pathlib.Path, list[pathlib.Path]]:
    unknown = set(options) - {"endpoint", "stateDirectory", "moves", "sampling", "timeoutSeconds"}
    if unknown:
        raise ValueError(f"unsupported World handoff options: {', '.join(sorted(unknown))}")
    moves = recipe_moves(options.get("moves"))
    state_path = options.get("stateDirectory")
    if not isinstance(state_path, str) or not state_path:
        raise ValueError("request.options.stateDirectory must match the World server state directory")
    state_dir = pathlib.Path(state_path).expanduser().resolve()
    timeout = options.get("timeoutSeconds", 1800)
    if type(timeout) is not int or timeout < 1:
        raise ValueError("timeoutSeconds must be a positive integer")
    client = WorldClient(options.get("endpoint", "http://127.0.0.1:8791"))
    current = client.request("/v1/world/session")
    session = as_object(current.get("session"), "World session")
    backend = current.get("backend")
    if not isinstance(backend, str) or backend not in DEFAULTS:
        raise ValueError("World endpoint must serve DreamX or Cosmos3")
    if session.get("transition_count") != 0 or session.get("current_state_id") is not None or current.get("active_job") is not None:
        raise ValueError("Start a fresh dedicated World session before launching a handoff.")
    session_id = uuid_text(session.get("session_id"), "session ID")
    settings = sampling_settings(backend, options.get("sampling", {}))
    root = output / "world"
    root.mkdir(mode=0o700)
    media = root / "media"
    media.mkdir()
    origin = root / "origin.png"
    with Image.open(source) as original:
        if getattr(original, "n_frames", 1) != 1:
            raise ValueError("World origin must be a single still image")
        ImageOps.exif_transpose(original).convert("RGB").save(origin)
    pending = root / "capture.json"
    records: list[JsonMap] = []
    ledger: JsonMap = {
        "backend": backend, "sessionId": session_id, "status": "in-progress",
        "plannedMoves": moves, "transitions": records, "sampling": settings, "origin": pin(origin, root),
    }
    write_receipt(pending, ledger)
    paths = [origin]
    parent = None
    index = 0
    for number, move in enumerate(moves, 1):
        snapshot = client.request("/v1/world/session")
        active = as_object(snapshot.get("session"), "World session")
        current_state = active.get("current_state_id")
        expected_state = None if current_state is None else uuid_text(current_state, "current state ID")
        if (snapshot.get("active_job") is not None or snapshot.get("backend") != backend
                or uuid_text(active.get("session_id"), "session ID") != session_id or expected_state != parent):
            raise ValueError("World session changed during capture. Completed media remains in the output directory.")
        clip = media / f"{number:04}.mp4"
        frame = media / f"{number:04}.png"
        payload = {**move, **settings, "output": str(clip)}
        if number == 1:
            payload["sourceImage"] = str(origin)
        queued = client.request("/v1/world/session/transitions", payload)
        job_id = uuid_text(queued.get("job_id"), "job ID")
        ledger["activeJob"] = job_id
        write_receipt(pending, ledger)
        completed = client.complete(job_id, timeout)
        previous = parent
        parent, index, actual_seed = collect_transition(
            completed, job_id, parent, index, clip, state_dir, frame, as_object(move["camera"], "camera"),
        )
        records.append({
            "sequence": number, "jobId": job_id, "previousStateId": previous, "stateId": parent,
            "transitionIndex": index, "effectiveSeed": actual_seed, "request": move,
            "video": pin(clip, root), "terminalFrame": pin(frame, root),
        })
        paths.extend([clip, frame])
        ledger.pop("activeJob")
        write_receipt(pending, ledger)
    delivery = root / "handoff.json"
    write_receipt(delivery, {
        "contractVersion": SCHEMA, "backend": backend, "sessionId": session_id,
        "origin": ledger["origin"], "sampling": settings, "transitions": records,
        "continuationFrame": records[-1]["terminalFrame"],
    })
    ledger["status"] = "completed"
    write_receipt(pending, ledger)
    return delivery, paths

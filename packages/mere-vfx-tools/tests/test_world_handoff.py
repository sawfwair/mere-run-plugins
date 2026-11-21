from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jsonschema import validate
from PIL import Image

from mere_vfx_tools import cli, world_handoff


def run_cli(*args: str) -> tuple[int, str]:
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as err:
        code = cli.main(list(args))
    return code, err.getvalue()


class WorldHandoffTests(unittest.TestCase):
    def test_two_moves_create_portable_editorial_media(self) -> None:
        with tempfile.TemporaryDirectory() as location:
            root = Path(location).resolve()
            source = root / "source.jpg"
            Image.new("RGB", (32, 32), "navy").save(source)
            state = root / "server-state"
            state.mkdir()
            output = root / "export"
            moves = [
                {"prompt": "Move forward", "camera": {
                    "motion": "forward", "translationMeters": [0, 0, 1], "rotationDegrees": [0, 0, 0],
                }},
                {"prompt": "Turn to the window", "camera": {
                    "motion": "yawRight", "translationMeters": [0, 0, 0], "rotationDegrees": [0, 20, 0],
                }},
            ]
            request = root / "request.json"
            request.write_text(json.dumps({
                "inputs": {"image": str(source)}, "options": {"stateDirectory": str(state), "moves": moves},
            }))
            session = str(uuid.uuid4())
            current = None
            jobs: dict[str, world_handoff.JsonMap] = {}
            generating: set[str] = set()

            def server(_self: world_handoff.WorldClient, path: str, payload: world_handoff.JsonMap | None = None,
                       timeout: float = 10) -> world_handoff.JsonMap:
                nonlocal current
                self.assertGreater(timeout, 0)
                if path == "/v1/world/session":
                    return {"backend": "cosmos3", "session": {
                        "session_id": session, "transition_count": len(jobs), "current_state_id": current,
                    }}
                if path == "/v1/world/session/transitions":
                    self.assertIsNotNone(payload)
                    assert payload is not None
                    self.assertEqual(payload.get("fps"), 30)
                    self.assertEqual("sourceImage" in payload, len(jobs) == 0)
                    clip = Path(str(payload["output"]))
                    clip.write_bytes(b"\x00\x00\x00\x18ftyp" + b"fixture")
                    frame = state / f"state-{len(jobs) + 1:04}.png"
                    Image.new("RGB", (32, 32), "orange").save(frame)
                    camera = world_handoff.as_object(payload["camera"], "camera")
                    job_id = str(uuid.uuid4())
                    next_state = str(uuid.uuid4())
                    receipt: world_handoff.JsonMap = {
                        "state_id": next_state, "previous_state_id": current,
                        "transition_index": len(jobs) + 1, "seed": len(jobs),
                        "output_url": clip.as_uri(), "terminal_frame_url": frame.as_uri(),
                        "camera": {"motion": camera["motion"], "translation_meters": camera["translationMeters"],
                                   "rotation_degrees": camera["rotationDegrees"]},
                    }
                    jobs[job_id] = receipt
                    current = next_state
                    return {"job_id": job_id, "status": "queued"}
                job_id = path.rsplit("/", 1)[1]
                if job_id not in generating:
                    generating.add(job_id)
                    return {"job_id": job_id, "status": "generating"}
                return {"job_id": job_id, "status": "completed", "receipt": jobs[job_id]}

            with (
                patch.object(world_handoff.WorldClient, "request", autospec=True, side_effect=server),
                patch.object(world_handoff.time, "sleep"),
            ):
                code, error = run_cli("world-handoff", "--request-json", str(request), "--output-dir", str(output))
                self.assertEqual(code, 0, error)
            portable = root / "editor-copy"
            shutil.move(output / "world", portable)
            shutil.rmtree(state)
            handoff = json.loads((portable / "handoff.json").read_text())
            schema = Path(__file__).resolve().parents[3] / "contracts" / "world-handoff.v1.schema.json"
            validate(handoff, json.loads(schema.read_text()))
            self.assertEqual([row["request"] for row in handoff["transitions"]], moves)
            self.assertEqual([row["effectiveSeed"] for row in handoff["transitions"]], [0, 1])
            self.assertEqual(handoff["continuationFrame"], handoff["transitions"][1]["terminalFrame"])
            self.assertEqual(handoff["transitions"][1]["previousStateId"], handoff["transitions"][0]["stateId"])
            self.assertNotIn(str(root), (portable / "handoff.json").read_text())
            for name in ("origin.png", "media/0001.mp4", "media/0002.mp4", "media/0002.png"):
                self.assertTrue((portable / name).is_file())

    def test_rejects_remote_authority_and_busy_session(self) -> None:
        for endpoint in ("http://192.0.2.1:8791", "http://127.0.0.1@192.0.2.1:8791", "http://localhost:8791"):
            with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, "loopback|local HTTP"):
                world_handoff.endpoint_address(endpoint)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(world_handoff.WorldClient, "request", return_value={
                "backend": "dreamx", "session": {"transition_count": 2}, "active_job": {"status": "generating"},
            }) as request, self.assertRaisesRegex(ValueError, "fresh dedicated"):
                world_handoff.capture(root / "source.png", {"stateDirectory": str(root), "moves": [{
                    "prompt": "Hold", "camera": {"motion": "hold", "translationMeters": [0, 0, 0],
                                                "rotationDegrees": [0, 0, 0]},
                }]}, root)
            request.assert_called_once_with("/v1/world/session")
            self.assertFalse((root / "world").exists())

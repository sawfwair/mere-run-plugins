from __future__ import annotations

import json
import pathlib
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from mere_film_tools import cli, pi_harness, production
from mere_film_tools.common import PluginError, file_sha256, load_json, validate_run_id, write_json
from mere_film_tools.locking import project_lock
from mere_film_tools.state import paths_for_root

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def assert_contract(test: unittest.TestCase, schema_name: str, payload: dict[str, object]) -> None:
    schema = load_json(REPO_ROOT / "contracts" / schema_name)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda item: list(item.path),
    )
    test.assertEqual(errors, [], errors[0].message if errors else "")


def run_cli(arguments: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli.main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


def write_executable(path: pathlib.Path, body: str) -> pathlib.Path:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def fake_pi(path: pathlib.Path) -> pathlib.Path:
    return write_executable(
        path,
        r'''
import json
import re
import sys

prompt = sys.argv[-1]
match = re.search(r"Complete task ([a-z0-9-]+)", prompt)
if not match:
    raise SystemExit("task id not found")
task = match.group(1)
roles = {
    "story-development": "story-editor",
    "visual-development": "production-designer",
    "production-constraints": "line-producer",
    "treatment-synthesis": "director",
    "screenplay": "screenwriter",
    "cinematography": "cinematographer",
    "sound-plan": "sound-designer",
    "continuity-plan": "continuity-supervisor",
    "production-synthesis": "director",
    "story-review": "story-critic",
    "edit-review": "edit-critic",
    "continuity-review": "continuity-supervisor",
    "review-synthesis": "director",
}
phases = {
    **{key: "development" for key in ["story-development", "visual-development", "production-constraints", "treatment-synthesis"]},
    **{key: "preproduction" for key in ["screenplay", "cinematography", "sound-plan", "continuity-plan", "production-synthesis"]},
    **{key: "review" for key in ["story-review", "edit-review", "continuity-review", "review-synthesis"]},
}
deliverables = {"notes": [f"validated {task}"]}
if task == "treatment-synthesis":
    deliverables = {"treatment": {
        "title": "The Last Signal",
        "logline": "A keeper answers a signal that should not exist.",
        "synopsis": "A storm isolates a lighthouse keeper until an impossible signal asks her to choose memory over certainty.",
        "theme": "Connection requires risk.",
        "beats": ["The beacon fails.", "The impossible signal arrives.", "The keeper answers."],
        "visualLanguage": "Cold Atlantic blues interrupted by amber lamp light.",
        "soundLanguage": "Wind, relay clicks, and a restrained analog pulse.",
        "assumptions": [],
        "openQuestions": [],
    }}
elif task == "production-synthesis":
    deliverables = {"productionPlan": {
        "title": "The Last Signal",
        "scorePrompt": "restrained analog pulse, Atlantic wind, hopeful ending",
        "cast": [{
            "id": "keeper",
            "name": "Mara",
            "visual": "weathered woman in her forties, cropped dark hair, alert eyes",
            "wardrobe": "mustard wool sweater and navy work trousers",
            "voice": "quiet Atlantic cadence",
        }],
        "locations": [{
            "id": "lamp-room",
            "name": "Lamp Room",
            "visual": "salt-streaked glass, brass relay desk, rotating beacon",
            "ambience": "wind pressure and relay clicks",
        }],
        "shots": [
            {
                "id": "beacon-fails",
                "purpose": "isolate Mara",
                "framePrompt": "Wide cinematic frame of Mara at a brass relay desk in a storm-dark lighthouse lamp room, mustard sweater, cold blue windows, amber practical light",
                "prompt": "The beacon slows and Mara looks up as the lamp room falls dark, controlled dolly in, physical natural motion",
                "durationSeconds": 2,
                "seed": 101,
                "characters": ["keeper"],
                "location": "lamp-room",
                "dialogue": [],
                "soundEffects": [{
                    "prompt": "single brass relay click with a short mechanical tail, isolated, no music",
                    "startSeconds": 0.7,
                    "durationSeconds": 1.0,
                    "levelDb": -9,
                    "seed": 303,
                }],
                "transition": "cut",
            },
            {
                "id": "signal-answered",
                "purpose": "resolve the choice",
                "framePrompt": "Close cinematic frame of Mara pressing an old brass telegraph key, mustard sweater, amber beacon returning behind her, rain on glass",
                "prompt": "Mara presses the key and warm light rolls across her face as the beacon returns, subtle handheld breath",
                "durationSeconds": 2,
                "seed": 202,
                "characters": ["keeper"],
                "location": "lamp-room",
                "dialogue": [{
                    "speaker": "keeper",
                    "text": "I hear you.",
                    "startSeconds": 0.5,
                    "delivery": "quiet, certain, barely above the storm",
                }],
                "transition": "fade",
            },
        ],
    }}
elif task == "review-synthesis":
    deliverables = {"review": {
        "decision": "pass",
        "issues": [],
        "rerolls": [],
        "strengths": ["The visual turn lands clearly."],
        "deliveryNotes": ["Preserve the final amber lift."],
    }}
payload = {
    "contractVersion": "mere.run/film-department-result.v1",
    "taskId": task,
    "role": roles[task],
    "phase": phases[task],
    "summary": f"Completed {task}.",
    "decisions": [f"Accepted the bounded {task} direction."],
    "deliverables": deliverables,
    "risks": [],
    "questions": [],
}
print(json.dumps(payload))
''',
    )


def fake_mere_run(path: pathlib.Path) -> pathlib.Path:
    return write_executable(
        path,
        r'''
import json
import pathlib
import sys

if "--preflight" in sys.argv:
    print(json.dumps({"status": "ok", "admission": "fake-local"}))
    raise SystemExit(0)
if sys.argv[1:3] == ["model", "info"]:
    if "--json" in sys.argv:
        print(json.dumps({"id": sys.argv[3], "formatVersion": 1}))
    else:
        model_root = pathlib.Path(__file__).parent / "fake-model-root"
        model_root.mkdir(exist_ok=True)
        print(f"Model Root: {model_root}")
    raise SystemExit(0)
if sys.argv[1:3] == ["vision", "inspect"]:
    candidate = pathlib.Path(sys.argv[3]).stem
    print(json.dumps({
        "decision": "pass",
        "score": 96 if candidate == "candidate-002" else 82,
        "observations": ["The generated frame visibly matches the expected cinematic subject and setting."],
        "mismatches": [],
        "confidence": 0.91,
    }))
    raise SystemExit(0)
if sys.argv[1:3] == ["speech", "transcribe"]:
    print("I hear you.")
    raise SystemExit(0)
output = pathlib.Path(sys.argv[sys.argv.index("--output") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(("generated:" + " ".join(sys.argv[1:3])).encode())
print(json.dumps({"output": str(output)}))
''',
    )


def fake_ffmpeg(path: pathlib.Path) -> pathlib.Path:
    return write_executable(
        path,
        r'''
import json
import pathlib
import sys

output = pathlib.Path(sys.argv[-1])
if output == pathlib.Path("-"):
    if "-af" in sys.argv and "loudnorm" in sys.argv[sys.argv.index("-af") + 1]:
        print(json.dumps({
            "input_i": "-16.1", "input_tp": "-1.7", "input_lra": "5.2",
            "input_thresh": "-27.0", "output_i": "-16.0", "output_tp": "-1.5",
            "output_lra": "5.1", "output_thresh": "-26.9", "normalization_type": "dynamic",
            "target_offset": "0.0",
        }), file=sys.stderr)
    if "-af" in sys.argv and "volumedetect" in sys.argv[sys.argv.index("-af") + 1]:
        print("[Parsed_volumedetect_0] max_volume: -12.0 dB", file=sys.stderr)
    raise SystemExit(0)
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(b"fake playable h264 aac movie")
''',
    )


def fake_ffprobe(path: pathlib.Path) -> pathlib.Path:
    return write_executable(
        path,
        r'''
import json
import pathlib
import sys

media = pathlib.Path(sys.argv[-1])
streams = [] if media.suffix == ".wav" else [{"codec_type": "video", "codec_name": "h264", "width": 160, "height": 90}]
if media.suffix == ".wav" or media.name == "rough-cut.mp4" or media.parent.name == "delivery":
    streams.append({"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"})
print(json.dumps({"streams": streams, "format": {"duration": "4.000", "size": str(media.stat().st_size)}}))
''',
    )


def complete_plan_arguments(root: pathlib.Path) -> list[str]:
    return [
        "plan",
        "--idea",
        "A lighthouse keeper receives a signal from a vanished ship.",
        "--title",
        "The Last Signal",
        "--project-id",
        "The_Last_SIGNAL!",
        "--output-dir",
        str(root),
        "--run-id",
        "unit-film",
        "--duration",
        "4",
        "--width",
        "160",
        "--height",
        "90",
        "--fps",
        "24",
        "--audience",
        "adult science-fiction viewers",
        "--genre",
        "science-fiction drama",
        "--tone",
        "tense then hopeful",
        "--rating",
        "PG",
        "--platform",
        "web",
        "--usage",
        "noncommercial",
        "--reference",
        "restrained maritime chamber drama",
    ]


class MereFilmToolsTests(unittest.TestCase):
    def test_project_lock_rejects_a_competing_writer_with_owner_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "film"
            with project_lock(root, "first-writer", timeout_seconds=0):
                with self.assertRaisesRegex(PluginError, "first-writer") as raised:
                    with project_lock(root, "second-writer", timeout_seconds=0):
                        self.fail("a competing writer acquired the project lock")
            self.assertEqual(raised.exception.exit_code, 1)
            owner = load_json(root / ".mere-film.lock")
            self.assertEqual(owner["operation"], "first-writer")
            self.assertGreater(owner["pid"], 0)

    def test_execute_recovers_interrupted_work_and_retries_from_durable_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project_root = root / "film"
            pi = fake_pi(root / "pi")
            code, output, error = run_cli([*complete_plan_arguments(project_root), "--pi-command", str(pi)])
            self.assertEqual(code, 0, error)
            run_manifest = pathlib.Path(json.loads(output)["status"]["runManifest"])
            self.assertEqual(run_cli(["approve", str(run_manifest), "--gate", "brief"])[0], 0)
            project_path = project_root / "film-project.json"
            project = load_json(project_path)
            story = next(item for item in project["departments"] if item["id"] == "story-development")
            story.update({"status": "running", "startedAt": "2026-01-01T00:00:00Z"})
            project["jobs"] = [{"id": "stale-media", "status": "running", "kind": "shot-clip"}]
            project["status"] = "running"
            write_json(project_path, project)

            code, output, error = run_cli(["recover", str(run_manifest)])
            self.assertEqual(code, 0, error)
            recovery = json.loads(output)["recovery"]
            self.assertTrue(recovery["recovered"])
            self.assertEqual(recovery["tasks"], ["story-development"])
            self.assertEqual(recovery["jobs"], ["stale-media"])
            self.assertTrue(recovery["projectStatus"])

            code, output, error = run_cli(["run", str(run_manifest)])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["action"], "treatment-created")
            recovered = load_json(project_path)
            story = next(item for item in recovered["departments"] if item["id"] == "story-development")
            stale_job = next(item for item in recovered["jobs"] if item["id"] == "stale-media")
            self.assertIn(story["status"], {"succeeded", "accepted"})
            self.assertEqual(stale_job["status"], "failed")
            self.assertTrue(any(item["event"] == "interrupted-work-recovered" for item in recovered["history"]))
            issue = next(item for item in recovered["issues"] if item["code"] == "interrupted-work-recovered")
            self.assertFalse(issue["blocking"])

    def test_manifest_declares_governed_local_film_surface(self) -> None:
        manifest = cli.plugin_manifest()
        names = {item["name"] for item in manifest["commands"]}
        self.assertEqual(manifest["contractVersion"], "mere.run/plugin.v1")
        self.assertEqual(manifest["name"], "mere-film-tools")
        self.assertTrue({"manifest", "doctor", "plan", "run", "resume", "cleanup"}.issubset(names))
        self.assertTrue({"agent", "approve", "delegate", "review", "review-decision", "reroll"}.issubset(names))
        self.assertFalse(manifest["security"]["createsPaidResources"])
        self.assertEqual(manifest["security"]["cleanupDefault"], "none")

    def test_incomplete_brief_cannot_be_approved_then_can_be_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "film"
            code, output, error = run_cli([
                "plan", "--idea", "A door remembers everyone who opened it.", "--output-dir", str(root)
            ])
            self.assertEqual(code, 0, error)
            planned = json.loads(output)
            run_manifest = pathlib.Path(planned["status"]["runManifest"])
            self.assertEqual(len(planned["status"]["openQuestions"]), 6)
            code, _, error = run_cli(["approve", str(run_manifest), "--gate", "brief"])
            self.assertEqual(code, 2)
            self.assertIn("unresolved questions", error)
            code, output, error = run_cli([
                "brief",
                str(run_manifest),
                "--audience", "festival viewers",
                "--genre", "magical realism",
                "--tone", "wry and tender",
                "--rating", "PG",
                "--reference", "quiet practical miniatures",
                "--usage", "noncommercial",
            ])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["openQuestions"], [])
            code, output, error = run_cli([
                "approve", str(run_manifest), "--gate", "brief", "--approved-by", "unit-user"
            ])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["approvals"]["brief"]["approvedBy"], "unit-user")
            project = load_json(root / "film-project.json")
            self.assertEqual(project["projectId"], "a-door-remembers-everyone-who-opened")

    def test_end_to_end_fake_local_film_reaches_checksum_backed_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project_root = root / "film"
            pi = fake_pi(root / "pi")
            mere_run = fake_mere_run(root / "mere.run")
            ffmpeg = fake_ffmpeg(root / "ffmpeg")
            ffprobe = fake_ffprobe(root / "ffprobe")
            code, output, error = run_cli([
                *complete_plan_arguments(project_root),
                "--pi-command", str(pi),
                "--mere-run-command", str(mere_run),
                "--ffmpeg-command", str(ffmpeg),
                "--ffprobe-command", str(ffprobe),
            ])
            self.assertEqual(code, 0, error)
            run_manifest = pathlib.Path(json.loads(output)["status"]["runManifest"])
            project = load_json(project_root / "film-project.json")
            self.assertEqual(project["projectId"], "the-last-signal")

            code, _, error = run_cli(["approve", str(run_manifest), "--gate", "brief"])
            self.assertEqual(code, 0, error)
            code, output, error = run_cli(["run", str(run_manifest)])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["action"], "treatment-created")
            treatment = load_json(project_root / "treatment.json")
            self.assertEqual(treatment["title"], "The Last Signal")

            code, _, error = run_cli(["approve", str(run_manifest), "--gate", "treatment"])
            self.assertEqual(code, 0, error)
            code, output, error = run_cli(["resume", str(run_manifest), "--execute"])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["action"], "production-plan-created")
            plan = load_json(project_root / "production-plan.json")
            assert_contract(self, "film-production-plan.v1.schema.json", plan)
            self.assertEqual(plan["plannedDurationSeconds"], 4.0)
            self.assertEqual(len(plan["shots"]), 2)

            code, output, error = run_cli(["preflight", str(run_manifest)])
            self.assertEqual(code, 0, error)
            preflight_payload = json.loads(output)
            assert_contract(self, "film-production-readiness.v1.schema.json", preflight_payload["readiness"])
            self.assertTrue(preflight_payload["readiness"]["complete"])

            code, _, error = run_cli(["approve", str(run_manifest), "--gate", "production"])
            self.assertEqual(code, 0, error)
            code, _, error = run_cli([
                "configure", str(run_manifest), "--mode", "draft", "--takes-per-shot", "2", "--no-generate-score"
            ])
            self.assertEqual(code, 0, error)
            code, output, error = run_cli(["run", str(run_manifest)])
            self.assertEqual(code, 0, error)
            production_result = json.loads(output)
            self.assertTrue(production_result["result"]["executed"])
            readiness = load_json(project_root / "production-readiness.json")
            assert_contract(self, "film-production-readiness.v1.schema.json", readiness)
            self.assertTrue(readiness["complete"])
            self.assertEqual(
                {item["role"] for item in readiness["models"]},
                {"imageMaster", "imageShot", "video", "visionInspector", "speechTts", "speechAsr", "sfx"},
            )
            vision_readiness = next(item for item in readiness["models"] if item["role"] == "visionInspector")
            self.assertEqual(vision_readiness["status"], "runtime-managed")
            self.assertEqual(vision_readiness["resolvedId"], "mlx-community/Qwen3-VL-2B-Instruct-4bit")
            self.assertTrue((project_root / "cuts" / "rough-cut.mp4").is_file())
            self.assertTrue((project_root / "canon" / "cast" / "keeper.png").is_file())
            self.assertTrue((project_root / "canon" / "locations" / "lamp-room.png").is_file())
            self.assertTrue((project_root / "audio" / "dialogue" / "signal-answered-01.wav").is_file())
            self.assertTrue((project_root / "audio" / "sfx" / "beacon-fails-01.wav").is_file())
            candidates = list((project_root / "clips" / "candidates").glob("*/*.mp4"))
            self.assertEqual(len(candidates), 4)
            take_selection = load_json(project_root / "reviews" / "take-selection.json")
            assert_contract(self, "film-take-selection.v1.schema.json", take_selection)
            self.assertEqual(take_selection["summary"]["candidates"], 4)
            self.assertTrue(all(item["selectedCandidate"] == 2 for item in take_selection["shots"]))
            code, output, error = run_cli(["export-animatic", str(run_manifest)])
            self.assertEqual(code, 0, error)
            export_receipt = json.loads(output)
            handoff_path = pathlib.Path(export_receipt["manifest"])
            handoff = load_json(handoff_path)
            assert_contract(self, "film-animatic-handoff.v1.schema.json", handoff)
            self.assertEqual(export_receipt["manifestSha256"], file_sha256(handoff_path))
            self.assertEqual([shot["timelineStartMilliseconds"] for shot in handoff["shots"]], [0, 2000])
            self.assertEqual([shot["seed"] for shot in handoff["shots"]], [102, 203])
            self.assertTrue(all(shot["keyframeAssetId"] for shot in handoff["shots"]))
            self.assertTrue(all(shot["clipAssetId"] for shot in handoff["shots"]))

            keyframe = project_root / "frames" / "beacon-fails.png"
            original_keyframe = keyframe.read_bytes()
            keyframe.write_bytes(b"tampered")
            code, _, error = run_cli(["export-animatic", str(run_manifest)])
            self.assertEqual(code, 2)
            self.assertIn("hash mismatch", error)
            keyframe.write_bytes(original_keyframe)
            dialogue_qc = load_json(project_root / "reviews" / "dialogue-qc.json")
            self.assertTrue(dialogue_qc["complete"])
            self.assertEqual(dialogue_qc["summary"]["lines"], 1)
            self.assertEqual(dialogue_qc["lines"][0]["wordRecall"], 1.0)
            block_receipt = load_json(project_root / "blocks" / "signal-answered.json")
            self.assertEqual(block_receipt["dialogue"][0]["startSeconds"], 0.5)
            self.assertEqual(block_receipt["transition"], "fade")
            sound_block = load_json(project_root / "blocks" / "beacon-fails.json")
            self.assertEqual(sound_block["soundEffects"][0]["startSeconds"], 0.7)
            self.assertEqual(sound_block["soundEffects"][0]["levelDb"], -9.0)
            sound_qc = load_json(project_root / "reviews" / "sound-qc.json")
            assert_contract(self, "film-sound-qc.v1.schema.json", sound_qc)
            self.assertTrue(sound_qc["complete"])
            self.assertEqual(sound_qc["summary"]["cues"], 1)
            self.assertTrue(sound_qc["cues"][0]["audible"])
            self.assertEqual(sound_qc["cues"][0]["peakDbfs"], -12.0)
            captions = load_json(project_root / "captions" / "captions.json")
            assert_contract(self, "film-captions.v1.schema.json", captions)
            self.assertTrue(captions["complete"])
            self.assertEqual(captions["summary"]["cues"], 1)
            self.assertIn("I hear you.", (project_root / "captions" / "subtitles.en.srt").read_text())
            self.assertTrue((project_root / "production-commands.json").is_file())

            code, output, error = run_cli(["run", str(run_manifest)])
            self.assertEqual(code, 0, error)
            review_result = json.loads(output)
            self.assertEqual(review_result["action"], "independent-review")
            self.assertEqual(review_result["status"]["nextGate"], "picture-lock")
            technical_qc = load_json(project_root / "reviews" / "technical-qc.json")
            self.assertTrue(technical_qc["passed"])
            self.assertTrue(next(item for item in technical_qc["checks"] if item["name"] == "audio-sample-rate")["passed"])
            self.assertTrue(technical_qc["signalAnalysis"]["available"])
            self.assertEqual(technical_qc["signalAnalysis"]["blackSegments"], 0)
            self.assertTrue(technical_qc["loudnessAnalysis"]["available"])
            self.assertEqual(technical_qc["loudnessAnalysis"]["measurement"]["output_i"], "-16.0")
            self.assertEqual(load_json(project_root / "reviews" / "creative-review.json")["decision"], "pass")
            inspection = load_json(project_root / "reviews" / "media-inspection.json")
            self.assertTrue(inspection["complete"])
            self.assertEqual(inspection["summary"]["shots"], 2)
            self.assertEqual(inspection["summary"]["review"], 0)
            self.assertEqual(len(list((project_root / "reviews" / "inspection-frames").glob("*.png"))), 2)
            self.assertEqual(len(list((project_root / "reviews" / "frames").glob("*.png"))), 5)
            review_package = project_root / "reviews" / "index.html"
            self.assertTrue(review_package.is_file())
            self.assertIn("Human gate:", review_package.read_text())
            self.assertIn("independent critic verdict", review_package.read_text())
            self.assertIn("PASS", review_package.read_text())
            self.assertIn("Download approval", review_package.read_text())
            self.assertIn("subtitles.en.vtt", review_package.read_text())
            self.assertEqual(review_result["status"]["reviewPackage"], str(review_package.resolve()))

            code, _, error = run_cli(["approve", str(run_manifest), "--gate", "picture-lock"])
            self.assertEqual(code, 2)
            self.assertIn("humanReview", error)
            binding = production.current_review_binding(
                paths_for_root(project_root),
                load_json(project_root / "film-project.json"),
            )
            decision = {
                "contractVersion": "mere.run/film-human-review.v1",
                "projectId": "the-last-signal",
                "createdAt": "2026-08-14T12:00:00Z",
                "masterSha256": binding["masterSha256"],
                "reviewEvidenceDigest": "stale",
                "decision": "approve",
                "reviewer": "Unit Reviewer",
                "notes": "Watched with captions; picture and sound approved.",
                "rerolls": [],
            }
            decision_path = project_root / "review-decision.json"
            write_json(decision_path, decision)
            code, _, error = run_cli(["review-decision", str(run_manifest), "--input", str(decision_path)])
            self.assertEqual(code, 2)
            self.assertIn("stale", error)
            decision["reviewEvidenceDigest"] = binding["reviewEvidenceDigest"]
            decision["decision"] = "revise"
            decision["notes"] = "The opening needs a longer held look."
            decision["rerolls"] = [{"shotId": "beacon-fails", "note": "Hold on Mara before the relay reacts."}]
            write_json(decision_path, decision)
            code, output, error = run_cli(["review-decision", str(run_manifest), "--input", str(decision_path)])
            self.assertEqual(code, 0, error)
            review_requests = json.loads(output)["status"]["reviewRequests"]
            self.assertEqual(review_requests[0]["shotId"], "beacon-fails")
            self.assertEqual(review_requests[0]["status"], "pending")
            decision["decision"] = "approve"
            decision["notes"] = "Watched with captions; picture and sound approved."
            decision["rerolls"] = []
            write_json(decision_path, decision)
            code, output, error = run_cli(["review-decision", str(run_manifest), "--input", str(decision_path)])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["decision"]["reviewer"], "Unit Reviewer")
            assert_contract(self, "film-human-review.v1.schema.json", load_json(project_root / "reviews" / "human-review.json"))
            self.assertTrue(load_json(project_root / "film-project.json")["proof"]["humanReview"])

            rough_cut = project_root / "cuts" / "rough-cut.mp4"
            original_cut = rough_cut.read_bytes()
            rough_cut.write_bytes(original_cut + b"tampered")
            code, _, error = run_cli(["approve", str(run_manifest), "--gate", "picture-lock"])
            self.assertEqual(code, 2)
            self.assertIn("current rough cut", error)
            rough_cut.write_bytes(original_cut)
            code, _, error = run_cli(["approve", str(run_manifest), "--gate", "picture-lock"])
            self.assertEqual(code, 0, error)
            picture_lock = load_json(project_root / "film-project.json")["approvals"]["picture-lock"]
            self.assertEqual(picture_lock["masterSha256"], file_sha256(rough_cut))
            code, output, error = run_cli(["run", str(run_manifest)])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["action"], "delivery-prepared")
            delivery = load_json(project_root / "delivery" / "delivery-manifest.json")
            assert_contract(self, "film-delivery.v1.schema.json", delivery)
            master = project_root / str(delivery["master"]["path"])
            self.assertEqual(delivery["master"]["sha256"], file_sha256(master))
            self.assertEqual({item["kind"] for item in delivery["captions"]}, {"srt", "vtt"})
            self.assertTrue(all((project_root / item["path"]).is_file() for item in delivery["captions"]))
            self.assertEqual({item["kind"] for item in delivery["marketingAssets"]}, {"poster", "thumbnail"})
            self.assertTrue(all((project_root / item["path"]).is_file() for item in delivery["marketingAssets"]))

            code, output, error = run_cli([
                "approve", str(run_manifest), "--gate", "delivery", "--note", "Master watched and accepted."
            ])
            self.assertEqual(code, 0, error)
            final_status = json.loads(output)
            self.assertEqual(final_status["status"], "completed")
            self.assertTrue(all(final_status["proof"].values()))
            self.assertEqual(load_json(run_manifest)["status"], "succeeded")
            assert_contract(self, "film-project.v1.schema.json", load_json(project_root / "film-project.json"))

            code, output, error = run_cli(["cleanup", str(run_manifest)])
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["cleanup"]["status"], "skipped")
            self.assertTrue(master.is_file())

    def test_plan_mode_writes_commands_without_executing_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project_root = root / "film"
            pi = fake_pi(root / "pi")
            code, output, error = run_cli([*complete_plan_arguments(project_root), "--pi-command", str(pi)])
            self.assertEqual(code, 0, error)
            run_manifest = pathlib.Path(json.loads(output)["status"]["runManifest"])
            for gate_name in ("brief",):
                self.assertEqual(run_cli(["approve", str(run_manifest), "--gate", gate_name])[0], 0)
            self.assertEqual(run_cli(["run", str(run_manifest)])[0], 0)
            self.assertEqual(run_cli(["approve", str(run_manifest), "--gate", "treatment"])[0], 0)
            self.assertEqual(run_cli(["run", str(run_manifest)])[0], 0)
            self.assertEqual(run_cli(["approve", str(run_manifest), "--gate", "production"])[0], 0)
            self.assertEqual(run_cli(["configure", str(run_manifest), "--takes-per-shot", "3"])[0], 0)
            code, output, error = run_cli(["run", str(run_manifest)])
            self.assertEqual(code, 0, error)
            payload = json.loads(output)
            self.assertFalse(payload["result"]["executed"])
            self.assertEqual(payload["result"]["reason"], "production-mode-plan")
            commands = load_json(project_root / "production-commands.json")
            self.assertEqual(commands["resourcePolicy"]["mediaConcurrency"], 1)
            self.assertEqual(commands["resourcePolicy"]["videoCandidatesPerShot"], 3)
            self.assertEqual(sum(item["kind"] == "clip-candidate" for item in commands["jobs"]), 6)
            self.assertEqual(sum(item["kind"] == "take-selection" for item in commands["jobs"]), 2)
            score_job = next(item for item in commands["jobs"] if item["kind"] == "score")
            self.assertEqual(score_job["command"][score_job["command"].index("--model") + 1], "music-acestep")
            dialogue_job = next(item for item in commands["jobs"] if item["kind"] == "dialogue")
            self.assertEqual(
                dialogue_job["command"][dialogue_job["command"].index("--model") + 1],
                "speech-tts-qwen3-nano",
            )
            self.assertEqual(run_cli(["configure", str(run_manifest), "--takes-per-shot", "1"])[0], 0)
            self.assertEqual(run_cli(["run", str(run_manifest)])[0], 0)
            commands = load_json(project_root / "production-commands.json")
            self.assertFalse(any(item["kind"] in {"clip-candidate", "take-selection"} for item in commands["jobs"]))
            self.assertFalse(any((project_root / "clips").glob("*.mp4")))

    def test_agent_print_command_uses_bundled_resources_and_project_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "film"
            code, output, error = run_cli(complete_plan_arguments(root))
            self.assertEqual(code, 0, error)
            run_manifest = pathlib.Path(json.loads(output)["status"]["runManifest"])
            code, output, error = run_cli([
                "agent", "--run-manifest", str(run_manifest), "--pi-command", "custom-pi",
                "--plugin-command", "custom-film", "--isolated", "--print-command",
            ])
            self.assertEqual(code, 0, error)
            payload = json.loads(output)
            command = payload["command"]
            self.assertEqual(command[0], "custom-pi")
            self.assertIn("--extension", command)
            self.assertIn("--skill", command)
            self.assertIn("--prompt-template", command)
            self.assertIn("--no-extensions", command)
            self.assertIn("--no-context-files", command)
            tools = command[command.index("--tools") + 1].split(",")
            self.assertIn("film_reroll", tools)
            self.assertIn("film_record_review_decision", tools)
            self.assertNotIn("write", tools)
            self.assertNotIn("bash", tools)
            self.assertEqual(payload["environment"]["MERE_FILM_RUN_MANIFEST"], str(run_manifest))
            self.assertEqual(payload["environment"]["MERE_FILM_TOOLS_COMMAND"], "custom-film")
            fresh = pathlib.Path(tmp) / "fresh-film"
            code, output, error = run_cli([
                "agent",
                "--idea", "A paper moon falls into a fishing village.",
                "--output-dir", str(fresh),
                "--print-command",
            ])
            self.assertEqual(code, 0, error)
            fresh_payload = json.loads(output)
            self.assertEqual(fresh_payload["status"]["phase"], "intake")
            self.assertTrue((fresh / "run.json").is_file())
            self.assertIn("--no-context-files", fresh_payload["command"])

    def test_agent_print_command_forwards_explicit_local_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "film"
            code, output, error = run_cli(complete_plan_arguments(root))
            self.assertEqual(code, 0, error)
            run_manifest = pathlib.Path(json.loads(output)["status"]["runManifest"])
            with patch.dict(
                "os.environ",
                {
                    "MERE_FILM_TOOLS_PI_PROVIDER": "mere-run",
                    "MERE_FILM_TOOLS_PI_MODEL": "text-chat-gemma4-12b-4bit",
                },
            ):
                code, output, error = run_cli([
                    "agent", "--run-manifest", str(run_manifest), "--pi-command", "custom-pi",
                    "--print-command",
                ])
            self.assertEqual(code, 0, error)
            command = json.loads(output)["command"]
            self.assertEqual(command[:5], [
                "custom-pi", "--provider", "mere-run", "--model", "text-chat-gemma4-12b-4bit",
            ])

    def test_department_contract_parser_and_validation_reject_drift(self) -> None:
        task = {
            "id": "story-development",
            "role": "story-editor",
            "phase": "development",
        }
        parsed = pi_harness.parse_json_output(
            '```json\n{"contractVersion":"mere.run/film-department-result.v1",'
            '"taskId":"story-development","role":"story-editor","phase":"development",'
            '"summary":"clear","decisions":[],"deliverables":{},"risks":[],"questions":[]}\n```'
        )
        pi_harness.validate_department_result(parsed, task)
        parsed["role"] = "director"
        with self.assertRaises(PluginError):
            pi_harness.validate_department_result(parsed, task)
        with self.assertRaises(PluginError):
            pi_harness.parse_json_output("not json")

    def test_reroll_archives_take_and_resets_review_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project_root = root / "film"
            pi = fake_pi(root / "pi")
            mere_run = fake_mere_run(root / "mere.run")
            ffmpeg = fake_ffmpeg(root / "ffmpeg")
            ffprobe = fake_ffprobe(root / "ffprobe")
            code, output, _ = run_cli([
                *complete_plan_arguments(project_root),
                "--pi-command", str(pi),
                "--mere-run-command", str(mere_run),
                "--ffmpeg-command", str(ffmpeg),
                "--ffprobe-command", str(ffprobe),
            ])
            self.assertEqual(code, 0)
            manifest = pathlib.Path(json.loads(output)["status"]["runManifest"])
            self.assertEqual(run_cli(["approve", str(manifest), "--gate", "brief"])[0], 0)
            self.assertEqual(run_cli(["run", str(manifest)])[0], 0)
            self.assertEqual(run_cli(["approve", str(manifest), "--gate", "treatment"])[0], 0)
            self.assertEqual(run_cli(["run", str(manifest)])[0], 0)
            self.assertEqual(run_cli(["approve", str(manifest), "--gate", "production"])[0], 0)
            self.assertEqual(run_cli(["configure", str(manifest), "--mode", "draft", "--no-generate-score"])[0], 0)
            self.assertEqual(run_cli(["run", str(manifest)])[0], 0)
            self.assertEqual(run_cli(["run", str(manifest)])[0], 0)
            project_before_reroll = load_json(project_root / "film-project.json")
            project_before_reroll["reviewRequests"] = [
                {
                    "shotId": "beacon-fails",
                    "note": "Hold on Mara longer.",
                    "status": "pending",
                    "recordedAt": "2026-08-14T12:00:00+00:00",
                }
            ]
            write_json(project_root / "film-project.json", project_before_reroll)
            code, output, error = run_cli([
                "reroll", str(manifest), "--shot", "beacon-fails", "--note", "Hold on Mara longer."
            ])
            self.assertEqual(code, 0, error)
            reroll = json.loads(output)["reroll"]
            self.assertEqual(reroll["nextTake"], 2)
            self.assertEqual(reroll["seed"], 102)
            take_root = project_root / "takes" / "beacon-fails" / "take-001"
            self.assertTrue((take_root / "clips" / "beacon-fails.mp4").is_file())
            self.assertTrue((take_root / "blocks" / "beacon-fails.mp4").is_file())
            self.assertTrue((take_root / "prior-cut" / "cuts" / "rough-cut.mp4").is_file())
            project = load_json(project_root / "film-project.json")
            self.assertEqual(project["reviewRequests"][0]["status"], "applied")
            self.assertEqual(project["reviewRequests"][0]["archivedTake"], 1)
            self.assertFalse(project["proof"]["assembly"])
            self.assertFalse(project["proof"]["review"])
            review_tasks = [item for item in project["departments"] if item["phase"] == "review"]
            self.assertTrue(all(item["status"] == "blocked" for item in review_tasks))
            plan = load_json(project_root / "production-plan.json")
            shot = next(item for item in plan["shots"] if item["id"] == "beacon-fails")
            self.assertEqual(shot["take"], 2)

    def test_doctor_reports_missing_required_executables_and_cleanup_never_deletes(self) -> None:
        code, output, _ = run_cli([
            "doctor",
            "--pi-command", "/definitely/missing/pi",
            "--mere-run-command", "/definitely/missing/mere.run",
            "--ffmpeg-command", "/definitely/missing/ffmpeg",
            "--ffprobe-command", "/definitely/missing/ffprobe",
        ])
        self.assertEqual(code, 3)
        payload = json.loads(output)
        self.assertFalse(payload["ok"])
        self.assertEqual({item["detail"] for item in payload["checks"] if item["required"] and not item["ok"]}, {"not found"})

    def test_doctor_and_new_projects_resolve_mere_run_managed_pi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            pi = fake_pi(root / "managed-pi")
            mere_run = write_executable(
                root / "mere.run",
                f'''\nimport json\n\nprint(json.dumps({{"pi": {{"installed": True, "managedInstall": True, "path": {str(pi)!r}, "version": "v0.84.2"}}}}))\n''',
            )
            ffmpeg = fake_ffmpeg(root / "ffmpeg")
            ffprobe = fake_ffprobe(root / "ffprobe")
            with patch("mere_film_tools.cli.shutil.which", return_value=None):
                code, output, error = run_cli([
                    "doctor",
                    "--pi-command", "pi",
                    "--mere-run-command", str(mere_run),
                    "--ffmpeg-command", str(ffmpeg),
                    "--ffprobe-command", str(ffprobe),
                ])
            self.assertEqual(code, 0, error)
            payload = json.loads(output)
            pi_check = next(item for item in payload["checks"] if item["name"] == "pi")
            self.assertEqual(pi_check["detail"], str(pi.resolve()))

            project_root = root / "film"
            # Planning must use the same missing-PATH-Pi condition as doctor.
            with patch("mere_film_tools.cli.shutil.which", return_value=None):
                code, output, error = run_cli([
                    *complete_plan_arguments(project_root),
                    "--pi-command", "pi",
                    "--mere-run-command", str(mere_run),
                    "--ffmpeg-command", str(ffmpeg),
                    "--ffprobe-command", str(ffprobe),
                ])
            self.assertEqual(code, 0, error)
            run_manifest = pathlib.Path(json.loads(output)["status"]["runManifest"])
            project = load_json(run_manifest.parent / "film-project.json")
            commands = project["production"]["commands"]
            self.assertEqual(commands["pi"], str(pi.resolve()))
            self.assertEqual(commands["mereRun"], str(mere_run))

    def test_missing_model_blocks_before_any_media_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            project_root = root / "film"
            pi = fake_pi(root / "pi")
            media_attempted = root / "media-attempted"
            missing_models = write_executable(
                root / "mere.run",
                f'''\nimport pathlib\nimport sys\n\nif sys.argv[1:3] == ["model", "info"]:\n    print("model is not installed", file=sys.stderr)\n    raise SystemExit(64)\npathlib.Path({str(media_attempted)!r}).write_text("generation started")\nraise SystemExit(1)\n''',
            )
            ffmpeg = fake_ffmpeg(root / "ffmpeg")
            ffprobe = fake_ffprobe(root / "ffprobe")
            code, output, error = run_cli([
                *complete_plan_arguments(project_root),
                "--pi-command", str(pi),
                "--mere-run-command", str(missing_models),
                "--ffmpeg-command", str(ffmpeg),
                "--ffprobe-command", str(ffprobe),
            ])
            self.assertEqual(code, 0, error)
            run_manifest = pathlib.Path(json.loads(output)["status"]["runManifest"])
            self.assertEqual(run_cli(["approve", str(run_manifest), "--gate", "brief"])[0], 0)
            self.assertEqual(run_cli(["run", str(run_manifest)])[0], 0)
            self.assertEqual(run_cli(["approve", str(run_manifest), "--gate", "treatment"])[0], 0)
            self.assertEqual(run_cli(["resume", str(run_manifest), "--execute"])[0], 0)
            code, _, error = run_cli(["preflight", str(run_manifest)])
            self.assertEqual(code, 2)
            self.assertIn("production model readiness failed", error)
            self.assertFalse(media_attempted.exists())
            readiness = load_json(project_root / "production-readiness.json")
            assert_contract(self, "film-production-readiness.v1.schema.json", readiness)
            self.assertEqual(readiness["status"], "blocked")
            self.assertFalse(readiness["complete"])
            project = load_json(project_root / "film-project.json")
            self.assertEqual(project["status"], "revision-required")
            self.assertIn("model-readiness", {item["code"] for item in project["issues"]})

    def test_production_helpers_use_stable_seeds_and_preflight_only_supported_commands(self) -> None:
        self.assertEqual(production.stable_seed("same"), production.stable_seed("same"))
        self.assertNotEqual(production.stable_seed("same"), production.stable_seed("different"))
        image = ["mere.run", "image", "generate", "--output", "x.png"]
        self.assertEqual(production.preflight_command(image), [*image, "--preflight", "--json"])
        self.assertIsNone(production.preflight_command(["ffmpeg", "-i", "x", "y"]))
        with self.assertRaises(PluginError):
            validate_run_id("bad id")
        commercial_project = {
            "brief": {"target": {"usage": "commercial"}},
            "shots": [],
            "production": {"models": {"imageShot": "image-klein-9b", "sfx": "sfx-woosh-dflow"}},
        }
        with self.assertRaisesRegex(PluginError, "known noncommercial"):
            production.validate_usage_policy(commercial_project)
        commercial_project["production"]["models"]["imageShot"] = "commercially-cleared-model"
        production.validate_usage_policy(commercial_project)
        commercial_project["shots"] = [{"soundEffects": [{"prompt": "relay click"}]}]
        with self.assertRaisesRegex(PluginError, "noncommercial SFX model"):
            production.validate_usage_policy(commercial_project)
        commercial_project["production"]["models"]["sfx"] = "commercially-cleared-sfx"
        production.validate_usage_policy(commercial_project)
        self.assertEqual(production.transcript_recall("I hear you.", "i HEAR you"), 1.0)
        self.assertLess(production.transcript_recall("I hear you.", "unrelated noise"), 0.6)
        revision_project = {"jobs": []}
        first = production.upsert_job(
            revision_project,
            {
                "id": "dialogue-shot-01",
                "kind": "dialogue",
                "subject": "shot",
                "dependsOn": [],
                "output": "audio/line.wav",
                "command": ["mere.run", "speech", "synthesize", "old line"],
                "artifactKind": "dialogue-line",
                "contentType": "audio/wav",
            },
        )
        first.update({"status": "succeeded", "sha256": "old", "completedSpecSha256": first["specSha256"]})
        revised = production.upsert_job(
            revision_project,
            {
                "id": "dialogue-shot-01",
                "kind": "dialogue",
                "subject": "shot",
                "dependsOn": [],
                "output": "audio/line.wav",
                "command": ["mere.run", "speech", "synthesize", "revised line"],
                "artifactKind": "dialogue-line",
                "contentType": "audio/wav",
            },
        )
        self.assertEqual(revised["status"], "planned")
        self.assertNotIn("sha256", revised)

    def test_local_vision_retries_one_malformed_response_with_bounded_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            counter = root / "counter"
            vision = write_executable(
                root / "mere.run",
                f'''\nimport json\nimport pathlib\n\ncounter = pathlib.Path({str(counter)!r})\nattempt = int(counter.read_text()) + 1 if counter.exists() else 1\ncounter.write_text(str(attempt))\nif attempt == 1:\n    print('{{"decision":"review","observations":[')\nelse:\n    print(json.dumps({{"decision":"review","observations":["The frame is visibly abstract."],"mismatches":[{{"code":"unreadable","severity":"high","message":"The expected subject is not legible."}}],"confidence":0.95}}))\n''',
            )
            image = root / "frame.png"
            image.write_bytes(b"fake image")
            paths = paths_for_root(root)
            project = {
                "production": {
                    "commands": {"mereRun": str(vision)},
                    "models": {"visionInspector": "auto-qwen3-vl-2b"},
                }
            }
            result = production.run_vision_json(
                paths=paths,
                project=project,
                image=image,
                prompt="Inspect visible continuity.",
                max_tokens=100,
                log_name="retry-test",
                timeout_seconds=30,
                parser=lambda text: production.parse_inspection_response(text, "retry-shot"),
            )
            self.assertEqual(counter.read_text(), "2")
            self.assertEqual(result["decision"], "review")
            self.assertEqual(len(result["mismatches"]), 1)
            with self.assertRaisesRegex(PluginError, "at most 5"):
                production.parse_inspection_response(
                    json.dumps(
                        {
                            "decision": "review",
                            "observations": ["finding"] * 6,
                            "mismatches": [],
                            "confidence": 0.5,
                        }
                    ),
                    "unbounded-shot",
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jsonschema import validate

from mere_workflow_tools import cli, text_lora
from mere_workflow_tools import text_lora_data as data

MODEL = "text-chat-laguna-xs-2-1"


def sft(prompt: str) -> data.JsonMap:
    return {"sources": ["synthetic"], "messages": [
        {"role": "system", "content": "Answer briefly."},
        {"role": "user", "content": prompt}, {"role": "assistant", "content": "example"},
    ]}


def run_cli(args: list[str]) -> tuple[int, str, str]:
    with redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
        result = cli.main_for("dataset", ["text-lora", *args])
    return result, out.getvalue(), err.getvalue()


def write_inputs(root: Path) -> tuple[Path, Path, Path]:
    paths = root / "train.jsonl", root / "hold.jsonl", root / "behavior.jsonl"
    rows: tuple[data.JsonMap, ...] = (
        sft("Write BLUE for the A route"),
        sft("What color is B?"),
        {"id": "c", "prompt": "What color is C?", "expected": r" red\E[2] "},
    )
    for path, row in zip(paths, rows):
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return paths


class TextLoRATests(unittest.TestCase):
    def test_preparation_rejects_cross_split_leakage_and_pins_pack(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch).resolve()
            train, held_out, behavior = write_inputs(root)
            overlap = sft("  WRITE ＢＬＵＥ   for the A route ")
            held_out.write_text(json.dumps(overlap) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prompt appears in both train and held-out"):
                data.prepare_dataset(train, held_out, behavior, root / "rejected")
            self.assertFalse((root / "rejected").exists())
            write_inputs(root)
            prepared = root / "prepared"
            result = data.prepare_dataset(train, held_out, behavior, prepared)
            self.assertEqual(result["counts"], {"train": 1, "heldOut": 1, "behavior": 1})
            self.assertEqual(data.read_json(prepared / data.PACK)["scorer"]["kind"], "assertions")
            behavior.write_text("", encoding="utf-8")
            data.load_dataset(prepared / "dataset.json")
            (prepared / data.CASES).write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "workflow file changed"):
                data.load_dataset(prepared / "dataset.json")

    def test_cli_binds_training_and_reports_matched_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch).resolve()
            train, held_out, behavior = write_inputs(root)
            prepared = root / "prepared"
            code, result, error = run_cli(["prepare", "--train-data", str(train),
                                           "--held-out-data", str(held_out), "--behavior-data", str(behavior),
                                           "--output-dir", str(prepared)])
            self.assertEqual(code, 0, error)
            dataset = Path(json.loads(result)["dataset"])
            train_output = root / "training"
            eval_output = root / "evaluation"

            def native_json(runtime: list[str], *args: str) -> data.JsonMap:
                self.assertTrue(runtime)
                if args[:2] == ("model", "info"):
                    return {"id": MODEL, "upstreamRepoId": "synthetic/test"}
                if args[:3] == ("eval", "pack", "validate"):
                    return {"caseCount": 1, "valid": True, "scorerKind": "assertions", "packSHA256": "a" * 64}
                self.assertEqual(args[:2], ("text", "train-lora"))
                self.assertNotEqual(Path(args[args.index("--data") + 1]), prepared / data.TRAIN)
                self.assertTrue(Path(args[args.index("--eval") + 1]).is_file())
                output = Path(args[args.index("--output") + 1])
                output.write_bytes(b"synthetic adapter")
                summary = {"fingerprint": "b" * 64, "exampleCount": 1}
                data.write_json(output.parent / text_lora.MANIFEST, {
                    "training": {"dataset": summary, "seed": 42, "trainingSteps": 1, "batchSize": 1,
                                 "maxSequenceLength": 4096, "learningRate": 0.0001},
                    "lora": {"rank": 16},
                    "schemaVersion": 1, "status": "trained", "baseModel": MODEL,
                    "outputFile": text_lora.ADAPTER, "evalPromptCount": 1,
                })
                return {
                    "model": MODEL, "status": "trained", "dry_run": False, "eval_prompt_count": 1,
                    "dataset": summary, "training_report": {"steps": 1, "evaluationExampleCount": 1,
                        "evaluationTargetTokenCount": 3, "initialEvaluationLoss": 2, "finalEvaluationLoss": 1},
                }

            def native_report(runtime: list[str], *args: str) -> str:
                self.assertTrue(runtime)
                self.assertEqual(args[:2], ("eval", "run"))
                self.assertNotIn("--allow-external-scorer", args)
                self.assertNotIn("--log-responses", args)
                receipt = data.read_json(train_output / "training.json")
                adapter_sha = receipt["adapter"]["sha256"]
                manifest_sha = receipt["nativeManifest"]["sha256"]
                data.write_json(Path(args[args.index("--output") + 1]), {
                    "schemaVersion": 1, "plan": {
                        "pack": {"packSHA256": "a" * 64, "scorerKind": "assertions"},
                        "models": [{"id": MODEL, "installed": True}],
                        "adapters": [{"slot": "candidate", "sha256": adapter_sha,
                                      "training": {"manifestSHA256": manifest_sha}}],
                    },
                    "progress": {"complete": True, "expectedRows": 2, "completedRows": 2},
                    "results": [{
                        "armID": arm, "caseID": "c", "modelID": MODEL, "profileID": "greedy", "split": "held-out",
                        "adapterSHA256": adapter_sha if arm == "candidate" else None, "passed": arm == "candidate",
                    } for arm in data.ARM_IDS],
                })
                return ""

            with patch.object(text_lora, "native_json", side_effect=native_json):
                code, output, error = run_cli(["train", "--dataset", str(dataset), "--model", MODEL,
                                               "--steps", "1", "--output-dir", str(train_output)])
                self.assertEqual(code, 0, error)
                training = Path(json.loads(output)["training"])
                self.assertEqual(data.read_json(training)["heldOutLoss"], {
                    "before": 2, "after": 1, "examples": 1, "assistantTokens": 3,
                })
                cmd = ["evaluate", "--dataset", str(dataset), "--training", str(training),
                       "--output-dir", str(eval_output)]
                def interrupted(runtime: list[str], *args: str) -> str:
                    self.assertTrue(runtime)
                    Path(args[args.index("--checkpoint") + 1]).write_text("{}")
                    raise ValueError("fixture interruption")

                with patch.object(text_lora, "invoke", side_effect=interrupted):
                    code, _, error = run_cli(cmd)
                self.assertEqual(code, 2)
                self.assertIn("fixture interruption", error)
                self.assertFalse((eval_output / "evaluation.json").exists())
                with patch.object(text_lora, "invoke", side_effect=native_report) as resumed:
                    code, output, error = run_cli([*cmd, "--resume"])
                    self.assertIn("--resume", resumed.call_args.args)
                self.assertEqual(code, 0, error)
                report = data.read_json(Path(json.loads(output)["evaluation"]))
                self.assertEqual(report["comparison"]["deltaPassRate"], 1)
                self.assertEqual(report["comparison"]["improvedCases"], 1)
                schema = Path(__file__).resolve().parents[3] / "contracts" / "text-lora-workflow.v1.schema.json"
                for receipt in (data.read_json(dataset), data.read_json(training), report):
                    validate(receipt, data.read_json(schema))
                (train_output / text_lora.ADAPTER).write_bytes(b"changed")
                code, _, error = run_cli([*cmd[:-1], str(root / "changed")])
                self.assertEqual(code, 2)
                self.assertIn("workflow file changed: adapter.safetensors", error)

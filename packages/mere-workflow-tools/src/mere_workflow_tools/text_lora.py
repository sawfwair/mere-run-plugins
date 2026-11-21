"""Run native text LoRA training and compare the base and candidate on held-out cases."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from .text_lora_data import (
    ARM_IDS,
    CASES,
    EVALUATION_CONTRACT,
    HELD_OUT,
    PACK,
    TRAIN,
    TRAINING_CONTRACT,
    JsonMap,
    array,
    file_pin,
    jsonl,
    load_dataset,
    nonempty,
    object_digest,
    object_map,
    prepare_dataset,
    read_json,
    verify_pin,
    write_json,
)

ADAPTER = "adapter.safetensors"
MANIFEST = "adapter.manifest.json"
NATIVE_COMPLETED = {"trained", "completed"}


def invoke(runtime: list[str], *args: str) -> str:
    try:
        result = subprocess.run([*runtime, *args], stdout=subprocess.PIPE, text=True, check=False)
    except FileNotFoundError:
        raise ValueError(f"Mere Run executable not found: {runtime[0]}") from None
    if result.returncode:
        raise ValueError(f"Mere Run {' '.join(args[:2])} exited with status {result.returncode}")
    return result.stdout


def native_json(runtime: list[str], *args: str) -> JsonMap:
    return object_map(json.loads(invoke(runtime, *args, "--json")), "Mere Run response")


def count(data: JsonMap, key: str) -> int:
    number = data.get(key)
    if type(number) is not int or number < 1:
        raise ValueError(f"expected positive {key}")
    return number


def finite(data: JsonMap, key: str) -> float:
    value = data.get(key)
    if type(value) not in (int, float) or not math.isfinite(cast(float, value)):
        raise ValueError(f"Mere Run did not report finite {key}")
    return float(cast(float, value))


def model_description(runtime: list[str], model: str) -> str:
    description = native_json(runtime, "model", "info", model)
    if description.get("id") != model:
        raise ValueError("installed base model does not match the requested model ID")
    return object_digest(description)


def copy_verified(root: Path, temporary: Path, name: str, expected: object) -> None:
    verify_pin(root, name, expected)
    target = temporary / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / name, target)
    verify_pin(temporary, name, expected)


def train(args: argparse.Namespace, runtime: list[str]) -> JsonMap:
    dataset_path = args.dataset.expanduser().resolve()
    data = load_dataset(dataset_path)
    files = object_map(data["files"], "dataset files")
    counts = object_map(data.get("counts"), "dataset counts")
    model = nonempty(args.model, "base model")
    if model.startswith("-") or "/" in model or "=" in model or any(char.isspace() for char in model):
        raise ValueError("--model requires a canonical managed model ID")
    config = {
        "steps": args.steps, "rank": args.rank, "batchSize": args.batch_size,
        "learningRate": args.learning_rate, "maxSequenceLength": args.max_sequence_length, "seed": args.seed,
    }
    for key in ("steps", "rank", "batchSize", "maxSequenceLength"):
        count(config, key)
    if finite(config, "learningRate") <= 0 or not 0 <= args.seed < 2**64:
        raise ValueError("learning rate must be positive and seed must be an unsigned 64-bit integer")
    model_hash = None if args.dry_run else model_description(runtime, model)
    out = args.output_dir
    out.mkdir(mode=0o700, parents=True)
    request: JsonMap = {
        "datasetSha256": data["datasetSha256"], "model": model, "settings": config,
        "baseModelDescriptionSha256": model_hash,
    }
    if args.resume_from is not None:
        resume = args.resume_from.expanduser().resolve()
        if resume.suffix != ".safetensors":
            raise ValueError("--resume-from requires a .safetensors checkpoint")
        request["resumeFrom"] = file_pin(resume)
    write_json(out / "training-request.json", request)

    with TemporaryDirectory(dir=out, prefix=".inputs-") as location:
        temporary = Path(location)
        for name in (TRAIN, HELD_OUT):
            copy_verified(dataset_path.parent, temporary, name, files[name])
        command = [
            "text", "train-lora", "--model", model, "--data", str(temporary / TRAIN),
            "--eval", str(temporary / HELD_OUT), "--output", str(out / ADAPTER),
            "--steps", str(args.steps), "--rank", str(args.rank), "--batch-size", str(args.batch_size),
            "--learning-rate", str(args.learning_rate), "--max-sequence-length", str(args.max_sequence_length),
            "--seed", str(args.seed),
        ]
        if args.resume_from is not None:
            copy_verified(resume.parent, temporary, resume.name, request["resumeFrom"])
            command.extend(["--resume-from", str(temporary / resume.name)])
        if args.dry_run:
            command.append("--dry-run")
        result = native_json(runtime, *command)

    status = "planned" if args.dry_run else "completed"
    native_manifest = read_json(out / MANIFEST)
    native_status = nonempty(native_manifest.get("status"), "native training status")
    allowed_statuses = {"prepared"} if args.dry_run else NATIVE_COMPLETED
    dataset = object_map(result.get("dataset"), "native training dataset")
    identity = nonempty(dataset.get("fingerprint"), "native dataset fingerprint")
    native_recipe = object_map(native_manifest.get("training"), "native training settings")
    native_dataset = object_map(native_recipe.get("dataset"), "native manifest dataset")
    native_lora = object_map(native_manifest.get("lora"), "native LoRA settings")
    if (result.get("model") != model or result.get("status") != native_status or native_status not in allowed_statuses
            or result.get("dry_run") is not args.dry_run
            or result.get("eval_prompt_count") != count(counts, "heldOut")
            or dataset.get("exampleCount") != count(counts, "train")
            or native_manifest.get("schemaVersion") != 1
            or native_manifest.get("baseModel") != model or native_manifest.get("outputFile") != ADAPTER
            or native_manifest.get("evalPromptCount") != count(counts, "heldOut")
            or native_dataset.get("fingerprint") != identity or native_recipe.get("seed") != args.seed
            or native_recipe.get("trainingSteps") != args.steps
            or native_recipe.get("maxSequenceLength") != args.max_sequence_length
            or native_recipe.get("batchSize") != args.batch_size or native_lora.get("rank") != args.rank
            or not math.isclose(finite(native_recipe, "learningRate"), args.learning_rate, rel_tol=1e-6)):
        raise ValueError("native training evidence does not match the requested workflow")
    receipt: JsonMap = {
        **request, "contractVersion": TRAINING_CONTRACT, "status": status,
        "nativeDatasetFingerprint": identity, "nativeManifest": file_pin(out / MANIFEST),
    }
    if not args.dry_run:
        report = object_map(result.get("training_report"), "native training report")
        if (report.get("steps") != args.steps or report.get("evaluationExampleCount") != count(counts, "heldOut")
                or model_description(runtime, model) != model_hash):
            raise ValueError("native training report or installed base changed during training")
        receipt.update({
            "adapter": file_pin(out / ADAPTER),
            "heldOutLoss": {
                "before": finite(report, "initialEvaluationLoss"), "after": finite(report, "finalEvaluationLoss"),
                "examples": count(report, "evaluationExampleCount"),
                "assistantTokens": count(report, "evaluationTargetTokenCount"),
            },
        })
    write_json(out / "training.json", receipt)
    return {"training": str(out / "training.json"), **receipt}


@contextmanager
def evaluation_lock(out: Path) -> Iterator[None]:
    import fcntl

    with (out / ".evaluation.lock").open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another evaluation is using this directory") from None
        yield


def compare_report(report: JsonMap, cases: set[str], model: str, adapter_sha: object, pack_sha: object,
                   native_sha: object) -> JsonMap:
    plan = object_map(report.get("plan"), "evaluation plan")
    pack = object_map(plan.get("pack"), "evaluation pack identity")
    progress = object_map(report.get("progress"), "evaluation progress")
    models = [object_map(value, "evaluation model") for value in array(plan.get("models"), "models")]
    adapters = [object_map(value, "evaluation adapter") for value in array(plan.get("adapters"), "adapters")]
    if (report.get("schemaVersion") != 1 or pack.get("packSHA256") != pack_sha
            or pack.get("scorerKind") != "assertions" or len(models) != 1
            or models[0].get("id") != model or models[0].get("installed") is not True
            or len(adapters) != 1 or adapters[0].get("slot") != "candidate"
            or adapters[0].get("sha256") != adapter_sha
            or object_map(adapters[0].get("training"), "native training binding").get("manifestSHA256") != native_sha
            or progress.get("complete") is not True or progress.get("expectedRows") != 2 * len(cases)
            or progress.get("completedRows") != 2 * len(cases)):
        raise ValueError("native evaluation plan or completion does not match the requested comparison")
    results: dict[tuple[str, str], bool] = {}
    for value in array(report.get("results"), "evaluation results"):
        row = object_map(value, "evaluation row")
        arm = nonempty(row.get("armID"), "evaluation arm")
        case = nonempty(row.get("caseID"), "evaluation case")
        passed = row.get("passed")
        expected_adapter = adapter_sha if arm == "candidate" else None
        if (arm not in ARM_IDS or case not in cases or (arm, case) in results
                or row.get("modelID") != model or row.get("adapterSHA256") != expected_adapter
                or row.get("profileID") != "greedy" or row.get("split") != "held-out"
                or row.get("response") is not None or not isinstance(passed, bool)):
            raise ValueError("native evaluation contains an unexpected or duplicate result row")
        results[arm, case] = passed
    if len(results) != len(cases) * 2:
        raise ValueError("native evaluation is missing matched result rows")
    base = sum(results["base", case] for case in cases)
    candidate = sum(results["candidate", case] for case in cases)
    return {
        "cases": len(cases), "basePassed": base, "candidatePassed": candidate,
        "basePassRate": base / len(cases), "candidatePassRate": candidate / len(cases),
        "deltaPassRate": (candidate - base) / len(cases),
        "improvedCases": sum(not results["base", case] and results["candidate", case] for case in cases),
        "regressedCases": sum(results["base", case] and not results["candidate", case] for case in cases),
    }


def evaluate(args: argparse.Namespace, runtime: list[str]) -> JsonMap:
    dataset_path = args.dataset.expanduser().resolve()
    data = load_dataset(dataset_path)
    training_path = args.training.expanduser().resolve()
    training = read_json(training_path)
    if (training.get("contractVersion") != TRAINING_CONTRACT or training.get("status") != "completed"
            or training.get("datasetSha256") != data["datasetSha256"]):
        raise ValueError("evaluation requires a completed training receipt for this prepared dataset")
    if args.max_tokens < 1:
        raise ValueError("--max-tokens must be positive")
    model = nonempty(training.get("model"), "trained model")
    model_hash = model_description(runtime, model)
    if model_hash != training.get("baseModelDescriptionSha256"):
        raise ValueError("installed base model description differs from training")
    files = object_map(data["files"], "dataset files")
    adapter = object_map(training.get("adapter"), "trained adapter")
    manifest = object_map(training.get("nativeManifest"), "native training manifest")
    request: JsonMap = {
        "datasetSha256": data["datasetSha256"], "model": model, "baseModelDescriptionSha256": model_hash,
        "adapter": adapter, "nativeManifest": manifest, "maxTokens": args.max_tokens,
    }
    out = args.output_dir
    if not args.resume:
        out.mkdir(mode=0o700, parents=True)
    with evaluation_lock(out), TemporaryDirectory(dir=out, prefix=".inputs-") as location:
        request_path = out / "evaluation-request.json"
        if args.resume:
            if read_json(request_path) != request or (out / "evaluation.json").exists():
                raise ValueError("evaluation directory is completed or belongs to a different request")
        else:
            write_json(request_path, request)
        temporary = Path(location)
        for name in (PACK, CASES):
            copy_verified(dataset_path.parent, temporary, name, files[name])
        copy_verified(training_path.parent, temporary, ADAPTER, adapter)
        copy_verified(training_path.parent, temporary, MANIFEST, manifest)
        native_manifest = read_json(temporary / MANIFEST)
        native_training = object_map(native_manifest.get("training"), "native training settings")
        native_dataset = object_map(native_training.get("dataset"), "native training dataset")
        native_status = nonempty(native_manifest.get("status"), "native training status")
        if (native_status not in NATIVE_COMPLETED or native_manifest.get("baseModel") != model
                or native_manifest.get("outputFile") != ADAPTER
                or native_dataset.get("fingerprint") != training.get("nativeDatasetFingerprint")):
            raise ValueError("evaluation requires the completed native manifest for the trained dataset")
        pack = temporary / "evaluation"
        info = native_json(runtime, "eval", "pack", "validate", str(pack))
        cases = {nonempty(row.get("id"), "case ID") for _, row in jsonl(temporary / CASES)}
        counts = object_map(data.get("counts"), "dataset counts")
        if (len(cases) != count(counts, "behavior") or info.get("caseCount") != len(cases)
                or info.get("valid") is not True or info.get("scorerKind") != "assertions"):
            raise ValueError("native evaluation pack lost prepared cases or changed scorer")
        pack_sha = nonempty(info.get("packSHA256"), "validated native pack SHA-256")
        report_path = out / "native-evaluation.json"
        command = [
            "eval", "run", str(pack), "--model", f"base={model}", "--adapter", f"candidate={temporary / ADAPTER}",
            "--max-tokens", str(args.max_tokens), "--checkpoint", str(out / "checkpoint.json"),
            "--output", str(report_path),
        ]
        if args.resume and (out / "checkpoint.json").is_file():
            command.append("--resume")
        invoke(runtime, *command)
        scores = compare_report(read_json(report_path), cases, model, adapter["sha256"], pack_sha, manifest["sha256"])
        if model_description(runtime, model) != model_hash:
            raise ValueError("installed base model description changed during evaluation")
        receipt: JsonMap = {
            **request, "contractVersion": EVALUATION_CONTRACT, "nativePackSha256": pack_sha,
            "nativeReport": file_pin(report_path), "comparison": scores,
        }
        write_json(out / "evaluation.json", receipt)
    return {"evaluation": str(out / "evaluation.json"), "report": str(report_path), **receipt}


def run(args: argparse.Namespace, runtime: list[str]) -> JsonMap:
    if args.text_lora_operation == "prepare":
        return prepare_dataset(
            args.train_data.expanduser(), args.held_out_data.expanduser(), args.behavior_data.expanduser(), args.output_dir,
        )
    if args.text_lora_operation == "train":
        return train(args, runtime)
    return evaluate(args, runtime)


def add_commands(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="text_lora_operation", required=True)
    prepare = sub.add_parser("prepare", help="Validate, separate, and seal the three input files.")
    for flag in ("train-data", "held-out-data", "behavior-data"):
        prepare.add_argument(f"--{flag}", required=True, type=Path)
    train_cmd = sub.add_parser("train", help="Train a native LoRA and record held-out loss.")
    eval_cmd = sub.add_parser("evaluate", help="Compare the base model and adapter on held-out behavior.")
    for command in (prepare, train_cmd, eval_cmd):
        command.add_argument("--output-dir", required=True, type=Path)
    for command in (train_cmd, eval_cmd):
        command.add_argument("--dataset", required=True, type=Path, help="Prepared dataset.json receipt.")
        command.add_argument("--mere-run-command", default="")
    train_cmd.add_argument("--model", required=True, help="Installed managed text model ID.")
    train_cmd.add_argument("--steps", type=int, default=600)
    train_cmd.add_argument("--rank", type=int, default=16)
    train_cmd.add_argument("--batch-size", type=int, default=1)
    train_cmd.add_argument("--learning-rate", type=float, default=0.0001)
    train_cmd.add_argument("--max-sequence-length", type=int, default=4096)
    train_cmd.add_argument("--seed", type=int, default=42)
    train_cmd.add_argument("--dry-run", action="store_true")
    train_cmd.add_argument("--resume-from", type=Path, help="Existing native optimizer-bearing checkpoint.")
    eval_cmd.add_argument("--training", required=True, type=Path, help="Completed training.json receipt.")
    eval_cmd.add_argument("--max-tokens", type=int, default=128)
    eval_cmd.add_argument("--resume", action="store_true", help="Resume a matching interrupted evaluation.")

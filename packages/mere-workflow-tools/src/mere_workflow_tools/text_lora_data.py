"""Prepare and verify a local three-way split for text LoRA training."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from .graph_provider import file_sha256

JsonMap = dict[str, object]
DATASET_CONTRACT = "mere.run/text-lora-dataset.v1"
TRAINING_CONTRACT = "mere.run/text-lora-training.v1"
EVALUATION_CONTRACT = "mere.run/text-lora-evaluation.v1"
TRAIN = "train.jsonl"
HELD_OUT = "held-out.jsonl"
PACK = "evaluation/eval-pack.json"
CASES = "evaluation/cases.jsonl"
DATASET_FILES = (TRAIN, HELD_OUT, PACK, CASES)
ARM_IDS = ("base", "candidate")
CASE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}")


def object_map(value: object, label: str) -> JsonMap:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return cast(JsonMap, value)


def array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return cast(list[object], value)


def nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def unique_object(pairs: list[tuple[str, object]]) -> JsonMap:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON keys")
    return value


def read_json(path: Path) -> JsonMap:
    return object_map(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object), path.name)


def write_json(path: Path, value: object) -> None:
    with path.with_suffix(".tmp").open("w", encoding="utf-8") as file:
        json.dump(value, file, indent=2, sort_keys=True, allow_nan=False)
        file.write("\n")
    path.with_suffix(".tmp").replace(path)


def object_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_pin(path: Path) -> JsonMap:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing regular workflow file: {path.name}")
    return {"bytes": path.stat().st_size, "sha256": file_sha256(path)}


def verify_pin(root: Path, name: str, expected: object) -> None:
    path = root / name
    if path.resolve() != root / name or file_pin(path) != expected:
        raise ValueError(f"workflow file changed: {name}")


def jsonl(path: Path) -> Iterator[tuple[int, JsonMap]]:
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield index, object_map(json.loads(line, object_pairs_hook=unique_object), "record")
            except ValueError as exc:
                raise ValueError(f"{path.name}:{index}: {exc}") from None


def register_prompt(text: str, split: str, seen: dict[str, str]) -> None:
    normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    prior = seen.setdefault(digest, split)
    if prior != split:
        raise ValueError(f"user prompt appears in both {prior} and {split}")


def check_sft(row: JsonMap, split: str, seen: dict[str, str]) -> None:
    if set(row) - {"id", "sources", "messages"}:
        raise ValueError("SFT records support id, sources, and plain-text messages")
    if "id" in row:
        nonempty(row["id"], "sample id")
    sources = array(row.get("sources"), "sources")
    if not sources:
        raise ValueError("sources must contain at least one label")
    for source in sources:
        nonempty(source, "source label")
    messages = array(row.get("messages"), "messages")
    if len(messages) < 3 or object_map(messages[0], "first message").get("role") != "system":
        raise ValueError("native SFT requires an initial system message and at least one user-assistant turn")
    expected = "user"
    for index, raw in enumerate(messages):
        message = object_map(raw, "message")
        if set(message) != {"role", "content"}:
            raise ValueError("messages support only role and text content")
        role = message["role"]
        content = nonempty(message["content"], "message content")
        if len(content.strip()) < 4:
            raise ValueError("native SFT messages must contain at least four characters")
        if index == 0 and role == "system":
            continue
        if role != expected:
            raise ValueError("after the system message, alternate user and assistant messages")
        if role == "user":
            register_prompt(content, split, seen)
        expected = "assistant" if role == "user" else "user"
    if not messages or object_map(messages[-1], "last message").get("role") != "assistant":
        raise ValueError("an SFT record must end with a supervised assistant response")


def copy_sft(source: Path, destination: Path, split: str, seen: dict[str, str]) -> int:
    count = 0
    with destination.open("w", encoding="utf-8") as output:
        for line, row in jsonl(source):
            try:
                check_sft(row, split, seen)
            except ValueError as exc:
                raise ValueError(f"{source.name}:{line}: {exc}") from None
            output.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            count += 1
    if not count:
        raise ValueError(f"{split} must contain at least one SFT record")
    return count


def behavioral_cases(source: Path, destination: Path, seen: dict[str, str]) -> int:
    case_ids: set[str] = set()
    with destination.open("w", encoding="utf-8") as stream:
        for line, row in jsonl(source):
            try:
                if set(row) != {"id", "prompt", "expected"}:
                    raise ValueError("behavior records require id, prompt, and expected")
                case_id = nonempty(row["id"], "id")
                if not CASE_ID.fullmatch(case_id) or case_id in case_ids:
                    raise ValueError("case IDs must be unique and contain only letters, digits, dots, underscores, or dashes")
                case_ids.add(case_id)
                prompt = nonempty(row["prompt"], "prompt")
                expected = nonempty(row["expected"], "expected").strip()
                register_prompt(prompt, "behavior", seen)
            except ValueError as exc:
                raise ValueError(f"{source.name}:{line}: {exc}") from None
            quoted = expected.replace(r"\E", r"\E\\E\Q")
            stream.write(json.dumps({
                "id": case_id, "split": "held-out", "capability_tags": ["exact-response"],
                "messages": [{"role": "user", "content": prompt}], "metadata": {},
                "assertions": [{"id": "exact-response", "kind": "regex", "case_insensitive": False, "value": rf"\A\s*\Q{quoted}\E\s*\z"}],
            }, sort_keys=True, allow_nan=False) + "\n")
    if not case_ids:
        raise ValueError("behavior must contain at least one case")
    return len(case_ids)


def evaluation_pack() -> JsonMap:
    return {
        "schema_version": 1, "id": "text-lora-comparison", "version": "1.0.0",
        "description": "Matched exact-response checks for a local text LoRA.",
        "case_files": ["cases.jsonl"], "prompt_sets": [], "gates": [],
        "arms": [
            {"id": "base", "model_slot": "base", "adapter_scale": 1},
            {"id": "candidate", "model_slot": "base", "adapter_slot": "candidate", "adapter_scale": 1},
        ],
        "sampling_profiles": [{
            "id": "greedy", "temperature": 0, "top_p": 1, "top_k": 1, "min_p": 0, "show_thinking": False,
        }],
        "scorer": {"kind": "assertions", "arguments": [], "timeout_seconds": 30},
        "defaults": {"trials": 1, "max_tokens": 128, "context_size": 2048, "logprobs": "none", "top_logprobs": 5},
        "adapter_requirements": {
            "require_training_manifest": True, "require_base_model_match": True,
            # Runtime 0.73 writes "trained"; its evaluator uses "completed".
            # The plugin checks the native completion marker against the receipt.
            "require_completed_training": False,
        },
    }


@contextmanager
def dataset_staging(output: Path) -> Iterator[Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise ValueError(f"output directory already exists: {output}")
    with TemporaryDirectory(dir=output.parent, prefix=".text-lora-") as location:
        staging = Path(location)
        yield staging
        output.mkdir(mode=0o700)
        try:
            staging.replace(output)
        except OSError:
            output.rmdir()
            raise


def prepare_dataset(train: Path, held_out: Path, behavior: Path, output: Path) -> JsonMap:
    seen: dict[str, str] = {}
    with dataset_staging(output) as staging:
        (staging / "evaluation").mkdir()
        counts = {
            "train": copy_sft(train, staging / TRAIN, "train", seen),
            "heldOut": copy_sft(held_out, staging / HELD_OUT, "held-out", seen),
            "behavior": behavioral_cases(behavior, staging / CASES, seen),
        }
        write_json(staging / PACK, evaluation_pack())
        payload: JsonMap = {
            "contractVersion": DATASET_CONTRACT, "counts": counts,
            "files": {name: file_pin(staging / name) for name in DATASET_FILES},
        }
        payload["datasetSha256"] = object_digest(payload)
        write_json(staging / "dataset.json", payload)
    return {"dataset": str(output / "dataset.json"), "datasetSha256": payload["datasetSha256"], "counts": counts}


def load_dataset(path: Path) -> JsonMap:
    root = path.parent
    data = read_json(path)
    if data.get("contractVersion") != DATASET_CONTRACT:
        raise ValueError("unsupported prepared text LoRA dataset")
    digest = data.get("datasetSha256")
    if digest != object_digest({key: value for key, value in data.items() if key != "datasetSha256"}):
        raise ValueError("prepared text LoRA dataset manifest changed")
    files = object_map(data.get("files"), "dataset files")
    if files.keys() != set(DATASET_FILES):
        raise ValueError("prepared dataset has an unexpected file inventory")
    for name in DATASET_FILES:
        verify_pin(root, name, files[name])
    if read_json(root / PACK) != evaluation_pack():
        raise ValueError("the prepared evaluation pack must use the linked base and candidate assertion arms")
    return data

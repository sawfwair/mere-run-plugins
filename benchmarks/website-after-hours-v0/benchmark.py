"""Prepare isolated website entries and summarize evidence-backed manual reviews."""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent


def read_json(path: Path) -> object:
    value: object = json.loads(path.read_text())
    return value


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected an object with string keys")
    return dict(value)


def sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected an array")
    return list(value)


def string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonempty string")
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def checks() -> list[dict[str, object]]:
    return [mapping(item) for item in sequence(read_json(ROOT / "checks.json"))]


def ids_for(stage: str) -> list[str]:
    kinds = {"stable", "adjacency"} if stage == "stage1" else {"stable", "change"}
    return [string(case["id"]) for case in checks() if case["kind"] in kinds]


def result_template() -> dict[str, object]:
    return {
        "entry": "A",
        "stage1": {key: {"status": "pending", "observation": None, "evidence": None} for key in ids_for("stage1")},
        "stage2": {
            key: {
                "status": "pending", "observation": None, "evidence": None,
                **({"failureCause": None} if key == "C05" else {}),
            }
            for key in ids_for("stage2")
        },
        "reviews": [],
        "resourceUse": {"stage1": None, "stage2": None},
    }


def statuses(value: object, expected: list[str]) -> dict[str, str]:
    records = mapping(value)
    if set(records) != set(expected):
        raise ValueError("Case IDs do not match the required stage cases")
    result: dict[str, str] = {}
    for key, value in records.items():
        record = mapping(value)
        status = string(record.get("status"))
        if status not in {"pass", "fail", "pending"}:
            raise ValueError(f"{key}: status must be pass, fail, or pending")
        if status != "pending":
            string(record.get("observation"))
            string(record.get("evidence"))
        if key == "C05" and status == "fail":
            if string(record.get("failureCause")) not in {"stage1-prerequisite", "site-behavior"}:
                raise ValueError("C05: failureCause must be stage1-prerequisite or site-behavior")
        elif record.get("failureCause") is not None:
            raise ValueError("failureCause is only used for a failed C05")
        result[key] = status
    return result


def metric(values: list[str]) -> dict[str, object]:
    passed = values.count("pass")
    pending = values.count("pending")
    return {
        "passed": passed,
        "failed": values.count("fail"),
        "pending": pending,
        "total": len(values),
        "percent": None if pending or not values else round(100 * passed / len(values), 2),
    }


def score(value: object) -> dict[str, object]:
    record = mapping(value)
    entry = string(record.get("entry"))
    if entry not in "ABCDE" or len(entry) != 1:
        raise ValueError("Entry must be A, B, C, D, or E")
    before = statuses(record.get("stage1"), ids_for("stage1"))
    after = statuses(record.get("stage2"), ids_for("stage2"))
    stable = [string(case["id"]) for case in checks() if case["kind"] == "stable"]
    changed = [string(case["id"]) for case in checks() if case["kind"] == "change"]
    eligible = [key for key in stable if before[key] == "pass"]
    broken = [key for key in eligible if after[key] == "fail"]
    pending_before = [key for key in stable if before[key] == "pending"]
    pending_after = [key for key in eligible if after[key] == "pending"]
    regression: Optional[float] = None
    if eligible and not pending_before and not pending_after:
        regression = round(100 * len(broken) / len(eligible), 2)
    return {
        "entry": entry,
        "initialFunctionality": metric(list(before.values())),
        "updatedFunctionality": metric([after[key] for key in stable]),
        "changedRuleSuccess": metric([after[key] for key in changed]),
        "migration": {
            "status": after["C05"],
            "failureCause": mapping(mapping(record["stage2"])["C05"]).get("failureCause"),
            "interpretation": "A stage1-prerequisite failure is not an observed migration failure.",
        },
        "regression": {
            "brokenCases": broken,
            "previouslyPassingStableCases": len(eligible),
            "pendingStage1Cases": pending_before,
            "pendingStage2Cases": pending_after,
            "percent": regression,
        },
        "reviewMethod": "manual browser observations; evidence contents are not verified by this calculator",
    }


def validate() -> dict[str, object]:
    cases = checks()
    case_ids = [string(case["id"]) for case in cases]
    if len(set(case_ids)) != 32 or len(cases) != 32:
        raise ValueError("Expected 32 unique cases")
    for kind, count in (("stable", 24), ("adjacency", 2), ("change", 6)):
        if sum(case["kind"] == kind for case in cases) != count:
            raise ValueError(f"Expected {count} {kind} cases")
    for case in cases:
        string(case["action"])
        string(case["expected"])
    studio = mapping(read_json(ROOT / "starter/data/studio.json"))
    rooms = [mapping(room) for room in sequence(studio["rooms"])]
    room_ids = [string(room["id"]) for room in rooms]
    if len(rooms) != 6 or len(set(room_ids)) != 6:
        raise ValueError("Expected six unique rooms")
    for room in rooms:
        asset = ROOT / "starter" / string(room["image"])
        if not asset.is_file() or asset.suffix != ".svg":
            raise ValueError("Missing room illustration")
        for field in ("capacity", "hourlyRateCents"):
            number = room[field]
            if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
                raise ValueError(f"Invalid {field}")
    bookings = [mapping(item) for item in sequence(read_json(ROOT / "starter/data/bookings.json"))]
    if len(bookings) != 4 or len({string(item["id"]) for item in bookings}) != 4:
        raise ValueError("Expected four unique seed reservations")
    for booking in bookings:
        if booking["roomId"] not in room_ids or not string(booking["start"]) < string(booking["end"]):
            raise ValueError("Invalid seed reservation")
    for name in ("README.md", "PROMPT.md", "FOLLOW_UP.md", "PROTOCOL.md", "REVIEW.md", "RUN_SETUP.md"):
        string((ROOT / name).read_text())
    score(result_template())
    return {"valid": True, "stage1Cases": 26, "stableCases": 24, "changedRuleCases": 6, "rooms": 6}


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
    }


def prepare(destination: Path) -> dict[str, object]:
    validate()
    destination = destination.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("Keep campaign output outside the benchmark source directory")
    # Exclusive creation preserves any previous attempt, including an empty directory.
    destination.mkdir(parents=True, exist_ok=False)
    operator = destination / "operator"
    operator.mkdir()
    for name in ("FOLLOW_UP.md", "PROTOCOL.md", "REVIEW.md", "RUN_SETUP.md", "checks.json", "benchmark.py"):
        shutil.copyfile(ROOT / name, operator / name)
    write_json(operator / "result-template.json", result_template())
    participants: list[dict[str, object]] = []
    for entry in "ABCDE":
        folder = destination / "entries" / entry
        folder.mkdir(parents=True)
        shutil.copytree(ROOT / "starter", folder / "site")
        shutil.copyfile(ROOT / "PROMPT.md", folder / "PROMPT.md")
        participants.append({
            "entry": entry,
            "modelConfiguration": None,
            "baselineContext": None,
            "initialFilesSha256": file_hashes(folder),
        })
    write_json(operator / "manifest.json", {
        "benchmark": "website-after-hours-v0",
        "status": "prepared-not-run",
        "protocolFrozen": False,
        "runSettings": None,
        "participants": participants,
        "packFilesSha256": file_hashes(ROOT),
    })
    return {"prepared": str(destination), "entries": 5, "modelsRun": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--output", type=Path, required=True)
    score_parser = commands.add_parser("score")
    score_parser.add_argument("result", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            output = validate()
        elif args.command == "prepare":
            output = prepare(args.output)
        else:
            output = score(read_json(args.result))
    except (ValueError, OSError, KeyError) as error:
        sys.stderr.write(f"{error}\n")
        raise SystemExit(1) from error
    sys.stdout.write(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()

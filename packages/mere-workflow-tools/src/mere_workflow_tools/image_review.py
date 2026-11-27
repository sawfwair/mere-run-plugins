"""Generate a local image and select at most one reviewer-requested redraw."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
from typing import cast

from PIL import Image, ImageDraw, ImageOps

from .cli import JsonMap, PluginError, eprint, write_json

AUDIT = (
    "Review this image against the creative brief below, including its intended style. "
    "Describe what you actually see. Keep it if it satisfies the brief. If a concrete visible problem "
    "warrants a redraw, explain it and write a standalone image-generation prompt that fixes it while "
    "preserving the brief and successful details. Return only JSON with observation, evidence, "
    'decision ("keep" or "repair"), and generator_prompt (empty when keeping).'
)
JUDGE = (
    "Which image better satisfies the creative brief below? A is on the left and B on the right. "
    "Assess visible quality and fidelity to the brief. Choose tie for no meaningful difference. "
    'Return only JSON with reason, winner ("A", "B", or "tie"), and numeric confidence from 0 to 1.'
)
THRESHOLD = 0.75
MAX_SEED = (1 << 64) - 1


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prompt", required=True, help="Creative brief for generation and review.")
    parser.add_argument("--model", default=os.environ.get("MERE_NEMOTRON_MODEL") or "image-nemotron-labs-30b-a3b",
                        help="Installed Nemotron image model ID or checkpoint path (env: MERE_NEMOTRON_MODEL).")
    parser.add_argument("--reviewer", default="vision-chat-inkling-2-mini", help="Installed Inkling model ID or path.")
    parser.add_argument("--output-dir", type=pathlib.Path, help="New run directory (default: unique directory in runs/).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--mere-run-command", default="", help="Native mere.run command.")


def render(native: list[str], folder: pathlib.Path, name: str, prompt: str, args: argparse.Namespace,
           initial_seed: int, attempts: list[JsonMap]) -> int:
    """Retry only the native decoder's incomplete image block, using successive seeds."""
    path = folder / f"{name}.png"
    for offset in range(3):
        seed = (initial_seed + offset) & MAX_SEED
        log = folder / f"{name}-{seed}.log"
        attempts.append({"image": name, "seed": seed, "log": log.name})
        eprint(f"Rendering {name} with seed {seed}.")
        with log.open("w") as output:
            result = subprocess.run([*native, "image", "generate", "--model", args.model, "--prompt", prompt,
                                     "--width", str(args.width), "--height", str(args.height), "--seed", str(seed),
                                     "--output", str(path)], stdout=output, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            with Image.open(path) as image:
                if image.format != "PNG" or image.size != (args.width, args.height):
                    raise PluginError(f"Unexpected render dimensions or format: {path}")
                image.load()
            return seed
        if offset == 2 or "without a complete image block" not in log.read_text(errors="replace"):
            raise PluginError(f"Generation failed. See {log}")
    raise AssertionError("Generation attempts exhausted")


def review(native: list[str], folder: pathlib.Path, stage: str, image: pathlib.Path,
           reviewer: str, prompt: str) -> JsonMap:
    (folder / f"{stage}-prompt.txt").write_text(prompt, encoding="utf-8")
    reply = folder / f"{stage}-reply.txt"
    log = folder / f"{stage}.log"
    eprint(f"Requesting {stage} from {reviewer}.")
    with reply.open("w") as out, log.open("w") as err:
        proc = subprocess.run([*native, "text", "chat", "--model", reviewer, "--image", str(image), "--prompt", prompt,
                               "--max-tokens", "1536", "--temperature", "0.2", "--reasoning-effort", "0.2",
                               "--require-installed", "--quiet"], stdout=out, stderr=err)
    if proc.returncode:
        raise PluginError(f"{stage} failed. See {log}")
    raw = reply.read_text(encoding="utf-8").strip()
    lines = raw.splitlines()
    if len(lines) >= 3 and lines[0].lower() in {"```", "```json"} and lines[-1] == "```":
        raw = "\n".join(lines[1:-1])
    try:
        response: object = json.loads(raw)
    except ValueError as exc:
        raise PluginError(f"Invalid {stage} JSON. See {reply}") from exc
    if not isinstance(response, dict):
        raise PluginError(f"Expected {stage} object. See {reply}")
    return cast(JsonMap, response)


def comparison_sheet(left: pathlib.Path, right: pathlib.Path, out: pathlib.Path) -> None:
    sheet = Image.new("RGB", (1024, 554), "white")
    draw = ImageDraw.Draw(sheet)
    for x, label, source in ((0, "A", left), (512, "B", right)):
        draw.text((x + 14, 4), label, fill="black", font_size=30)
        with Image.open(source) as image:
            panel = ImageOps.contain(image, (512, 512), Image.Resampling.LANCZOS)
            sheet.paste(panel, (x + (512 - panel.width) // 2, 42 + (512 - panel.height) // 2))
    sheet.save(out)


def prefer_redraw(native: list[str], folder: pathlib.Path, original: pathlib.Path, candidate: pathlib.Path,
                  reviewer: str, prompt: str, comparisons: list[JsonMap]) -> bool:
    wins = []
    for stage, left, right in (("pair-1", candidate, original), ("pair-2", original, candidate)):
        sheet = folder / f"{stage}.png"
        comparison_sheet(left, right, sheet)
        vote = review(native, folder, stage, sheet, reviewer, prompt)
        winner, confidence = vote.get("winner"), vote.get("confidence")
        if (winner not in ("A", "B", "tie") or isinstance(confidence, bool)
                or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
            raise PluginError(f"Invalid winner or confidence in {stage}.")
        choice = {"A": left.stem, "B": right.stem, "tie": "tie"}[str(winner)]
        comparisons.append({"A": left.stem, "B": right.stem, "choice": choice, "reply": vote})
        wins.append(choice == "candidate" and confidence >= THRESHOLD)
    return all(wins)


def generate(args: argparse.Namespace, native: list[str]) -> JsonMap:
    if not args.prompt.strip() or not 0 <= args.seed <= MAX_SEED or min(args.width, args.height) <= 0:
        raise PluginError("Supply a nonempty prompt, positive dimensions, and an unsigned 64-bit seed.")
    if args.output_dir is None:
        parent = pathlib.Path("runs").resolve()
        parent.mkdir(exist_ok=True)
        folder = pathlib.Path(tempfile.mkdtemp(prefix="reviewed-image-", dir=parent))
    else:
        folder = pathlib.Path(args.output_dir).resolve()
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise PluginError(f"Output directory already exists: {folder}") from exc
    eprint(f"Image review run: {folder}")
    original = folder / "original.png"
    candidate = folder / "candidate.png"
    selected = folder / "selected.png"
    attempts: list[JsonMap] = []
    comparisons: list[JsonMap] = []
    result: JsonMap = {"prompt": args.prompt, "generator": args.model, "reviewer": args.reviewer,
                       "width": args.width, "height": args.height, "threshold": THRESHOLD, "attempts": attempts,
                       "comparisons": comparisons, "directory": str(folder), "status": "running", "selected": None}
    report = folder / "result.json"
    write_json(report, result)
    brief = "\n\nCreative brief:\n" + args.prompt
    try:
        seed = render(native, folder, "original", args.prompt, args, args.seed, attempts)
        shutil.copyfile(original, selected)
        result.update(selected="original", output=str(selected))
        write_json(report, result)
        audit = review(native, folder, "audit", original, args.reviewer, AUDIT + brief)
        result["audit"] = audit
        decision = audit.get("decision")
        if decision == "keep":
            result["reason"] = "reviewer_kept_original"
        elif decision == "repair":
            prompt = audit.get("generator_prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise PluginError("Reviewer requested a repair without a generator prompt.")
            render(native, folder, "candidate", prompt, args, (seed + 1) & MAX_SEED, attempts)
            if prefer_redraw(native, folder, original, candidate, args.reviewer, JUDGE + brief, comparisons):
                temporary = folder / "selected.tmp"
                shutil.copyfile(candidate, temporary)
                temporary.replace(selected)
                result.update(selected="candidate", reason="both_orders_prefer_candidate")
            else:
                result["reason"] = "original_retained_after_comparison"
        else:
            raise PluginError("Reviewer decision must be keep or repair.")
        result["status"] = "complete"
    except (OSError, ValueError, PluginError, KeyboardInterrupt) as exc:
        result.update(status="failed", error=str(exc) or "Interrupted")
        raise
    finally:
        write_json(report, result)
    return result

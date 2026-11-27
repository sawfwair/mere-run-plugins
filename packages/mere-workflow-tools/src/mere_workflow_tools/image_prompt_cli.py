"""Signed bundle and source entrypoint for prompt-driven image review."""

import sys

from .cli import main_for


def main() -> int:
    args = sys.argv[1:]
    commands = {"manifest", "doctor", "plan", "run", "resume", "cleanup", "generate", "generate-reviewed"}
    if len(args) == 1 and not args[0].startswith("-") and args[0] not in commands:
        args = ["generate-reviewed", "--prompt=" + args[0]]
    return main_for("image_prompt", args)


if __name__ == "__main__":
    raise SystemExit(main())

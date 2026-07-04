from .cli import main_for


def main() -> int:
    return main_for("batch")


if __name__ == "__main__":
    raise SystemExit(main())

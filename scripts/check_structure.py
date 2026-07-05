from __future__ import annotations

import ast
import pathlib
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE_SRC_ROOTS = sorted(ROOT.glob("packages/*/src/*"))
MAX_README_WORDS = 500


@dataclass(frozen=True)
class ModuleInfo:
    name: str
    path: pathlib.Path
    imports: tuple[str, ...]


def fail(message: str) -> None:
    raise SystemExit(f"check_structure: {message}")


def module_name(package_root: pathlib.Path, path: pathlib.Path) -> str:
    return ".".join((path.relative_to(package_root.parent).with_suffix("")).parts)


def resolve_relative_import(module: str, level: int, package: str) -> str:
    parts = package.split(".")
    if level > len(parts):
        return module
    prefix = parts[: len(parts) - level + 1]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def imported_modules(package_root: pathlib.Path, path: pathlib.Path) -> tuple[str, ...]:
    package_name = package_root.name
    current_module = module_name(package_root, path)
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(package_name + "."):
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                target = resolve_relative_import(node.module or "", node.level, current_module)
            else:
                target = node.module or ""
            if target == package_name or target.startswith(package_name + "."):
                imports.add(target)
    return tuple(sorted(imports))


def load_modules(package_root: pathlib.Path) -> dict[str, ModuleInfo]:
    modules: dict[str, ModuleInfo] = {}
    for path in sorted(package_root.rglob("*.py")):
        name = module_name(package_root, path)
        modules[name] = ModuleInfo(name=name, path=path, imports=imported_modules(package_root, path))
    return modules


def collapse_to_known_module(import_name: str, modules: dict[str, ModuleInfo]) -> str | None:
    parts = import_name.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return None


def internal_edges(modules: dict[str, ModuleInfo]) -> dict[str, tuple[str, ...]]:
    edges: dict[str, tuple[str, ...]] = {}
    for name, info in modules.items():
        targets: set[str] = set()
        for import_name in info.imports:
            target = collapse_to_known_module(import_name, modules)
            if target and target != name:
                targets.add(target)
        edges[name] = tuple(sorted(targets))
    return edges


def find_cycle(edges: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        if node in visiting:
            start = stack.index(node)
            return tuple(stack[start:] + [node])
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for target in edges.get(node, ()):
            cycle = visit(target)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(edges):
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def check_package_readme(package_root: pathlib.Path) -> None:
    readme = package_root / "README.md"
    if not readme.is_file():
        fail(f"{package_root.relative_to(ROOT)} is missing README.md orientation")
    words = readme.read_text().split()
    if len(words) > MAX_README_WORDS:
        fail(f"{readme.relative_to(ROOT)} must stay under {MAX_README_WORDS} words")


def check_package(package_root: pathlib.Path) -> None:
    if not (package_root / "py.typed").is_file():
        fail(f"{package_root.relative_to(ROOT)} is missing py.typed")
    check_package_readme(package_root)
    modules = load_modules(package_root)
    cycle = find_cycle(internal_edges(modules))
    if cycle:
        fail(f"internal import cycle in {package_root.name}: {' -> '.join(cycle)}")


def main() -> int:
    if not PACKAGE_SRC_ROOTS:
        fail("no package source roots found")
    for package_root in PACKAGE_SRC_ROOTS:
        if package_root.is_dir() and not package_root.name.endswith(".egg-info"):
            check_package(package_root)
    sys.stdout.write("check_structure: ok\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

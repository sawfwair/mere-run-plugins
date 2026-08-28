"""Collect upstream license texts from a reviewed AnyDoc Cargo metadata snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import tomllib


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--missing-notices", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    metadata = json.loads(args.metadata.read_text())
    if Path(metadata["workspace_root"]).resolve() != source:
        raise ValueError("Cargo metadata must belong to the reviewed source checkout")
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"]):
        raise ValueError("Use a clean immutable upstream checkout")
    version = tomllib.loads((source / "Cargo.toml").read_text())["package"]["version"]
    locked = tomllib.loads((source / "Cargo.lock").read_text())["package"]
    checksums = {(item["name"], item["version"]): item.get("checksum") for item in locked}
    packages = {item["id"]: item for item in metadata["packages"]}
    nodes = {item["id"]: item for item in metadata["resolve"]["nodes"]}
    queue = [next(item["id"] for item in packages.values() if item["name"] == "anydoc-python")]
    selected: set[str] = set()
    while queue:
        identity = queue.pop()
        if identity in selected:
            continue
        selected.add(identity)
        queue.extend(dep["pkg"] for dep in nodes[identity]["deps"]
                     if any(kind["kind"] != "dev" for kind in dep["dep_kinds"]))

    records = []
    texts: dict[str, bytes] = {}
    for package in sorted((packages[key] for key in selected), key=lambda value: (value["name"], value["version"])):
        root = Path(package["manifest_path"]).parent
        candidates = [path for path in root.rglob("*") if path.is_file() and
                      path.name.lower().startswith(("license", "copying", "notice", "unlicense"))]
        override_source = None
        if package["source"] is None:
            candidates = [source / "LICENSE"]
            root = source
        elif not candidates:
            root = args.missing_notices / f"{package['name']}-{package['version']}"
            override = json.loads((root / "source.json").read_text())
            crate_revision = json.loads((Path(package["manifest_path"]).parent / ".cargo_vcs_info.json").read_text())["git"]["sha1"]
            if override["commit"] != crate_revision:
                raise ValueError("Supplemental license source must match the published crate revision")
            override_source = override
            candidates = [root / name for name in override["files"]]
        if not candidates or not package["license"]:
            raise ValueError(f"Missing license information: {package['name']}")
        files = []
        for path in sorted(candidates):
            data = path.read_bytes()
            data.decode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            texts[digest] = data
            files.append({"path": str(path.relative_to(root)), "sha256": digest})
        checksum = checksums[(package["name"], package["version"])] if package["source"] else None
        records.append({"name": package["name"], "version": package["version"], "license": package["license"],
                        "crateSHA256": checksum, "repository": package["repository"],
                        "supplementalSource": override_source, "licenseFiles": files})

    header = (f"AnyDoc {version} native dependency notices\n"
              f"Upstream source: https://github.com/firecrawl/anydoc/tree/{revision}\n\n"
              "The companion anydoc-native-inventory.json maps each package to its license texts below.\n"
              "This includes Cargo build dependencies and can exceed the linked runtime dependency set.\n"
              "Upstream license texts are preserved verbatim.\n")
    notices = header.encode()
    for digest, data in sorted(texts.items()):
        notices += f"\n{'=' * 72}\nLicense text SHA-256: {digest}\n{'=' * 72}\n".encode() + data + b"\n"
    inventory = {"package": "firecrawl-anydoc", "version": version, "sourceCommit": revision,
                 "target": "aarch64-apple-darwin", "cargoLockSHA256": hashlib.sha256((source / "Cargo.lock").read_bytes()).hexdigest(),
                 "scope": "Cargo non-dev dependency closure including build dependencies; not a binary composition attestation",
                 "noticesSHA256": hashlib.sha256(notices).hexdigest(), "packages": records}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "anydoc-native-notices.txt").write_bytes(notices)
    (args.output / "anydoc-native-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    sys.stdout.write(json.dumps({"licenseTexts": len(texts), "cargoPackages": len(records)}) + "\n")


if __name__ == "__main__":
    main()

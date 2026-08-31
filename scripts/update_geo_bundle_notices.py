"""Build the reviewed native-license inventory for the Geo Tools bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import tomllib

RASTERIO_COMPONENTS = [
    ("c-blosc", "1.21.6", "BSD-3-Clause", ["libblosc.1.21.6.dylib"], ["LICENSE.txt"]),
    ("curl", "8.20.0", "curl", ["libcurl.4.dylib"], ["COPYING"]),
    (
        "gdal",
        "3.12.4",
        "MIT AND BSD-2-Clause AND BSD-3-Clause AND Apache-2.0",
        ["libgdal.38.3.12.4.dylib"],
        [
            "LICENSE.TXT",
            "alg/internal_libqhull/COPYING.txt",
            "third_party/LercLib/LICENSE",
            "third_party/LercLib/NOTICE",
            "third_party/fast_float/LICENSE-MIT",
            "third_party/libdivide/LICENSE.txt",
        ],
    ),
    ("giflib", "5.2.2", "MIT", ["libgif.7.2.0.dylib"], ["COPYING"]),
    (
        "hdf5",
        "2.1.1",
        "BSD-3-Clause-like",
        ["libhdf5.320.1.1.dylib", "libhdf5_hl.320.0.2.dylib"],
        ["LICENSE"],
    ),
    ("libjpeg-turbo", "3.1.4", "BSD-3-Clause AND IJG AND Zlib", ["libjpeg.8.3.2.dylib"], ["LICENSE.md"]),
    ("json-c", "0.18", "MIT", ["libjson-c.5.4.0.dylib"], ["COPYING"]),
    ("lerc", "4.0.0", "Apache-2.0", ["libLerc.4.dylib"], ["LICENSE", "NOTICE"]),
    ("libaec", "1.1.7", "BSD-2-Clause", ["libaec.0.1.7.dylib", "libsz.2.0.1.dylib"], ["LICENSE.txt"]),
    ("libdeflate", "1.24", "MIT", ["libdeflate.0.dylib"], ["COPYING"]),
    ("libpng", "1.6.58", "Libpng", ["libpng16.16.dylib"], ["LICENSE"]),
    ("libwebp", "1.6.0", "BSD-3-Clause", ["libwebp.7.dylib", "libsharpyuv.0.dylib"], ["COPYING", "PATENTS"]),
    (
        "netcdf-c",
        "4.10.1",
        "BSD-3-Clause",
        ["libnetcdf.22.dylib"],
        ["COPYRIGHT", "libncpoco/COPYRIGHT", "libncxml/license.txt"],
    ),
    ("nghttp2", "1.69.0", "MIT", ["libnghttp2.14.dylib"], ["COPYING"]),
    ("openjpeg", "2.5.4", "BSD-2-Clause", ["libopenjp2.2.5.4.dylib"], ["LICENSE"]),
    ("openssl", "3.6.2", "Apache-2.0", ["libcrypto.3.dylib", "libssl.3.dylib"], ["LICENSE.txt"]),
    ("pcre2", "10.47", "BSD-3-Clause", ["libpcre2-8.0.dylib"], ["COPYING", "deps/sljit/LICENSE"]),
    ("proj", "9.8.1", "MIT", ["libproj.25.9.8.1.dylib"], ["COPYING"]),
    ("sqlite", "3.53.1", "blessing", ["libsqlite3.3.53.1.dylib"], ["sqlite3.h"]),
    ("libtiff", "4.7.1", "libtiff", ["libtiff.6.dylib"], ["LICENSE.md"]),
    (
        "xz",
        "5.8.3",
        "0BSD",
        ["liblzma.5.dylib"],
        ["COPYING", "COPYING.0BSD"],
    ),
    ("zlib", "1.3.2", "Zlib", ["libz.1.3.2.dylib"], ["LICENSE"]),
    ("zstd", "1.5.7", "BSD-3-Clause OR GPL-2.0-only", ["libzstd.1.5.7.dylib"], ["LICENSE", "COPYING"]),
]

WHEEL_URLS = {
    "numcodecs": "https://files.pythonhosted.org/packages/81/38/88e40d40288b73c3b3a390ed5614a34b0661d00255bdd4cfb91c32101364/numcodecs-0.15.1-cp312-cp312-macosx_11_0_arm64.whl",
    "rasterio": "https://files.pythonhosted.org/packages/87/88/95d2d41889f86fc7f532caf672c789db1ecf48fcf56a62c6a26450025c65/rasterio-1.5.1-cp312-cp312-macosx_14_0_arm64.whl",
    "safetensors": "https://files.pythonhosted.org/packages/f5/b1/fa7c600e7dceae12e9606c7578cbc9ff1e1ed55844883ee5c92205e86226/safetensors-0.8.0-cp310-abi3-macosx_11_0_arm64.whl",
}

SDIST_RECORDS = {
    "numcodecs": {
        "url": "https://files.pythonhosted.org/packages/63/fc/bb532969eb8236984ba65e4f0079a7da885b8ac0ce1f0835decbb3938a62/numcodecs-0.15.1.tar.gz",
        "sha256": "eeed77e4d6636641a2cc605fbc6078c7a8f2cc40f3dfa2b3f61e52e6091b04ff",
    },
    "safetensors": {
        "url": "https://files.pythonhosted.org/packages/45/06/f955dbbb1859e3bd23c8ac6141af5106e7ad5fedec4a3a6e3d60f94b7001/safetensors-0.8.0.tar.gz",
        "sha256": "fabaf3e0f18a6618d9b36560682562157f77c2b71fcffc7b432be2baed9d753d",
    },
}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def add_text(texts: dict[str, bytes], path: Path, *, excerpt_lines: int | None = None) -> dict[str, object]:
    data = path.read_bytes()
    if excerpt_lines is not None:
        data = b"".join(data.splitlines(keepends=True)[:excerpt_lines])
    data.decode("utf-8")
    digest = sha_bytes(data)
    texts[digest] = data
    record: dict[str, object] = {"path": path.name, "sha256": digest}
    if excerpt_lines is not None:
        record["lines"] = f"1-{excerpt_lines}"
    return record


def wheel_record(name: str, path: Path) -> dict[str, str]:
    return {"url": WHEEL_URLS[name], "sha256": sha(path), "filename": path.name}


def cargo_records(
    source: Path,
    metadata_path: Path,
    supplemental_records: dict[str, dict[str, object]],
    texts: dict[str, bytes],
) -> list[dict[str, object]]:
    metadata = json.loads(metadata_path.read_text())
    workspace = Path(metadata["workspace_root"]).resolve()
    if workspace != (source / "bindings/python").resolve():
        raise ValueError("Cargo metadata must belong to the reviewed Safetensors sdist")
    lock = tomllib.loads((source / "bindings/python/Cargo.lock").read_text())["package"]
    checksums = {(item["name"], item["version"]): item.get("checksum") for item in lock}
    packages = {item["id"]: item for item in metadata["packages"]}
    nodes = {item["id"]: item for item in metadata["resolve"]["nodes"]}
    queue = [next(item["id"] for item in packages.values() if item["name"] == "safetensors-python")]
    selected: set[str] = set()
    while queue:
        identity = queue.pop()
        if identity in selected:
            continue
        selected.add(identity)
        queue.extend(
            dep["pkg"]
            for dep in nodes[identity]["deps"]
            if any(kind["kind"] != "dev" for kind in dep["dep_kinds"])
        )

    records = []
    for package in sorted((packages[item] for item in selected), key=lambda value: (value["name"], value["version"])):
        root = Path(package["manifest_path"]).parent
        license_expression = package["license"]
        candidates = [
            path
            for path in root.rglob("*")
            if path.is_file() and path.name.lower().startswith(("license", "copying", "notice", "unlicense"))
        ]
        supplemental = None
        if package["source"] is None:
            if package["name"] == "safetensors-python":
                root = source
                candidates = [source / "LICENSE"]
                license_expression = "Apache-2.0"
            else:
                candidates = [root / "LICENSE"]
        elif not candidates:
            supplemental = supplemental_records[f"{package['name']}@{package['version']}"]
            root = Path(supplemental["root"])
            candidates = [root / item for item in supplemental["files"]]
        if not candidates or not license_expression:
            raise ValueError(f"Missing Safetensors Cargo license information: {package['name']}")
        files = []
        for path in sorted(candidates):
            record = add_text(texts, path)
            record["path"] = str(path.relative_to(root))
            files.append(record)
        checksum = checksums[(package["name"], package["version"])] if package["source"] else None
        public_supplemental = None
        if supplemental:
            public_supplemental = {key: value for key, value in supplemental.items() if key != "root" and key != "files"}
        records.append(
            {
                "name": package["name"],
                "version": package["version"],
                "license": license_expression,
                "crateSHA256": checksum,
                "repository": package["repository"],
                "supplementalSource": public_supplemental,
                "licenseFiles": files,
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rasterio-sources", type=Path, required=True)
    parser.add_argument("--rasterio-build-config", type=Path, required=True)
    parser.add_argument("--rasterio-wheel", type=Path, required=True)
    parser.add_argument("--numcodecs-source", type=Path, required=True)
    parser.add_argument("--numcodecs-wheel", type=Path, required=True)
    parser.add_argument("--codec-supplemental", type=Path, required=True)
    parser.add_argument("--safetensors-source", type=Path, required=True)
    parser.add_argument("--safetensors-wheel", type=Path, required=True)
    parser.add_argument("--safetensors-metadata", type=Path, required=True)
    parser.add_argument("--safetensors-supplemental", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    texts: dict[str, bytes] = {}
    source_records = {item["name"]: item for item in json.loads(args.rasterio_sources.read_text())}
    components = []
    expected_libraries: set[str] = set()
    for name, version, license_expression, libraries, license_paths in RASTERIO_COMPONENTS:
        source_record = source_records[name]
        if source_record["version"] != version:
            raise ValueError(f"Rasterio native source version mismatch: {name}")
        root = Path(source_record["root"])
        files = []
        for item in license_paths:
            record = add_text(texts, root / item, excerpt_lines=14 if name == "sqlite" else None)
            record["path"] = item
            files.append(record)
        components.append(
            {
                "name": name,
                "version": version,
                "license": license_expression,
                "libraries": libraries,
                "source": {key: source_record[key] for key in ("url", "sha256")},
                "licenseFiles": files,
            }
        )
        expected_libraries.update(libraries)

    with zipfile.ZipFile(args.rasterio_wheel) as archive:
        observed_libraries = {
            Path(name).name
            for name in archive.namelist()
            if name.startswith("rasterio/.dylibs/") and name.endswith(".dylib")
        }
    if observed_libraries != expected_libraries:
        raise ValueError(
            f"Rasterio dylib inventory mismatch; missing={sorted(observed_libraries - expected_libraries)}, "
            f"extra={sorted(expected_libraries - observed_libraries)}"
        )

    codec_sources = {
        "lz4": {
            "version": "1.9.4",
            "license": "BSD-2-Clause",
            "url": "https://github.com/lz4/lz4/archive/refs/tags/v1.9.4.tar.gz",
            "archive": args.codec_supplemental / "lz4-1.9.4.tar.gz",
            "root": args.codec_supplemental / "lz4-1.9.4/lz4-1.9.4",
            "files": ["LICENSE"],
        },
        "zlib": {
            "version": "1.3.1",
            "license": "Zlib",
            "url": SDIST_RECORDS["numcodecs"]["url"],
            "archive": args.numcodecs_source.parent / "numcodecs-0.15.1.tar.gz",
            "root": args.numcodecs_source,
            "files": ["c-blosc/internal-complibs/zlib-1.3.1/LICENSE"],
        },
        "zstd": {
            "version": "1.5.6",
            "license": "BSD-3-Clause OR GPL-2.0-only",
            "url": "https://github.com/facebook/zstd/archive/refs/tags/v1.5.6.tar.gz",
            "archive": args.codec_supplemental / "zstd-1.5.6.tar.gz",
            "root": args.codec_supplemental / "zstd-1.5.6/zstd-1.5.6",
            "files": ["LICENSE", "COPYING"],
        },
    }
    codec_records = []
    for name, value in codec_sources.items():
        license_files = []
        for item in value["files"]:
            record = add_text(texts, value["root"] / item)
            record["path"] = item
            license_files.append(record)
        codec_records.append(
            {
                "name": name,
                "version": value["version"],
                "license": value["license"],
                "source": {"url": value["url"], "sha256": sha(value["archive"])},
                "licenseFiles": license_files,
            }
        )
    rasterio_blosc = next(item for item in components if item["name"] == "c-blosc")
    rasterio_blosc["embeddedComponents"] = [
        {
            **item,
            "source": (
                {
                    "url": source_records["c-blosc"]["url"],
                    "sha256": source_records["c-blosc"]["sha256"],
                }
                if item["name"] == "zlib"
                else item["source"]
            ),
        }
        for item in codec_records
    ]
    numcodecs_license = add_text(texts, args.numcodecs_source / "LICENSE.txt")
    numcodecs_license["path"] = "LICENSE.txt"
    blosc_license = add_text(texts, args.numcodecs_source / "c-blosc/LICENSE.txt")
    blosc_license["path"] = "c-blosc/LICENSE.txt"

    supplemental_sources = json.loads((args.safetensors_supplemental / "sources.json").read_text())
    supplemental_by_name = {item["name"]: item for item in supplemental_sources}
    supplement_mapping: dict[str, dict[str, object]] = {}
    mappings = {
        "block2@0.6.2": ("objc2-b4167b5", ["LICENSE.md"]),
        "dispatch2@0.3.1": ("objc2-8852b42", ["LICENSE.md"]),
        "objc2@0.6.4": ("objc2-8852b42", ["LICENSE.md"]),
        "objc2-core-foundation@0.3.2": ("objc2-7b1abfd", ["LICENSE.md"]),
        "objc2-encode@4.1.0": ("objc2-8d214f5", ["LICENSE.md"]),
        "objc2-metal@0.3.2": ("objc2-7b1abfd", ["LICENSE.md"]),
        "r-efi@6.0.0": ("r-efi-7e1b032", ["AUTHORS"]),
        "wasip3@0.4.0+wasi-0.3.0-rc-2026-01-06": (
            "wasi-rs-06ce201",
            ["LICENSE-APACHE", "LICENSE-Apache-2.0_WITH_LLVM-exception", "LICENSE-MIT"],
        ),
    }
    for package in ("wasm-encoder", "wasmparser", "wit-component", "wit-parser"):
        mappings[f"{package}@0.244.0"] = (
            "wasm-tools-d4e317f",
            ["LICENSE-APACHE", "LICENSE-Apache-2.0_WITH_LLVM-exception", "LICENSE-MIT"],
        )
    for package, (source_name, files) in mappings.items():
        source_record = supplemental_by_name[source_name]
        supplement_mapping[package] = {
            "root": source_record["root"],
            "files": files,
            "url": source_record["url"],
            "sha256": source_record["sha256"],
        }
    cargo_packages = cargo_records(
        args.safetensors_source, args.safetensors_metadata, supplement_mapping, texts
    )

    header = (
        "Mere Geo Tools native dependency notices\n\n"
        "The companion geo-native-inventory.json maps the packaged Rasterio dylibs, "
        "Numcodecs codec sources, and Safetensors Cargo packages to the license texts below.\n"
        "The Safetensors Cargo inventory conservatively includes non-development build and "
        "target dependencies and can exceed the linked macOS runtime set.\n"
        "The Rasterio inventory matches the exact arm64 CPython 3.12 wheel and the upstream "
        "1.5.1 macOS wheel build configuration.\n"
        "Upstream license texts and explicitly identified excerpts are preserved verbatim.\n"
    )
    notices = header.encode()
    for digest, data in sorted(texts.items()):
        notices += (
            f"\n{'=' * 72}\nLicense text SHA-256: {digest}\n{'=' * 72}\n".encode() + data + b"\n"
        )

    inventory = {
        "schemaVersion": 1,
        "target": "aarch64-apple-darwin",
        "scope": "License inventory; not a binary composition attestation",
        "noticesSHA256": sha_bytes(notices),
        "rasterio": {
            "package": "rasterio",
            "version": "1.5.1",
            "wheel": wheel_record("rasterio", args.rasterio_wheel),
            "buildConfig": {
                "url": "https://raw.githubusercontent.com/rasterio/rasterio/1.5.1/ci/config.sh",
                "sha256": sha(args.rasterio_build_config),
            },
            "nativeComponents": components,
        },
        "numcodecs": {
            "package": "numcodecs",
            "version": "0.15.1",
            "wheel": wheel_record("numcodecs", args.numcodecs_wheel),
            "source": SDIST_RECORDS["numcodecs"],
            "setupPySHA256": sha(args.numcodecs_source / "setup.py"),
            "license": "MIT",
            "licenseFiles": [numcodecs_license],
            "embeddedComponents": [
                {
                    "name": "c-blosc",
                    "version": "1.21.6",
                    "license": "BSD-3-Clause",
                    "source": SDIST_RECORDS["numcodecs"],
                    "licenseFiles": [blosc_license],
                },
                *codec_records,
            ],
        },
        "safetensors": {
            "package": "safetensors",
            "version": "0.8.0",
            "wheel": wheel_record("safetensors", args.safetensors_wheel),
            "source": SDIST_RECORDS["safetensors"],
            "cargoLockSHA256": sha(args.safetensors_source / "bindings/python/Cargo.lock"),
            "cargoPackages": cargo_packages,
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "geo-native-notices.txt").write_bytes(notices)
    (args.output / "geo-native-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    sys.stdout.write(
        json.dumps(
            {
                "licenseTexts": len(texts),
                "rasterioComponents": len(components),
                "rasterioLibraries": len(observed_libraries),
                "safetensorsCargoPackages": len(cargo_packages),
            }
        ) + "\n"
    )


if __name__ == "__main__":
    main()

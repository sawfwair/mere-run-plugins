"""Install the pinned, signed Cua Driver macOS app without optional packages."""

from __future__ import annotations

import hashlib
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

VERSION = "0.28.2"
ARCHIVE = f"cua-driver-rs-{VERSION}-darwin-arm64.tar.gz"
URL = f"https://github.com/trycua/cua/releases/download/cua-driver-rs-v{VERSION}/{ARCHIVE}"
SHA256 = "818ddefa0fa8ba2ec9cba837c7aa634a4b064221c748752cf49c5b08e2c94e8c"
TEAM_ID = "YCK386LBJ7"
APP = pathlib.Path("/Applications/CuaDriver.app")
BIN_LINK = pathlib.Path.home() / ".local/bin/cua-driver"


class SetupError(RuntimeError):
    pass


def checked(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise SetupError(f"{' '.join(command[:2])} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout + result.stderr


def verify_app(app: pathlib.Path) -> None:
    checked(["codesign", "--verify", "--deep", "--strict", str(app)])
    checked(["spctl", "--assess", "--type", "exec", str(app)])
    identity = checked(["codesign", "-dv", "--verbose=4", str(app)])
    if f"TeamIdentifier={TEAM_ID}" not in identity.splitlines():
        raise SetupError("Cua Driver signing team does not match the reviewed release")
    bundle = checked(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleIdentifier", str(app / "Contents/Info.plist")])
    if bundle.strip() != "com.trycua.driver":
        raise SetupError("Cua Driver bundle identifier does not match com.trycua.driver")


def download(archive: pathlib.Path) -> None:
    digest = hashlib.sha256()
    with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != SHA256:
        raise SetupError("Cua Driver release SHA-256 mismatch; nothing was installed")


def setup(install: bool) -> dict[str, object]:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SetupError("Cua Driver setup currently supports Apple Silicon macOS")
    binary = APP / "Contents/MacOS/cua-driver"
    link = BIN_LINK
    if APP.exists():
        verify_app(APP)
        version = checked([str(binary), "--version"]).strip()
        match = re.fullmatch(r"cua-driver (\d+)\.(\d+)\.(\d+)", version)
        if match is None or tuple(map(int, match.groups())) < (0, 28, 2):
            raise SetupError(f"existing {version} found; use the official Cua installer to upgrade or repair it")
        if link.is_symlink() and link.resolve() == binary.resolve():
            return {"status": "already-installed", "version": version.removeprefix("cua-driver "),
                    "app": str(APP), "command": str(link)}
        if link.exists() or link.is_symlink():
            raise SetupError(f"existing Cua Driver command needs manual review: {link}")
        if install:
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(binary)
            return {"status": "linked-existing-app", "version": version.removeprefix("cua-driver "),
                    "app": str(APP), "command": str(link)}
        return {"status": "needs-link", "version": version.removeprefix("cua-driver "),
                "app": str(APP), "command": str(link)}
    if link.exists() or link.is_symlink():
        raise SetupError(f"existing Cua Driver command needs manual review: {link}")
    if not install:
        return {"status": "ready-to-install", "version": VERSION, "license": "MIT", "url": URL,
                "sha256": SHA256, "app": str(APP), "command": str(link)}
    if not os.access(APP.parent, os.W_OK):
        raise SetupError("/Applications is not writable; Cua Driver needs its app bundle there for macOS permissions")
    with tempfile.TemporaryDirectory(prefix="mere-cua-driver-") as temporary:
        root = pathlib.Path(temporary)
        archive = root / ARCHIVE
        download(archive)
        with tarfile.open(archive, "r:gz") as source:
            source.extractall(root / "unpacked")
        staged = root / "unpacked" / ARCHIVE.removesuffix(".tar.gz") / "CuaDriver.app"
        if not staged.is_dir():
            raise SetupError("verified release archive has no CuaDriver.app")
        verify_app(staged)
        if APP.exists() or APP.is_symlink():
            raise SetupError("CuaDriver.app appeared during setup; refusing to replace it")
        copied = False
        try:
            copied = True
            checked(["ditto", str(staged), str(APP)])
            verify_app(APP)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(binary)
        except (OSError, SetupError):
            if link.is_symlink() and link.resolve() == binary.resolve():
                link.unlink()
            if copied and APP.exists():
                shutil.rmtree(APP)
            raise
    return {"status": "installed", "version": VERSION, "license": "MIT", "sha256": SHA256,
            "app": str(APP), "command": str(link), "permissions": "run cua-driver permissions grant"}

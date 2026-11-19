"""Install the separately distributed Firecrawl Local macOS application."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import cast

APP_NAME = "Firecrawl Local.app"
VERSION = "0.1.1"
ENDPOINT = "http://127.0.0.1:3002"
RELEASE = f"https://mere.run/releases/firecrawl-local/{VERSION}"
IMAGE = f"{RELEASE}/firecrawl-local-{VERSION}-macos-arm64.dmg"
IMAGE_SIZE = 11_786_803
IMAGE_SHA256 = "3c7109f917eef8c2232a8f77cfc85566265b0e97cc2d94b5732657fbbfea3cb9"
REQUIREMENT = (
    'anchor apple generic and identifier "run.mere.distribution.firecrawl-local"'
    ' and certificate leaf[subject.OU] = "S5JDPCT8RC"'
    ' and certificate 1[field.1.2.840.113635.100.6.2.6] exists'
    ' and certificate leaf[field.1.2.840.113635.100.6.1.13] exists'
)
SYSTEM_APP = Path("/Applications") / APP_NAME


class SetupError(RuntimeError):
    pass


def supported_mac() -> bool:
    major = platform.mac_ver()[0].partition(".")[0]
    return sys.platform == "darwin" and platform.machine() == "arm64" and major.isdigit() and int(major) >= 15


def local_version() -> str | None:
    connection = http.client.HTTPConnection("127.0.0.1", 3002, timeout=1)
    try:
        try:
            connection.connect()
        except ConnectionRefusedError:
            return None
        connection.request("GET", "/health")
        response = connection.getresponse()
        if response.status == 200:
            data: object = json.loads(response.read(4096))
            if isinstance(data, dict):
                health = cast(dict[str, object], data)
                version = health.get("version")
                if health.get("engine") == "firecrawl-local" and health.get("status") == "ok" and isinstance(version, str):
                    return version
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise SetupError("Port 3002 did not respond as Firecrawl Local. Check the service using that port.") from error
    finally:
        connection.close()
    raise SetupError("Port 3002 is in use by an unrecognized service. Leave it running and configure MERE_FIRECRAWL_URL.")


def run_tool(executable: str, args: list[str], action: str, timeout: int = 45) -> None:
    try:
        result = subprocess.run(
            [executable, *args], stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError(f"{action}: {error}") from error
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise SetupError(f"{action}: {detail[:500] or f'exit status {result.returncode}'}")


def verify_app(app: Path) -> None:
    if not app.is_dir() or app.is_symlink():
        raise SetupError(f"{app} is not a standalone application directory.")
    run_tool("/usr/bin/codesign", ["--verify", "--deep", "--strict", f"-R={REQUIREMENT}", str(app)],
             f"Could not verify {app}")


def verify_image(image: Path) -> None:
    digest = hashlib.sha256()
    with image.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    if image.stat().st_size != IMAGE_SIZE or digest.hexdigest() != IMAGE_SHA256:
        raise SetupError("Firecrawl Local disk image does not match the published checksum.")
    run_tool("/usr/sbin/spctl", ["--assess", "--type", "open", "--context", "context:primary-signature", str(image)],
             "macOS rejected the Firecrawl Local disk image")


def install_app(destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix=".mere-firecrawl-local-", dir=destination.parent) as temporary:
        root = Path(temporary)
        image = root / "firecrawl-local.dmg"
        run_tool("/usr/bin/curl", ["--disable", "--fail", "--silent", "--show-error", "--proto", "=https",
                 "--max-time", "120", "--max-filesize", str(IMAGE_SIZE), "--output", str(image), IMAGE],
                 "Could not download Firecrawl Local", timeout=125)
        verify_image(image)
        mount = root / "mount"
        mount.mkdir()
        run_tool("/usr/bin/hdiutil", ["attach", "-readonly", "-nobrowse", "-noautoopen", "-mountpoint", str(mount),
                 str(image)], "Could not mount the Firecrawl Local disk image")
        copied_app = root / APP_NAME
        try:
            app = mount / APP_NAME
            verify_app(app)
            run_tool("/usr/bin/ditto", [str(app), str(copied_app)], "Could not copy Firecrawl Local")
        finally:
            run_tool("/usr/bin/hdiutil", ["detach", str(mount)], "Could not eject the Firecrawl Local disk image")
        verify_app(copied_app)
        if destination.exists() or destination.is_symlink():
            raise SetupError(f"{destination} appeared during setup. Run setup again to use the installed copy.")
        copied_app.rename(destination)


def open_app(app: Path) -> None:
    run_tool("/usr/bin/open", [str(app)], "Could not open Firecrawl Local")


def wait_for_app() -> str:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        version = local_version()
        if version is not None:
            return version
        time.sleep(0.25)
    raise SetupError("Firecrawl Local did not become ready. Check its app window, then run setup again.")


def setup(applications: Path | None = None) -> dict[str, object]:
    if not supported_mac():
        return {"ready": False, "status": "external-instance-required", "guide": "https://plugins-docs.mere.run/plugins/firecrawl-local"}

    version = local_version()
    if version is not None:
        return {"ready": True, "status": "reused", "endpoint": ENDPOINT, "version": version}

    import fcntl

    applications = applications if applications is not None else Path.home() / "Applications"
    applications.mkdir(parents=True, exist_ok=True)
    lock = os.open(applications / ".mere-firecrawl-local.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, "r+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        version = local_version()
        if version is not None:
            return {"ready": True, "status": "reused", "endpoint": ENDPOINT, "version": version}
        app = applications / APP_NAME
        if app.exists() or app.is_symlink():
            verify_app(app)
        elif SYSTEM_APP.exists() or SYSTEM_APP.is_symlink():
            app = SYSTEM_APP
            verify_app(app)
        else:
            install_app(app)
        open_app(app)
        version = wait_for_app()
        return {"ready": True, "status": "started", "endpoint": ENDPOINT, "version": version, "application": str(app)}

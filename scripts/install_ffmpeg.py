"""Install the project's verified FFmpeg build on x86_64 Linux/WSL."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# Monthly builds are retained for two years; daily builds expire after 14 days.
RELEASE = "autobuild-2026-09-30-13-08"
BUILD = "n9.0.2-17-g2a571b6068-20260930"
ARCHIVE_ROOT = "ffmpeg-n9.0.2-17-g2a571b6068-linux64-gpl-9.0"
ARCHIVE_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    f"{RELEASE}/{ARCHIVE_ROOT}.tar.xz"
)
ARCHIVE_SHA256 = "68ee646831adaae2495618346f3bba94ff207ff83bbd34d643e7004730d66269"
BINARIES = ("ffmpeg", "ffprobe")
MANIFEST = "ffmpeg-build.json"


def install_ffmpeg(
    bin_dir: Path, *, archive: Path | None = None, replace: bool = False
) -> None:
    """Validate the archive and staged binaries before installing either tool."""
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise ValueError("This build requires x86_64 Linux/WSL with glibc >= 2.28")
    bin_dir = bin_dir.expanduser().resolve()
    targets = [bin_dir / name for name in (*BINARIES, MANIFEST)]
    if not replace and any(path.exists() or path.is_symlink() for path in targets):
        raise FileExistsError("FFmpeg installation exists; use --replace to update it")
    bin_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ffmpeg-install-", dir=bin_dir) as work:
        staged = Path(work)
        if archive is None:
            archive = staged / "download.tar.xz"
            with urllib.request.urlopen(ARCHIVE_URL, timeout=60) as response:
                with archive.open("wb") as output:
                    shutil.copyfileobj(response, output)
        digest = hashlib.sha256()
        with archive.open("rb") as archive_file:
            for block in iter(lambda: archive_file.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != ARCHIVE_SHA256:
            raise ValueError("FFmpeg archive SHA-256 does not match the pinned build")
        with tarfile.open(archive, "r:xz") as package:
            for name in BINARIES:
                member = package.getmember(f"{ARCHIVE_ROOT}/bin/{name}")
                if not member.isfile():
                    raise ValueError(f"FFmpeg archive contains a non-file {name}")
                source = package.extractfile(member)
                if source is None:
                    raise ValueError(f"FFmpeg archive is missing {name}")
                with source, (staged / name).open("wb") as output:
                    shutil.copyfileobj(source, output)
                (staged / name).chmod(0o755)
        for name in BINARIES:
            result = subprocess.run(
                [str(staged / name), "-version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            if result.returncode or not result.stdout.startswith(
                f"{name} version {BUILD} "
            ):
                raise ValueError(f"Installed {name} does not match the pinned build")
        filters = subprocess.run(
            [str(staged / "ffmpeg"), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if filters.returncode or " subtitles " not in filters.stdout:
            raise ValueError("FFmpeg build is missing the subtitles filter (libass)")
        (staged / MANIFEST).write_text(
            json.dumps(
                {
                    "build": BUILD,
                    "release": RELEASE,
                    "url": ARCHIVE_URL,
                    "sha256": ARCHIVE_SHA256,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        for target in targets:
            (staged / target.name).replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument(
        "--archive", type=Path, help="Use a local, checksum-verified tar.xz"
    )
    parser.add_argument(
        "--replace", action="store_true", help="Update existing binaries"
    )
    args = parser.parse_args()
    try:
        install_ffmpeg(args.bin_dir, archive=args.archive, replace=args.replace)
    except (
        OSError,
        ValueError,
        KeyError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"FFmpeg installation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Installed FFmpeg/ffprobe {BUILD} in {args.bin_dir.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

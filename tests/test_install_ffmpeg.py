"""Hermetic checks for media-tool download integrity and safe installation."""

import hashlib
import importlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def installer(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    module = importlib.import_module("install_ffmpeg")
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        name = Path(command[0]).name
        output = (
            f"{name} version {module.BUILD} Copyright\n"
            if command[-1] == "-version"
            else " ... subtitles V->V Render text subtitles using libass.\n"
        )
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    return module


def _archive(installer: ModuleType, *, link: bool = False) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:xz") as package:
        for name in installer.BINARIES:
            member = tarfile.TarInfo(f"{installer.ARCHIVE_ROOT}/bin/{name}")
            payload = name.encode()
            if link and name == "ffprobe":
                member.type = tarfile.SYMTYPE
                member.linkname = "../../outside"
                package.addfile(member)
            else:
                member.size = len(payload)
                package.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


def _local_archive(
    tmp_path: Path, installer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> Path:
    payload = _archive(installer)
    monkeypatch.setattr(
        installer, "ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest()
    )
    path = tmp_path / "ffmpeg.tar.xz"
    path.write_bytes(payload)
    return path


def test_download_installs_verified_pair_and_provenance(
    tmp_path: Path, installer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _archive(installer)
    monkeypatch.setattr(
        installer, "ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest()
    )
    requested: list[str] = []

    def download(url: str, *, timeout: int) -> io.BytesIO:
        requested.append(url)
        return io.BytesIO(payload)

    monkeypatch.setattr(installer.urllib.request, "urlopen", download)
    bin_dir = tmp_path / "bin"
    installer.install_ffmpeg(bin_dir)
    assert requested == [installer.ARCHIVE_URL]
    for name in installer.BINARIES:
        assert (bin_dir / name).read_bytes() == name.encode()
        assert (bin_dir / name).stat().st_mode & 0o777 == 0o755
    provenance = json.loads((bin_dir / installer.MANIFEST).read_text(encoding="utf-8"))
    assert provenance == {
        "build": installer.BUILD,
        "release": installer.RELEASE,
        "url": installer.ARCHIVE_URL,
        "sha256": installer.ARCHIVE_SHA256,
    }
    assert not list(bin_dir.glob(".ffmpeg-install-*"))


def test_checksum_failure_preserves_existing_binaries(
    tmp_path: Path, installer: ModuleType
) -> None:
    archive = tmp_path / "untrusted.tar.xz"
    archive.write_bytes(b"untrusted archive")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in installer.BINARIES:
        (bin_dir / name).write_bytes(b"original")
    with pytest.raises(ValueError, match="SHA-256"):
        installer.install_ffmpeg(bin_dir, archive=archive, replace=True)
    assert {p.name for p in bin_dir.iterdir()} == set(installer.BINARIES)
    assert all(
        (bin_dir / name).read_bytes() == b"original" for name in installer.BINARIES
    )


@pytest.mark.parametrize("failed_check", ["ffprobe-version", "subtitles"])
def test_probe_failure_publishes_neither_binary(
    tmp_path: Path,
    installer: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    failed_check: str,
) -> None:
    archive = _local_archive(tmp_path, installer, monkeypatch)
    original_run = installer.subprocess.run

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if (
            failed_check == "ffprobe-version" and Path(command[0]).name == "ffprobe"
        ) or (failed_check == "subtitles" and command[-1] == "-filters"):
            return subprocess.CompletedProcess(
                command, 0, stdout="unsupported", stderr=""
            )
        return original_run(command, **kwargs)

    monkeypatch.setattr(installer.subprocess, "run", run)
    bin_dir = tmp_path / "bin"
    with pytest.raises(ValueError, match="pinned build|subtitles"):
        installer.install_ffmpeg(bin_dir, archive=archive)
    assert list(bin_dir.iterdir()) == []


def test_archive_links_are_rejected_without_publishing(
    tmp_path: Path, installer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _archive(installer, link=True)
    monkeypatch.setattr(
        installer, "ARCHIVE_SHA256", hashlib.sha256(payload).hexdigest()
    )
    archive = tmp_path / "linked.tar.xz"
    archive.write_bytes(payload)
    bin_dir = tmp_path / "bin"
    with pytest.raises(ValueError, match="non-file"):
        installer.install_ffmpeg(bin_dir, archive=archive)
    assert list(bin_dir.iterdir()) == []


def test_existing_installation_requires_explicit_replacement(
    tmp_path: Path, installer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _local_archive(tmp_path, installer, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg").write_bytes(b"old version")
    with pytest.raises(FileExistsError, match="--replace"):
        installer.install_ffmpeg(bin_dir, archive=archive)
    assert (bin_dir / "ffmpeg").read_bytes() == b"old version"
    installer.install_ffmpeg(bin_dir, archive=archive, replace=True)
    assert (bin_dir / "ffmpeg").read_bytes() == b"ffmpeg"
    assert (bin_dir / "ffprobe").read_bytes() == b"ffprobe"


def test_unsupported_platform_fails_before_creating_destination(
    tmp_path: Path, installer: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(installer.platform, "machine", lambda: "aarch64")
    bin_dir = tmp_path / "bin"
    with pytest.raises(ValueError, match="x86_64"):
        installer.install_ffmpeg(bin_dir)
    assert not bin_dir.exists()

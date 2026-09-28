"""Hermetic checks of the controlled release archive policy."""

import importlib
import io
import tarfile
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def verifier(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    return importlib.import_module("verify_release_builds")


def _archive(
    path: Path, *, mtime: int, payload: bytes = b"source", mode: int = 0o644
) -> None:
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("package/module.py")
        member.size = len(payload)
        member.mtime = mtime
        member.uid = mtime
        member.uname = str(mtime)
        member.mode = mode
        member.pax_headers = {"mtime": str(mtime), "atime": str(mtime)}
        archive.addfile(member, io.BytesIO(payload))


def test_normalization_preserves_payload_and_produces_identical_hashes(
    tmp_path: Path, verifier: ModuleType
) -> None:
    for index in (1, 2):
        raw = tmp_path / f"raw-{index}.tar.gz"
        _archive(raw, mtime=index)
        verifier._normalize_sdist(raw, tmp_path / f"dist-{index}.tar.gz", 1700000000)
    first = tmp_path / "dist-1.tar.gz"
    second = tmp_path / "dist-2.tar.gz"
    assert first.read_bytes() == second.read_bytes()
    assert verifier._sha256(first) == verifier._sha256(second)
    with tarfile.open(first) as archive:
        member = archive.getmember("package/module.py")
        assert member.mode == 0o644
        assert member.mtime == 1700000000
        assert member.uid == member.gid == 0
        stream = archive.extractfile(member)
        assert stream is not None
        assert stream.read() == b"source"


@pytest.mark.parametrize("payload,mode", [(b"changed", 0o644), (b"source", 0o755)])
def test_normalization_does_not_hide_source_or_permission_changes(
    tmp_path: Path, verifier: ModuleType, payload: bytes, mode: int
) -> None:
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    _archive(first, mtime=1)
    _archive(second, mtime=2, payload=payload, mode=mode)
    for path in (first, second):
        verifier._normalize_sdist(path, path.with_suffix(".normalized"), 1700000000)
    assert verifier._sha256(first.with_suffix(".normalized")) != verifier._sha256(
        second.with_suffix(".normalized")
    )


def test_release_check_refuses_to_overwrite_existing_work(
    tmp_path: Path, verifier: ModuleType
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    original = work / "release-builds.json"
    original.write_text("completed", encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match="empty"):
        verifier.verify_release_builds(tmp_path / "project", work)
    assert original.read_text(encoding="utf-8") == "completed"


def test_release_check_requires_work_outside_checkout(
    tmp_path: Path, verifier: ModuleType
) -> None:
    with pytest.raises(verifier.VerificationError, match="outside"):
        verifier.verify_release_builds(tmp_path, tmp_path / "work")


def test_normalization_rejects_links(tmp_path: Path, verifier: ModuleType) -> None:
    raw = tmp_path / "raw.tar.gz"
    with tarfile.open(raw, "w:gz") as archive:
        link = tarfile.TarInfo("package/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    with pytest.raises(verifier.VerificationError, match="unsupported"):
        verifier._normalize_sdist(raw, tmp_path / "normalized.tar.gz", 1700000000)

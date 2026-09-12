from hashlib import sha256
from pathlib import Path
from typing import NoReturn

import pytest

from multicuts.errors import AcquisitionError
from multicuts.local_source import LOCAL_FINGERPRINT_VERSION, acquire_local_source
from multicuts.models import AcquiredSource


def test_local_source_fingerprint_is_content_based_and_read_only(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first video.mp4"
    second = tmp_path / "second.mp4"
    content = b"small test video bytes"
    first.write_bytes(content)
    second.write_bytes(content)
    original_stat = first.stat()

    acquired_first = acquire_local_source(first)
    acquired_second = acquire_local_source(second)

    assert isinstance(acquired_first, AcquiredSource)
    assert acquired_first.local_path == first.resolve()
    assert acquired_first.fingerprint == (
        f"{LOCAL_FINGERPRINT_VERSION}:{sha256(content).hexdigest()}"
    )
    assert acquired_first.fingerprint == acquired_second.fingerprint
    assert first.read_bytes() == content
    assert first.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert first.stat().st_size == original_stat.st_size


def test_local_source_fingerprint_changes_with_content(tmp_path: Path) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"original")
    first_fingerprint = acquire_local_source(source).fingerprint
    source.write_bytes(b"changed")

    assert acquire_local_source(source).fingerprint != first_fingerprint


def test_local_source_fingerprint_covers_every_chunk(tmp_path: Path) -> None:
    source = tmp_path / "video.mp4"
    content = b"a" * (1024 * 1024) + b"b"
    source.write_bytes(content)

    assert acquire_local_source(source).fingerprint == (
        f"{LOCAL_FINGERPRINT_VERSION}:{sha256(content).hexdigest()}"
    )


def test_local_source_resolves_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"source")
    monkeypatch.chdir(tmp_path)

    assert acquire_local_source("video.mp4").local_path == source.resolve()


@pytest.mark.parametrize("source_name", ["missing.mp4", "directory"])
def test_local_source_rejects_missing_or_non_file_paths(
    tmp_path: Path, source_name: str
) -> None:
    (tmp_path / "directory").mkdir()

    with pytest.raises(AcquisitionError):
        acquire_local_source(tmp_path / source_name)


def test_local_source_wraps_unreadable_file_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "video.mp4"
    source.write_bytes(b"source")

    def deny_read(_path: Path, _mode: str) -> NoReturn:
        raise PermissionError("private path and credentials")

    monkeypatch.setattr(Path, "open", deny_read)

    with pytest.raises(AcquisitionError, match="^Cannot read local source$") as caught:
        acquire_local_source(source)
    assert isinstance(caught.value.__cause__, PermissionError)
    assert "credentials" not in str(caught.value)

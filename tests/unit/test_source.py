from pathlib import Path

import pytest

from multicuts.errors import AcquisitionError
from multicuts.models import AcquiredSource
from multicuts.source import (
    acquire_source,
    is_supported_youtube_url,
    parse_youtube_url,
    prepare_acquisition_workspace,
)


@pytest.mark.parametrize(
    "source",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://m.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123?t=20",
        "https://www.youtube.com/shorts/abc123",
        "https://www.youtube-nocookie.com/embed/abc123",
    ],
)
def test_supported_youtube_urls_are_recognized_without_network(source: str) -> None:
    reference = parse_youtube_url(source)

    assert reference is not None
    assert reference.video_id == "abc123"
    assert is_supported_youtube_url(source)


@pytest.mark.parametrize(
    "source",
    [
        "https://example.com/watch?v=abc123",
        "ftp://www.youtube.com/watch?v=abc123",
        "https://www.youtube.com/playlist?list=abc123",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?v=bad/id",
        "https://www.youtube.com:444/watch?v=abc123",
    ],
)
def test_unsupported_urls_are_not_routed_to_youtube(source: str) -> None:
    assert parse_youtube_url(source) is None
    assert not is_supported_youtube_url(source)


def test_local_source_routing_does_not_invoke_remote_provider(tmp_path: Path) -> None:
    source_path = tmp_path / "video.mp4"
    source_path.write_bytes(b"local media")

    class FailingProvider:
        def acquire(self, source: str, workspace: Path) -> AcquiredSource:
            del source, workspace
            raise AssertionError("remote provider must not run for local paths")

    acquired = acquire_source(
        str(source_path),
        tmp_path / "workspace",
        youtube_provider=FailingProvider(),
    )

    assert acquired.source_kind == "local"
    assert acquired.provider_id is None
    assert acquired.original_url is None
    assert acquired.local_path == source_path.resolve()


def test_youtube_source_routing_uses_provider_boundary(tmp_path: Path) -> None:
    calls: list[tuple[str, Path]] = []
    expected = AcquiredSource(
        tmp_path / "download.mp4",
        "youtube-sha256-v1:source",
        source_kind="youtube",
        provider_id="abc123",
        title="A title",
        original_url="https://www.youtube.com/watch?v=abc123",
    )

    class FakeProvider:
        def acquire(self, source: str, workspace: Path) -> AcquiredSource:
            calls.append((source, workspace))
            return expected

    workspace = tmp_path / "workspace"
    acquired = acquire_source(
        "https://www.youtube.com/watch?v=abc123",
        workspace,
        youtube_provider=FakeProvider(),
    )

    assert acquired == expected
    assert calls == [("https://www.youtube.com/watch?v=abc123", workspace)]


def test_unsupported_remote_source_fails_before_provider_call(tmp_path: Path) -> None:
    with pytest.raises(AcquisitionError, match="Unsupported source URL"):
        acquire_source("https://example.com/video", tmp_path)


def test_acquisition_workspace_is_explicit_and_contained(tmp_path: Path) -> None:
    workspace = prepare_acquisition_workspace(tmp_path / "output")

    assert workspace == (tmp_path / "output" / ".work" / "acquisition").resolve()
    assert workspace.is_dir()
    assert workspace.is_relative_to((tmp_path / "output").resolve())

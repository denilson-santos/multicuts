from pathlib import Path

import pytest

import multicuts.adapters.youtube as youtube_module
from multicuts.adapters.youtube import YOUTUBE_FINGERPRINT_VERSION, YoutubeAdapter
from multicuts.errors import AcquisitionError, ConfigurationError, MediaError
from multicuts.models import TimeRange


class FakeYoutubeDL:
    instances: list["FakeYoutubeDL"] = []
    payload: dict[str, object] = {}
    failure: Exception | None = None
    content = b"downloaded media"

    def __init__(self, options: dict[str, object]) -> None:
        self.options = options
        self.extract_calls: list[tuple[str, bool]] = []
        self.__class__.instances.append(self)

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> object:
        self.extract_calls.append((url, download))
        if self.failure is not None:
            raise self.failure
        output_template = str(self.options["outtmpl"])
        output = Path(output_template.replace("%(id)s.%(ext)s", "abc123.mp4"))
        info: dict[str, object] = {
            "id": "abc123",
            "title": "  A useful title\n",
            "filepath": str(output),
            "duration": 360.0,
            **self.payload,
        }
        ranges = self.options.get("download_ranges")
        if callable(ranges):
            sections = ranges(info, self)
            assert isinstance(sections, list)
            (section,) = sections
            assert isinstance(section, dict)
            if "requested_downloads" not in self.payload:
                info["requested_downloads"] = [
                    {
                        "filepath": str(output),
                        "section_start": section["start_time"],
                        "section_end": section["end_time"],
                    }
                ]
        output.write_bytes(self.content)
        return info

    def prepare_filename(self, info_dict: object) -> str:
        assert isinstance(info_dict, dict)
        return str(info_dict["filepath"])


@pytest.fixture(autouse=True)
def reset_fake_downloader(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.payload = {}
    FakeYoutubeDL.failure = None
    FakeYoutubeDL.content = b"downloaded media"
    monkeypatch.setattr(youtube_module, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(youtube_module, "check_media_tools", lambda: None)


def test_adapter_downloads_one_source_into_controlled_workspace(tmp_path: Path) -> None:
    url = "https://www.youtube.com/watch?v=abc123"

    acquired = YoutubeAdapter().acquire(url, tmp_path / "downloads")

    workspace = (tmp_path / "downloads").resolve()
    downloader = FakeYoutubeDL.instances[0]
    assert acquired.local_path.is_relative_to(workspace)
    assert acquired.local_path.is_file()
    assert acquired.source_kind == "youtube"
    assert acquired.provider_id == "abc123"
    assert acquired.provider_id == "abc123"
    assert acquired.title == "A useful title"
    assert acquired.original_url == url
    assert acquired.fingerprint.startswith(f"{YOUTUBE_FINGERPRINT_VERSION}:")
    assert downloader.extract_calls == [(url, True)]
    assert downloader.options["noplaylist"] is True
    assert downloader.options["overwrites"] is False
    assert str(workspace) in str(downloader.options["outtmpl"])
    assert "download_ranges" not in downloader.options
    assert acquired.acquired_range is None
    assert acquired.original_duration is None


def test_adapter_requests_one_exact_interval_and_preserves_original_identity(
    tmp_path: Path,
) -> None:
    interval = TimeRange(100.25, 130.5)
    acquired = YoutubeAdapter().acquire(
        "https://youtu.be/abc123", tmp_path, time_range=interval
    )
    assert acquired.acquired_range == interval
    assert acquired.original_duration == 360.0
    assert acquired.timeline_offset == 100.25
    assert acquired.provider_id == "abc123"
    assert FakeYoutubeDL.instances[0].options["force_keyframes_at_cuts"] is True


def test_partial_fingerprint_separates_ranges_even_with_identical_media(
    tmp_path: Path,
) -> None:
    adapter = YoutubeAdapter()
    url = "https://youtu.be/abc123"
    first = adapter.acquire(url, tmp_path / "first", time_range=TimeRange(10, 20))
    repeated = adapter.acquire(
        url, tmp_path / "repeated", time_range=TimeRange(10.0, 20.0)
    )
    changed = adapter.acquire(url, tmp_path / "changed", time_range=TimeRange(30, 40))
    whole = adapter.acquire(url, tmp_path / "whole")
    assert first.fingerprint == repeated.fingerprint
    assert len({first.fingerprint, changed.fingerprint, whole.fingerprint}) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"duration": None},
        {"duration": float("nan")},
        {"duration": 0},
        {"duration": True},
        {"is_live": True},
        {"live_status": "post_live"},
    ],
)
def test_partial_download_rejects_unknown_or_unstable_duration_before_media(
    payload: dict[str, object], tmp_path: Path
) -> None:
    FakeYoutubeDL.payload = payload
    with pytest.raises(AcquisitionError, match="completed video with known duration"):
        YoutubeAdapter().acquire(
            "https://youtu.be/abc123", tmp_path, time_range=TimeRange(10, 20)
        )
    assert not list(tmp_path.glob("*.mp4"))


def test_partial_download_rejects_out_of_source_bounds_before_media(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="exceeds source"):
        YoutubeAdapter().acquire(
            "https://youtu.be/abc123", tmp_path, time_range=TimeRange(10, 361)
        )
    assert not list(tmp_path.glob("*.mp4"))


@pytest.mark.parametrize(
    "downloads", [None, [], [{"section_start": 0, "section_end": 360}]]
)
def test_partial_download_rejects_missing_or_different_section_metadata(
    downloads: object, tmp_path: Path
) -> None:
    FakeYoutubeDL.payload = {"requested_downloads": downloads}
    with pytest.raises(AcquisitionError, match="interval"):
        YoutubeAdapter().acquire(
            "https://youtu.be/abc123", tmp_path, time_range=TimeRange(10, 20)
        )


def test_partial_download_checks_media_tools_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail() -> None:
        raise MediaError("ffmpeg is unavailable")

    monkeypatch.setattr(youtube_module, "check_media_tools", fail)
    with pytest.raises(MediaError, match="ffmpeg"):
        YoutubeAdapter().acquire(
            "https://youtu.be/abc123", tmp_path, time_range=TimeRange(10, 20)
        )
    assert FakeYoutubeDL.instances == []


def test_adapter_normalizes_url_metadata_to_video_identity(
    tmp_path: Path,
) -> None:
    url = "https://youtu.be/abc123?token=secret&v=abc123"

    acquired = YoutubeAdapter().acquire(url, tmp_path)

    assert acquired.original_url == "https://youtu.be/abc123"
    assert "secret" not in (acquired.original_url or "")


def test_effective_media_changes_change_fingerprint(tmp_path: Path) -> None:
    adapter = YoutubeAdapter()
    first = adapter.acquire("https://youtu.be/abc123", tmp_path / "first")
    FakeYoutubeDL.content = b"different downloaded media"
    second = adapter.acquire("https://youtu.be/abc123", tmp_path / "second")

    assert first.fingerprint != second.fingerprint


@pytest.mark.parametrize(
    "payload",
    [
        {"_type": "playlist", "entries": []},
        {"id": None},
        {"title": None},
        {"duration": "unknown"},
    ],
)
def test_adapter_rejects_playlist_or_incomplete_metadata(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    FakeYoutubeDL.payload = payload

    with pytest.raises(AcquisitionError):
        YoutubeAdapter().acquire("https://youtu.be/abc123", tmp_path)


def test_adapter_rejects_output_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    FakeYoutubeDL.payload = {"filepath": str(outside)}

    with pytest.raises(AcquisitionError, match="outside"):
        YoutubeAdapter().acquire("https://youtu.be/abc123", tmp_path / "workspace")


def test_adapter_wraps_provider_failures_without_leaking_provider_text(
    tmp_path: Path,
) -> None:
    FakeYoutubeDL.failure = RuntimeError("cookie=super-secret")

    with pytest.raises(AcquisitionError, match="YouTube download failed") as caught:
        YoutubeAdapter().acquire("https://youtu.be/abc123", tmp_path)

    assert "super-secret" not in str(caught.value)

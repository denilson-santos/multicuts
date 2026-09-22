from pathlib import Path

import pytest

import multicuts.adapters.youtube as youtube_module
from multicuts.adapters.youtube import YOUTUBE_FINGERPRINT_VERSION, YoutubeAdapter
from multicuts.errors import AcquisitionError


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
        output.write_bytes(self.content)
        return {
            "id": "abc123",
            "title": "  A useful title\n",
            "filepath": str(output),
            **self.payload,
        }

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


def test_adapter_downloads_one_source_into_controlled_workspace(tmp_path: Path) -> None:
    url = "https://www.youtube.com/watch?v=abc123"

    acquired = YoutubeAdapter().acquire(url, tmp_path / "downloads")

    workspace = (tmp_path / "downloads").resolve()
    downloader = FakeYoutubeDL.instances[0]
    assert acquired.local_path.is_relative_to(workspace)
    assert acquired.local_path.is_file()
    assert acquired.source_kind == "youtube"
    assert acquired.provider_id == "abc123"
    assert acquired.source_id == "abc123"
    assert acquired.title == "A useful title"
    assert acquired.original_url == url
    assert acquired.fingerprint.startswith(f"{YOUTUBE_FINGERPRINT_VERSION}:")
    assert downloader.extract_calls == [(url, True)]
    assert downloader.options["noplaylist"] is True
    assert downloader.options["overwrites"] is False
    assert str(workspace) in str(downloader.options["outtmpl"])


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

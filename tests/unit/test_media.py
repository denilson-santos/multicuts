import json
import subprocess
from pathlib import Path

import pytest

from multicuts.errors import MediaError
from multicuts.media import normalize_media_probe, probe_media
from multicuts.models import AcquiredSource


@pytest.fixture
def probe_payload() -> dict[str, object]:
    return {
        "format": {"duration": "12.5"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "sample_aspect_ratio": "1:1",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "channels": 2,
                "sample_rate": "48000",
            },
        ],
    }


def test_probe_normalizes_duration_streams_and_square_geometry(
    probe_payload: dict[str, object],
) -> None:
    media = normalize_media_probe(probe_payload)

    assert media.duration == 12.5
    assert (media.coded_width, media.coded_height) == (1920, 1080)
    assert (media.presentation_width, media.presentation_height) == (1920, 1080)
    assert media.video_stream_index == 0
    assert media.audio_stream_index == 1
    assert media.has_audio


@pytest.mark.parametrize(
    ("rotation_metadata", "expected_rotation"),
    [
        ({"tags": {"rotate": "90"}}, 90.0),
        ({"side_data_list": [{"rotation": -90}]}, -90.0),
    ],
)
def test_probe_applies_quarter_turn_rotation(
    probe_payload: dict[str, object],
    rotation_metadata: dict[str, object],
    expected_rotation: float,
) -> None:
    streams = probe_payload["streams"]
    assert isinstance(streams, list)
    video = streams[0]
    assert isinstance(video, dict)
    video.update(rotation_metadata)

    media = normalize_media_probe(probe_payload)

    assert media.rotation_degrees == expected_rotation
    assert (media.presentation_width, media.presentation_height) == (1080, 1920)


def test_probe_applies_sample_aspect_ratio_before_rotation() -> None:
    payload = {
        "format": {"duration": "10"},
        "streams": [
            {
                "index": 3,
                "codec_type": "video",
                "width": 720,
                "height": 576,
                "sample_aspect_ratio": "16:15",
                "side_data_list": [{"rotation": 90}],
            }
        ],
    }

    media = normalize_media_probe(payload)

    assert (media.coded_width, media.coded_height) == (720, 576)
    assert (media.presentation_width, media.presentation_height) == (576, 768)
    assert not media.has_audio


def test_probe_skips_cover_art_and_unusable_streams() -> None:
    payload = {
        "format": {"duration": "8"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "width": 500,
                "height": 500,
                "disposition": {"attached_pic": 1},
            },
            {"index": 1, "codec_type": "video", "width": 0, "height": 480},
            {"index": 2, "codec_type": "video", "width": 640, "height": 480},
            {"index": 3, "codec_type": "audio", "channels": 0, "sample_rate": "48000"},
            {"index": 4, "codec_type": "audio", "channels": 1, "sample_rate": "44100"},
        ],
    }

    media = normalize_media_probe(payload)

    assert media.video_stream_index == 2
    assert media.audio_stream_index == 4


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"format": {"duration": "N/A"}, "streams": []},
        {"format": {"duration": 10**400}, "streams": []},
        {"format": {"duration": "0"}, "streams": []},
        {"format": {"duration": "10"}, "streams": []},
        {
            "format": {"duration": "10"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "width": 640,
                    "height": 480,
                    "sample_aspect_ratio": "0:1",
                }
            ],
        },
        {
            "format": {"duration": "10"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "width": 640,
                    "height": 480,
                    "tags": {"rotate": "45"},
                }
            ],
        },
    ],
)
def test_probe_rejects_invalid_required_metadata(payload: object) -> None:
    with pytest.raises(MediaError):
        normalize_media_probe(payload)


def test_probe_command_uses_argument_vector_and_project_model(
    probe_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AcquiredSource(tmp_path / "video with spaces.mp4", "sha256-v1:abc")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(probe_payload), "")

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    media = probe_media(source)

    assert media.duration == 12.5
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[0] == "ffprobe"
    assert command[-1] == str(source.local_path)
    assert command[command.index("-of") + 1] == "json"
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False
    assert "shell" not in kwargs


def test_probe_failure_does_not_expose_unbounded_provider_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = AcquiredSource(tmp_path / "secret.mp4", "sha256-v1:abc")

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "private metadata" * 1000)

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(MediaError, match="ffprobe failed") as caught:
        probe_media(source)
    assert "private metadata" not in str(caught.value)
    assert "secret.mp4" not in str(caught.value)
    assert len(str(caught.value)) < 100


def test_probe_wraps_missing_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = AcquiredSource(tmp_path / "video.mp4", "sha256-v1:abc")

    def fake_run(
        _command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(MediaError, match="Could not run ffprobe") as caught:
        probe_media(source)
    assert isinstance(caught.value.__cause__, FileNotFoundError)


def test_probe_rejects_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = AcquiredSource(tmp_path / "video.mp4", "sha256-v1:abc")

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "not-json", "")

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(MediaError, match="invalid JSON"):
        probe_media(source)

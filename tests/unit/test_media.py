import json
import subprocess
from pathlib import Path

import pytest

from multicuts.errors import MediaError
from multicuts.media import (
    check_media_tools,
    inspect_media_path,
    normalize_media_probe,
    probe_media,
    validate_media_for_transcription,
)
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
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, json.dumps(probe_payload), "")

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    media = probe_media(source)

    assert media.duration == 12.5
    assert len(calls) == 3
    assert [command for command, _ in calls[:2]] == [
        ["ffmpeg", "-version"],
        ["ffprobe", "-version"],
    ]
    for _, version_kwargs in calls[:2]:
        assert version_kwargs["timeout"] == 5
        assert version_kwargs["check"] is True
        assert "shell" not in version_kwargs
    command, kwargs = calls[2]
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
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "private metadata" * 1000)

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(
        MediaError, match="Could not inspect media with ffprobe"
    ) as caught:
        probe_media(source)
    assert "private metadata" not in str(caught.value)
    assert "secret.mp4" not in str(caught.value)
    assert len(str(caught.value)) < 100


@pytest.mark.parametrize("missing_tool", ["ffmpeg", "ffprobe"])
def test_preflight_rejects_missing_binary_before_probe(
    missing_tool: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = AcquiredSource(tmp_path / "video.mp4", "sha256-v1:abc")
    calls: list[list[str]] = []

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[0] == missing_tool:
            raise FileNotFoundError(missing_tool)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(MediaError, match=f"{missing_tool} is unavailable") as caught:
        probe_media(source)
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert all("-version" in command for command in calls)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (subprocess.CalledProcessError(7, ["ffmpeg", "-version"]), "exit code 7"),
        (subprocess.TimeoutExpired(["ffmpeg", "-version"], 5), "timed out"),
        (PermissionError("private executable path"), "Could not run ffmpeg"),
    ],
)
def test_preflight_wraps_version_failures_without_sensitive_details(
    failure: Exception,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        _command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        raise failure

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(MediaError, match=message) as caught:
        check_media_tools()
    assert caught.value.__cause__ is failure
    assert "private executable path" not in str(caught.value)


def test_preflight_rejects_missing_audio_after_probe(
    probe_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = probe_payload["streams"]
    assert isinstance(streams, list)
    probe_payload["streams"] = streams[:1]
    source = AcquiredSource(tmp_path / "silent.mp4", "sha256-v1:abc")

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, json.dumps(probe_payload), "")

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(MediaError, match="No usable audio stream"):
        probe_media(source)

    media = normalize_media_probe(probe_payload)
    assert not media.has_audio
    with pytest.raises(MediaError, match="No usable audio stream"):
        validate_media_for_transcription(media)


def test_rendered_media_inspection_allows_video_without_audio(
    probe_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streams = probe_payload["streams"]
    assert isinstance(streams, list)
    streams.pop()

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, json.dumps(probe_payload), "")

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    media = inspect_media_path(tmp_path / "raw.mp4")
    assert not media.has_audio
    assert media.presentation_width == 1920


def test_probe_preserves_process_failure_cause_without_exposing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = AcquiredSource(tmp_path / "private-video.mp4", "sha256-v1:abc")
    failure = PermissionError("private executable path")

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        raise failure

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(MediaError, match="Could not inspect media") as caught:
        probe_media(source)
    assert caught.value.__cause__ is failure
    assert "private" not in str(caught.value)


def test_probe_rejects_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = AcquiredSource(tmp_path / "video.mp4", "sha256-v1:abc")

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "not-json", "")

    monkeypatch.setattr("multicuts.media.subprocess.run", fake_run)

    with pytest.raises(MediaError, match="invalid JSON"):
        probe_media(source)

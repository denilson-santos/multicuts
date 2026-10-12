import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.errors import MediaError
from multicuts.media import (
    check_media_tools,
    inspect_media_path,
    normalize_media_probe,
    prepare_source_range,
    probe_media,
    validate_media_for_transcription,
)
from multicuts.models import AcquiredSource, TimeRange


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


@pytest.mark.parametrize("value", ["invalid", "nan", True])
def test_probe_rejects_invalid_media_start_time(
    value: object, probe_payload: dict[str, object]
) -> None:
    probe_payload["format"] = {"duration": "12.5", "start_time": value}
    with pytest.raises(MediaError, match="start time"):
        normalize_media_probe(probe_payload)


@pytest.mark.parametrize(("preskip", "delay"), [("3801", 0.0065), ("e001", 0.01)])
def test_probe_normalizes_opus_header_delay(
    preskip: str, delay: float, probe_payload: dict[str, object]
) -> None:
    streams = probe_payload["streams"]
    assert isinstance(streams, list)
    streams[1].update(
        {
            "codec_name": "opus",
            "extradata": (
                f"\n00000000: 4f70 7573 4865 6164 0102 {preskip} 80bb 0000"
                "  OpusHead........\n"
            ),
        }
    )
    assert normalize_media_probe(probe_payload).audio_codec_delay == delay


@pytest.mark.parametrize("header", [None, "invalid", "00000000: ffff 0000  ...."])
def test_probe_rejects_missing_or_malformed_opus_header(
    header: object, probe_payload: dict[str, object]
) -> None:
    streams = probe_payload["streams"]
    assert isinstance(streams, list)
    streams[1].update({"codec_name": "opus", "extradata": header})
    with pytest.raises(MediaError, match="Opus codec delay"):
        normalize_media_probe(probe_payload)


def test_prepare_source_range_preserves_source_and_maps_probed_streams(
    probe_payload: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "source video.mp4"
    original.write_bytes(b"original")
    source = AcquiredSource(original, "source")
    media = replace(
        normalize_media_probe(probe_payload), video_stream_index=3, audio_stream_index=5
    )
    commands: list[list[str]] = []
    probe_payload["format"] = {"duration": "2.5"}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "shell" not in kwargs
        commands.append(command)
        if command[0] == "ffmpeg" and "-version" not in command:
            Path(command[-1]).write_bytes(b"partial media")
        payload = dict(probe_payload)
        payload["format"] = {
            "duration": "2.5",
            "start_time": "6.25"
            if len([c for c in commands if c[0] == "ffprobe" and "-version" not in c])
            == 1
            else "0",
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr("multicuts.media.subprocess.run", run)
    prepared, prepared_media = prepare_source_range(
        source, media, TimeRange(6.25, 8.75), tmp_path / "work"
    )
    extracted = prepared.local_path
    assert prepared.timeline_offset == 6.25
    # Do not reuse ASR caches prepared with unconditional codec-delay correction.
    assert (
        prepared.fingerprint
        != "sha256-v1:bf7be041ddfbab543d66e1549d22c95c3eff44f6308cba16f11d3a6c7c004ce5"
    )
    assert prepared_media.duration == 2.5
    assert extracted.is_relative_to(tmp_path / "work")
    assert extracted.read_bytes() == b"partial media"
    assert original.read_bytes() == b"original"
    copies = [c for c in commands if c[0] == "ffmpeg" and "-version" not in c]
    assert len(copies) == 2
    command = copies[0]
    assert command[command.index("-ss") + 1] == "6.250000"
    assert command[command.index("-t") + 1] == "2.500000"
    assert command[command.index("-i") + 1] == str(original)
    assert [command[i + 1] for i, value in enumerate(command) if value == "-map"] == [
        "0:3",
        "0:5",
    ]
    for copy in copies:
        assert copy[copy.index("-c") + 1] == "copy"
        assert "-copyts" in copy and "-start_at_zero" in copy
        assert not {"-vf", "-crf", "-r", "-maxrate", "-ar", "-ac"}.intersection(copy)


@pytest.mark.parametrize(
    "failure",
    ["encode", "coverage", "audio", "probe", "os", "timeline", "geometry", "remux"],
)
def test_failed_source_range_is_removed_and_diagnostics_are_safe(
    failure: str,
    probe_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = normalize_media_probe(probe_payload)
    probe_payload["format"] = {"duration": "2.5"}
    if failure == "audio":
        streams = probe_payload["streams"]
        assert isinstance(streams, list)
        probe_payload["streams"] = [streams[0]]

    probes = 0
    copies = 0

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal probes, copies
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "ffmpeg":
            copies += 1
            Path(command[-1]).write_bytes(b"incomplete")
            if failure == "os":
                raise OSError("private source metadata")
            return subprocess.CompletedProcess(
                command,
                int(failure == "encode" or (failure == "remux" and copies == 2)),
                "",
                "private source metadata",
            )
        probes += 1
        probe_payload["format"] = {
            "duration": "2.5",
            "start_time": ("9" if failure == "coverage" else "6.25")
            if probes == 1
            else ("1" if failure == "timeline" else "0"),
        }
        if failure == "geometry" and probes == 2:
            streams = probe_payload["streams"]
            assert isinstance(streams, list)
            streams[0]["width"] = 1280
        payload = "invalid" if failure == "probe" else json.dumps(probe_payload)
        return subprocess.CompletedProcess(command, 0, payload, "")

    monkeypatch.setattr("multicuts.media.subprocess.run", run)
    work = tmp_path / "work"
    with pytest.raises(MediaError) as caught:
        prepare_source_range(
            AcquiredSource(tmp_path / "source.mp4", "source"),
            media,
            TimeRange(6.25, 8.75),
            work,
        )
    assert "private source metadata" not in str(caught.value)
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("has_audio", [False, True])
def test_invalid_transcription_range_fails_before_ffmpeg(
    has_audio: bool,
    probe_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = normalize_media_probe(probe_payload)
    if not has_audio:
        media = replace(media, audio_stream_index=None)

    def unexpected_run(*args: object, **kwargs: object) -> None:
        pytest.fail("Invalid interval/audio must fail before media processing")

    monkeypatch.setattr("multicuts.media.subprocess.run", unexpected_run)
    with pytest.raises(MediaError):
        prepare_source_range(
            AcquiredSource(tmp_path / "source.mp4", "source"),
            media,
            TimeRange(6, 14),
            tmp_path / "work",
        )


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


@pytest.mark.parametrize("libavformat_major", [58, 59, 60, 61, 62, 63])
@pytest.mark.parametrize("source_kind", ["local", "youtube"])
def test_opus_remux_compensation_matches_installed_matroska_muxer(
    libavformat_major: int,
    source_kind: str,
    probe_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "source.webm"
    original.write_bytes(b"original")
    streams = probe_payload["streams"]
    assert isinstance(streams, list)
    streams[1].update(
        {
            "codec_name": "opus",
            "extradata": (
                "00000000: 4f70 7573 4865 6164 0102 3801 80bb 0000  OpusHead........"
            ),
        }
    )
    youtube = source_kind == "youtube"
    media = replace(
        normalize_media_probe(probe_payload), start_time=6.25 if youtube else 0
    )
    source = AcquiredSource(
        original,
        "source",
        source_kind=source_kind,
        provider_id="abc123" if youtube else None,
        title="Fixture source" if youtube else None,
        original_url="https://youtu.be/abc123" if youtube else None,
        acquired_range=TimeRange(6.25, 8.75) if youtube else None,
        original_duration=12.5 if youtube else None,
    )
    copies: list[list[str]] = []
    probes = 0

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal probes
        if "-version" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                "ffmpeg version N-snapshot\n"
                f"libavformat    {libavformat_major}.  1.100 / "
                f"{libavformat_major}.  1.100",
                "",
            )
        if command[0] == "ffmpeg":
            copies.append(command)
            Path(command[-1]).write_bytes(b"copied media")
            return subprocess.CompletedProcess(command, 0, "", "")
        probes += 1
        payload = dict(probe_payload)
        payload["format"] = {
            "duration": "2.5",
            "start_time": "6.25" if probes == 1 and not youtube else "0",
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr("multicuts.media.subprocess.run", run)
    prepared, _ = prepare_source_range(
        source, media, TimeRange(6.25, 8.75), tmp_path / "work"
    )
    assert prepared.acquired_range == TimeRange(6.25, 8.75)
    assert len(copies) == (1 if youtube else 2)
    for command in copies:
        assert command[command.index("-c") + 1] == "copy"
        if libavformat_major < 60:
            expected_delay = "0.014000000" if youtube else "0.006500000"
            assert command[command.index("-bsf:a") + 1] == (
                f"setts=pts=PTS+{expected_delay}/TB:dts=DTS+{expected_delay}/TB"
            )
        else:
            assert "-bsf:a" not in command


@pytest.mark.parametrize("failure", ["unknown", "exit", "missing", "timeout"])
def test_opus_remux_rejects_unavailable_muxer_version_without_publishing_media(
    failure: str,
    probe_payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "source.webm"
    original.write_bytes(b"original")
    media = replace(normalize_media_probe(probe_payload), audio_codec_delay=0.0065)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if kwargs.get("check") is True:
            return subprocess.CompletedProcess(command, 0, "", "")
        if failure == "missing":
            raise FileNotFoundError("private-token")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 5, output="private-token")
        return subprocess.CompletedProcess(
            command, 1 if failure == "exit" else 0, "private-token", ""
        )

    monkeypatch.setattr("multicuts.media.subprocess.run", run)
    with pytest.raises(MediaError, match="FFmpeg libavformat version") as caught:
        prepare_source_range(
            AcquiredSource(original, "source"),
            media,
            TimeRange(6.25, 8.75),
            tmp_path / "work",
        )
    assert "private-token" not in str(caught.value)
    assert not list((tmp_path / "work").iterdir())
    assert original.read_bytes() == b"original"

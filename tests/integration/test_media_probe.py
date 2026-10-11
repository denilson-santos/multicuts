import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from multicuts.errors import MediaError
from multicuts.media import extract_transcription_range, inspect_media_path, probe_media
from multicuts.models import AcquiredSource, TimeRange


@pytest.mark.integration
@pytest.mark.parametrize(
    "interval", [TimeRange(2.125, 10.625), TimeRange(2.125, 2.175)]
)
def test_transcription_proxy_is_compact_and_preserves_requested_audio(
    interval: TimeRange,
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required")
    source_path = tmp_path / "compressed-source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=1280x720:r=30:d=12",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=12",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "36",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-shortest",
            str(source_path),
        ],
        check=True,
        capture_output=True,
    )
    before = sha256(source_path.read_bytes()).hexdigest()
    source = AcquiredSource(source_path, "fixture")
    media = inspect_media_path(source_path)
    temporary = extract_transcription_range(source, media, interval, tmp_path / "work")
    actual = inspect_media_path(temporary)
    duration = interval.end - interval.start
    assert actual.duration == pytest.approx(duration, abs=0.25)
    assert (actual.presentation_width, actual.presentation_height) == (1280, 720)
    assert temporary.stat().st_size < source_path.stat().st_size / 2
    assert sha256(source_path.read_bytes()).hexdigest() == before

    # Compare decoded samples with the requested source audio, independently
    # prepared for ASR. Lossless proxy encoding must not change these samples.
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    reference = subprocess.run(
        base
        + [
            "-ss",
            f"{interval.start:.6f}",
            "-i",
            str(source_path),
            "-t",
            f"{duration:.6f}",
            "-map",
            "0:a:0",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
    decoded = subprocess.run(
        base
        + [
            "-i",
            str(temporary),
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert decoded == reference
    assert len(decoded) == round(duration * 16000) * 2


@pytest.mark.integration
def test_probe_media_with_real_ffprobe(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required")

    video_path = tmp_path / "tiny.avi"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x24:r=1:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "1",
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )

    media = probe_media(AcquiredSource(video_path, "integration-fixture"))

    assert media.duration == pytest.approx(1.0, abs=0.1)
    assert (media.coded_width, media.coded_height) == (32, 24)
    assert (media.presentation_width, media.presentation_height) == (32, 24)
    assert media.has_audio


@pytest.mark.integration
def test_preflight_rejects_real_video_without_audio(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required")

    video_path = tmp_path / "silent.avi"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x24:r=1:d=1",
            "-t",
            "1",
            "-c:v",
            "mpeg4",
            "-an",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )

    with pytest.raises(MediaError, match="No usable audio stream"):
        probe_media(AcquiredSource(video_path, "integration-fixture"))

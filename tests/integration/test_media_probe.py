import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from multicuts.errors import MediaError
from multicuts.media import inspect_media_path, prepare_source_range, probe_media
from multicuts.models import AcquiredSource, TimeRange


@pytest.mark.integration
@pytest.mark.parametrize(
    ("container", "interval", "rotation"),
    [
        ("mp4", TimeRange(6.25, 8.75), 0),
        ("mp4", TimeRange(2.125, 2.175), 0),
        ("mov", TimeRange(6.25, 8.75), 90),
        ("webm", TimeRange(6.25, 8.75), 0),
        ("webm", TimeRange(0, 1), 0),
        ("webm", TimeRange(11.5, 12), 0),
    ],
)
def test_range_source_preserves_frames_audio_and_original(
    container: str,
    interval: TimeRange,
    rotation: int,
    tmp_path: Path,
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required")
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    source_path = tmp_path / f"source.{container}"
    encoded = tmp_path / f"encoded.{container}" if rotation else source_path
    subprocess.run(
        base
        + [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=25:d=12",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=12",
            "-c:v",
            "libvpx-vp9" if container == "webm" else "libx264",
            "-g",
            "100",
            "-c:a",
            "libopus" if container == "webm" else "aac",
            "-ac",
            "2",
            "-shortest",
            str(encoded),
        ],
        check=True,
        capture_output=True,
    )
    if rotation:
        subprocess.run(
            base
            + [
                "-i",
                str(encoded),
                "-c",
                "copy",
                "-metadata:s:v:0",
                f"rotate={rotation}",
                str(source_path),
            ],
            check=True,
            capture_output=True,
        )
    before = sha256(source_path.read_bytes()).hexdigest()
    source = AcquiredSource(source_path, "fixture")
    original_media = inspect_media_path(source_path)
    prepared, media = prepare_source_range(
        source,
        original_media,
        interval,
        tmp_path / "work",
    )
    assert prepared.acquired_range is not None
    assert prepared.acquired_range.start <= interval.start
    assert prepared.acquired_range.end >= interval.end
    assert prepared.original_duration == original_media.duration
    assert media.presentation_width == original_media.presentation_width
    assert media.presentation_height == original_media.presentation_height
    assert media.rotation_degrees == original_media.rotation_degrees
    assert prepared.local_path.stat().st_size < source_path.stat().st_size
    assert sha256(source_path.read_bytes()).hexdigest() == before

    decoded_video: list[list[str]] = []
    decoded_audio: list[bytes] = []
    for path, start_time in (
        (source_path, interval.start),
        (prepared.local_path, interval.start - prepared.timeline_offset),
    ):
        seek = base + [
            "-ss",
            f"{start_time:.6f}",
            "-i",
            str(path),
            "-t",
            f"{interval.end - interval.start:.6f}",
        ]
        frames = subprocess.run(
            seek + ["-map", "0:v:0", "-f", "framemd5", "pipe:1"],
            check=True,
            capture_output=True,
        ).stdout.decode()
        decoded_video.append(
            [
                line.split(",")[-1].strip()
                for line in frames.splitlines()
                if not line.startswith("#")
            ]
        )
        decoded_audio.append(
            subprocess.run(
                seek + ["-map", "0:a:0", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"],
                check=True,
                capture_output=True,
            ).stdout
        )
    assert decoded_video[0] and decoded_video[0] == decoded_video[1]
    assert sha256(decoded_audio[0]).digest() == sha256(decoded_audio[1]).digest()


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

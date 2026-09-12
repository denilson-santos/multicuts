import shutil
import subprocess
from pathlib import Path

import pytest

from multicuts.errors import MediaError
from multicuts.media import probe_media
from multicuts.models import AcquiredSource


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

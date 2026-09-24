"""Opt-in real FFmpeg and multisubs timed-cue rendering contract."""

import shutil
import subprocess
from pathlib import Path

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.models import ClipTranscript, ClipTranscriptSegment, ClipTranscriptWord


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and ffprobe are required",
)
def test_timed_cue_template_renders_final_clip_geometry(tmp_path: Path) -> None:
    raw = tmp_path / "raw.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=360x640:d=2:r=25",
            "-c:v",
            "mpeg4",
            "-y",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )
    clip = ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=2.0,
        source_start=4.0,
        source_end=6.0,
        source_duration=10.0,
        text="Olá mundo.",
        segments=(ClipTranscriptSegment("Olá mundo.", 0.2, 1.8, 0),),
        words=(
            ClipTranscriptWord("Olá", 0.2, 0.7, None, 0, 0),
            ClipTranscriptWord("mundo.", 0.8, 1.8, None, 1, 0),
        ),
        provider="multisubs",
        provider_version="4.3.0",
        word_timing_complete=True,
    )

    result = MultisubsAdapter().subtitle_clip(
        raw,
        clip,
        template="amber-word",
        template_dir=None,
        workspace=tmp_path / "subtitles",
    )

    ass = result.ass_path.read_text(encoding="utf-8")
    assert "PlayResX: 360" in ass
    assert "PlayResY: 640" in ass
    assert "Olá mundo." in result.srt_path.read_text(encoding="utf-8")
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(result.video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "360,640"

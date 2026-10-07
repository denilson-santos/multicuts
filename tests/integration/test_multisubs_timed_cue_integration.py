"""Opt-in real FFmpeg and multisubs timed-cue rendering contract."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.models import ClipTranscript, ClipTranscriptSegment, ClipTranscriptWord


@pytest.mark.integration
@pytest.mark.parametrize(
    "intervals",
    [
        ((0.2, 0.7), (0.8, 1.2), (1.3, 1.8)),
        ((0.2, 0.2), (0.8, 1.2), (1.3, 1.8)),
        ((0.2, 0.7), (0.8, 0.8), (1.3, 1.8)),
        ((0.2, 0.7), (0.8, 1.2), (1.8, 1.8)),
        ((0.7, 0.7), (0.7, 0.7), (0.7, 0.7)),
    ],
    ids=["positive", "leading-point", "interior-point", "trailing-point", "all-points"],
)
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and ffprobe are required",
)
def test_timed_cue_template_renders_final_clip_geometry(
    tmp_path: Path, intervals: tuple[tuple[float, float], ...]
) -> None:
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
        text="Olá de novo.",
        segments=(ClipTranscriptSegment("Olá de novo.", 0.2, 1.8, 0),),
        words=tuple(
            ClipTranscriptWord(token, start, end, None, index, 0)
            for index, (token, (start, end)) in enumerate(
                zip(("Olá", "de", "novo."), intervals, strict=True)
            )
        ),
        provider="multisubs",
        provider_version="4.4.0",
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
    assert "Olá de novo." in result.srt_path.read_text(encoding="utf-8")
    cues = json.loads(result.cues_json_path.read_text(encoding="utf-8"))["cues"]
    assert all(word["end"] > word["start"] for cue in cues for word in cue["words"])
    assert [(word.start, word.end) for word in clip.words] == list(intervals)
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

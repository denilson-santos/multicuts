"""Real FFmpeg contract for the active semantic render path."""

import shutil
import subprocess
from pathlib import Path

import pytest

from multicuts.app_config import AppConfig
from multicuts.clips import JudgedClip, Proposal
from multicuts.media import inspect_media_path
from multicuts.models import AcquiredSource, Transcript, TranscriptSegment
from multicuts.render import render_final, render_raw

pytestmark = pytest.mark.integration


def test_short_clip_is_cropped_and_published_without_subtitles(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    source_path = tmp_path / "source.mp4"
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
            "color=c=blue:s=640x360:r=25:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=3",
            "-t",
            "3",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-c:a",
            "aac",
            str(source_path),
        ],
        check=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:integration")
    media = inspect_media_path(source_path)
    proposal = Proposal(
        "clip-id",
        "short",
        "u0",
        "u1",
        0.5,
        2.5,
        "A complete idea.",
        "Title",
        "Rationale",
    )
    clip = JudgedClip(proposal, {}, 80.0, True, "Good")
    config = AppConfig(
        source=str(source_path),
        output_dir=tmp_path / "output",
        llm_backend="codex",
        llm_model="test",
        subtitles_enabled=False,
        vertical_width=360,
        vertical_height=640,
    )
    raw, raw_media, ratio = render_raw(
        source,
        media,
        clip,
        config,
        output=tmp_path / "work" / "raw.mp4",
        work=tmp_path / "work",
    )
    assert ratio == "9:16"
    assert (raw_media.presentation_width, raw_media.presentation_height) == (360, 640)
    assert raw_media.has_audio
    final_path = tmp_path / "clips" / "clip.mp4"
    transcript = Transcript(
        None,
        "en",
        3.0,
        "A complete idea.",
        (TranscriptSegment("A complete idea.", 0.5, 2.5),),
        (),
        "multisubs",
        "4.3.0",
    )
    final, sidecars, template = render_final(
        raw,
        raw_media,
        transcript,
        clip,
        config,
        output=final_path,
        work=tmp_path / "work",
    )
    assert final == final_path and final.is_file()
    assert sidecars == () and template is None
    assert inspect_media_path(final).presentation_width == 360

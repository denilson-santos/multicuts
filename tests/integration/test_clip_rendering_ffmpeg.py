from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from multicuts.candidates.refinement import REFINE_VERSION
from multicuts.media import inspect_media_path
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    RefinedSelection,
    RefinementReason,
    RenderRequest,
    ScoredCandidate,
    SelectedCandidate,
)
from multicuts.rendering.cutter import FfmpegRenderer
from multicuts.scoring.heuristic import score_heuristically

pytestmark = pytest.mark.integration


def _tools_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _refined(
    duration: float, *, start: float = 0.5, end: float = 1.8
) -> RefinedSelection:
    candidate = Candidate(
        "integration-candidate", start, end, "A complete thought.", (0,), "1"
    )
    evaluation = CandidateEvaluation(
        candidate=candidate,
        features=CandidateFeatures(
            duration=end - start,
            word_count=3,
            timed_word_count=3,
        ),
        checklist=(ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        shortlist_rank=1,
    )
    selected = SelectedCandidate(
        evaluation,
        ScoredCandidate(candidate.candidate_id, score_heuristically(evaluation)),
        1,
    )
    return RefinedSelection(
        selected=selected,
        render_start=start,
        render_end=end,
        pre_roll=0.0,
        post_roll=0.0,
        reasons=(RefinementReason.UNCHANGED,),
        version=REFINE_VERSION,
        source_duration=duration,
        requires_rescore=False,
    )


def _request(
    source_path: Path, output_root: Path, *, aspect_ratio: str
) -> RenderRequest:
    source = AcquiredSource(source_path, "sha256-v1:integration")
    media = inspect_media_path(source_path)
    refined = _refined(media.duration)
    return RenderRequest(
        source=source,
        media=media,
        refined=refined,
        aspect_ratio=aspect_ratio,
        target_width=1080,
        target_height=1920,
        temporary_path=output_root
        / "private"
        / f"{aspect_ratio.replace(':', '-')}.mp4",
        output_path=output_root / "published" / f"{aspect_ratio.replace(':', '-')}.mp4",
        renderer_version="integration",
        cache_key=f"sha256-v1:{aspect_ratio}",
    )


def test_render_original_preserves_geometry_and_audio(tmp_path: Path) -> None:
    if not _tools_available():
        pytest.skip("FFmpeg and ffprobe are required")
    source_path = Path("src/multicuts/data/test-horizontal.mp4")
    request = _request(source_path, tmp_path, aspect_ratio="original")

    result = FfmpegRenderer().render(request)
    inspected = inspect_media_path(result.path)

    assert result.path.is_file()
    assert (result.width, result.height) == (
        request.media.presentation_width,
        request.media.presentation_height,
    )
    assert (inspected.presentation_width, inspected.presentation_height) == (
        1920,
        1080,
    )
    assert inspected.has_audio
    assert inspected.duration == pytest.approx(1.3, abs=0.25)


def test_render_vertical_outputs_configured_center_cropped_geometry(
    tmp_path: Path,
) -> None:
    if not _tools_available():
        pytest.skip("FFmpeg and ffprobe are required")
    source_path = Path("src/multicuts/data/test-horizontal.mp4")
    request = _request(source_path, tmp_path, aspect_ratio="9:16")

    result = FfmpegRenderer().render(request)
    inspected = inspect_media_path(result.path)

    assert (result.width, result.height) == (1080, 1920)
    assert (inspected.presentation_width, inspected.presentation_height) == (
        1080,
        1920,
    )
    assert inspected.has_audio
    assert inspected.duration == pytest.approx(1.3, abs=0.25)


def test_render_video_only_source_keeps_supported_missing_audio(tmp_path: Path) -> None:
    if not _tools_available():
        pytest.skip("FFmpeg and ffprobe are required")
    source_path = tmp_path / "video-only.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=24",
            "-t",
            "2",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source_path),
        ],
        check=True,
    )
    request = _request(source_path, tmp_path / "render", aspect_ratio="original")

    result = FfmpegRenderer().render(request)
    inspected = inspect_media_path(result.path)

    assert result.width == 320
    assert result.height == 180
    assert not result.has_audio
    assert not inspected.has_audio


def test_render_original_uses_rotated_presentation_geometry(tmp_path: Path) -> None:
    if not _tools_available():
        pytest.skip("FFmpeg and ffprobe are required")
    source_path = tmp_path / "rotated.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            "src/multicuts/data/test-horizontal.mp4",
            "-c",
            "copy",
            "-metadata:s:v:0",
            "rotate=90",
            str(source_path),
        ],
        check=True,
    )
    request = _request(source_path, tmp_path / "render", aspect_ratio="original")
    assert (request.media.presentation_width, request.media.presentation_height) == (
        1080,
        1920,
    )

    result = FfmpegRenderer().render(request)
    inspected = inspect_media_path(result.path)

    assert (result.width, result.height) == (1080, 1920)
    assert (inspected.presentation_width, inspected.presentation_height) == (
        1080,
        1920,
    )
    assert inspected.rotation_degrees == 0

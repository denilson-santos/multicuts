from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from multicuts.candidates.refinement import REFINE_VERSION
from multicuts.config import RunConfig
from multicuts.errors import ArtifactError
from multicuts.media import inspect_media_path
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationBatch,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    ClipTranscript,
    ClipTranscriptSegment,
    ClipTranscriptWord,
    RefinedSelection,
    RefinementReason,
    RenderedClip,
    RenderRequest,
    ScoredCandidate,
    SelectedCandidate,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import run_pipeline
from multicuts.rendering.cutter import FfmpegRenderer
from multicuts.rendering.subtitles import SubtitledClip, SubtitleRenderer
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


@pytest.mark.parametrize(
    "aspect_ratio,expected_geometry",
    [("original", (480, 270)), ("9:16", (360, 640))],
)
def test_subtitle_rendering_preserves_final_geometry_and_burns_visible_text(
    tmp_path: Path, aspect_ratio: str, expected_geometry: tuple[int, int]
) -> None:
    if not _tools_available():
        pytest.skip("FFmpeg and ffprobe are required")
    source_path = tmp_path / "black-source.mp4"
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
            "color=c=black:s=480x270:d=2.5:r=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(source_path),
        ],
        check=True,
        capture_output=True,
    )
    request = _request(source_path, tmp_path / "raw", aspect_ratio=aspect_ratio)
    if aspect_ratio == "9:16":
        request = RenderRequest(
            source=request.source,
            media=request.media,
            refined=request.refined,
            aspect_ratio=request.aspect_ratio,
            target_width=360,
            target_height=640,
            temporary_path=request.temporary_path,
            output_path=request.output_path,
            renderer_version=request.renderer_version,
            cache_key=request.cache_key,
        )
    raw = FfmpegRenderer().render(request)
    clip = ClipTranscript(
        language_requested=None,
        language_detected="en",
        duration=request.refined.render_end - request.refined.render_start,
        source_start=request.refined.render_start,
        source_end=request.refined.render_end,
        source_duration=request.media.duration,
        text="Visible subtitle.",
        segments=(ClipTranscriptSegment("Visible subtitle.", 0.1, 1.2, 0),),
        words=(
            ClipTranscriptWord("Visible", 0.1, 0.55, None, 0, 0),
            ClipTranscriptWord("subtitle.", 0.6, 1.2, None, 1, 0),
        ),
        provider="multisubs",
        provider_version="4.3.0",
        word_timing_complete=True,
    )

    final = SubtitleRenderer().render(
        raw,
        clip,
        output_path=tmp_path / "final" / f"{aspect_ratio.replace(':', '-')}.mp4",
        workspace=tmp_path / "private" / aspect_ratio.replace(":", "-"),
        template="amber-word",
        template_dir=None,
    )

    media = inspect_media_path(final.path)
    assert (media.presentation_width, media.presentation_height) == expected_geometry
    assert media.has_audio
    assert media.duration == pytest.approx(1.3, abs=0.25)
    assert raw.path.is_file()
    assert final.subtitles.srt_path.is_file()
    assert final.subtitles.ass_path.is_file()
    frame = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            "0.7",
            "-i",
            str(final.path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert len(frame) == expected_geometry[0] * expected_geometry[1] * 3
    assert sum(component > 80 for component in frame) > 100


@pytest.mark.parametrize("subtitles_enabled", [True, False])
def test_pipeline_publishes_final_clips_and_recovers_unfinished_run(
    tmp_path: Path, subtitles_enabled: bool
) -> None:
    if not _tools_available():
        pytest.skip("FFmpeg and ffprobe are required")
    source_path = tmp_path / "pipeline-source.mp4"
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
            "color=c=black:s=480x270:d=8:r=25",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(source_path),
        ],
        check=True,
        capture_output=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:pipeline-subtitle")
    transcript = Transcript(
        language_requested="pt",
        language_detected="pt",
        duration=8.0,
        text="Olá mundo.",
        segments=(TranscriptSegment("Olá mundo.", 0.2, 3.4),),
        words=(Word("Olá", 0.4, 0.8), Word("mundo.", 1.0, 1.5)),
        provider="multisubs",
        provider_version="4.3.0",
    )
    candidate = Candidate("pipeline-candidate", 0.0, 3.8, "Olá mundo.", (0,), "1")
    evaluation = CandidateEvaluation(
        candidate,
        CandidateFeatures(duration=3.8, word_count=2, timed_word_count=2),
        (ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        1,
    )
    batch = CandidateEvaluationBatch((evaluation,), (evaluation,))

    class FakeTranscriber:
        def __init__(self) -> None:
            self.calls = 0

        def version(self) -> str:
            return "4.3.0"

        def transcribe(
            self,
            video_path: Path,
            *,
            language: str | None,
            model: str,
            workspace: Path,
        ) -> Transcript:
            del video_path, language, model, workspace
            self.calls += 1
            return transcript

    class CountingSubtitleRenderer(SubtitleRenderer):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def render(
            self,
            raw: RenderedClip,
            clip: ClipTranscript,
            *,
            output_path: Path,
            workspace: Path,
            template: str | None,
            template_dir: Path | None,
        ) -> SubtitledClip:
            self.calls += 1
            return super().render(
                raw,
                clip,
                output_path=output_path,
                workspace=workspace,
                template=template,
                template_dir=template_dir,
            )

    transcriber = FakeTranscriber()
    subtitle_renderer = CountingSubtitleRenderer()
    config = RunConfig(
        source=str(source_path),
        output_dir=tmp_path / "output",
        clips=1,
        min_score=0,
        aspect_ratio="original",
        subtitle_template="amber-word",
        scorer="heuristic",
        model="default",
        language="pt",
        min_duration=2.0,
        max_duration=4.0,
        refinement_pre_roll=0.0,
        refinement_post_roll=0.0,
        subtitles_enabled=subtitles_enabled,
    )

    def run() -> tuple[Path, ...]:
        return run_pipeline(
            config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _source: inspect_media_path(source.local_path),
            transcriber=transcriber,
            candidate_generator=lambda *_args, **_kwargs: (candidate,),
            candidate_evaluator=lambda *_args, **_kwargs: batch,
            subtitle_renderer=subtitle_renderer,
        )

    outputs = run()

    assert len(outputs) == 1
    assert outputs[0].is_file()
    assert transcriber.calls == 1
    assert subtitle_renderer.calls == (1 if subtitles_enabled else 0)
    final_media = inspect_media_path(outputs[0])
    assert (final_media.presentation_width, final_media.presentation_height) == (
        480,
        270,
    )
    subtitles = list((tmp_path / "output").rglob("*.srt"))
    if subtitles_enabled:
        assert len(subtitles) == 1
        assert "Olá mundo." in subtitles[0].read_text(encoding="utf-8")
    else:
        assert subtitles == []

    manifest = next((tmp_path / "output").rglob("manifest.json"))
    assert manifest.is_file()
    assert outputs[0].with_suffix(".json").is_file()
    with pytest.raises(ArtifactError, match="Completed output already exists"):
        run()

    # A retry before final publication can reuse the stage media and transcript.
    manifest.unlink()
    outputs[0].with_suffix(".json").unlink()
    assert run() == outputs
    assert transcriber.calls == 1
    assert subtitle_renderer.calls == (1 if subtitles_enabled else 0)

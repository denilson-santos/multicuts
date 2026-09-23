from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from multicuts.candidates.refinement import REFINE_VERSION
from multicuts.errors import RenderingError
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    MediaInfo,
    RefinedSelection,
    RefinementReason,
    RenderRequest,
    ScoredCandidate,
    SelectedCandidate,
)
from multicuts.rendering.cutter import (
    FfmpegRenderer,
    build_ffmpeg_command,
    expected_geometry,
    validate_rendered_media,
)
from multicuts.scoring.heuristic import score_heuristically


def _refined(
    *, start: float = 2.25, end: float = 5.75, duration: float = 20.0
) -> RefinedSelection:
    candidate = Candidate("candidate-1", start, end, "A complete thought.", (0,), "1")
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
    tmp_path: Path,
    *,
    aspect_ratio: str = "original",
    media: MediaInfo | None = None,
    refined: RefinedSelection | None = None,
) -> RenderRequest:
    media = media or MediaInfo(20.0, 1921, 1081, 1921, 1081, 0, 1)
    refined = refined or _refined(duration=media.duration)
    return RenderRequest(
        source=AcquiredSource(tmp_path / "source.mp4", "sha256-v1:source"),
        media=media,
        refined=refined,
        aspect_ratio=aspect_ratio,
        target_width=1080,
        target_height=1920,
        temporary_path=tmp_path / "private" / "clip.mp4",
        output_path=tmp_path / "published" / "clip.mp4",
        renderer_version="ffmpeg version test",
        cache_key="sha256-v1:render",
    )


def test_original_command_uses_accurate_trim_explicit_streams_and_normalized_geometry(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)

    command = build_ffmpeg_command(request)

    assert command[0] == "ffmpeg"
    assert "-ss" in command
    assert command[command.index("-ss") + 1] == "2.250000"
    assert command[command.index("-t") + 1] == "3.500000"
    assert command[command.index("-map") + 1] == "0:0"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "0:1"
    video_filter = command[command.index("-vf") + 1]
    assert video_filter == "scale=1920:1080:flags=lanczos,setsar=1"
    assert command[-1] == str(request.temporary_path)
    assert all(not isinstance(argument, Path) for argument in command)


def test_vertical_command_center_crops_from_presentation_geometry(
    tmp_path: Path,
) -> None:
    media = MediaInfo(20.0, 1921, 1081, 1921, 1081, 0, 1)
    request = _request(tmp_path, aspect_ratio="9:16", media=media)

    command = build_ffmpeg_command(request)
    video_filter = command[command.index("-vf") + 1]

    assert expected_geometry(request) == (1080, 1920)
    assert "scale=1920:1080:flags=lanczos,setsar=1" in video_filter
    assert "crop=606:1080" in video_filter
    assert "scale=1080:1920:flags=lanczos,setsar=1" in video_filter


def test_video_only_command_explicitly_disables_audio(tmp_path: Path) -> None:
    media = MediaInfo(20.0, 640, 360, 640, 360, 0, None)
    request = _request(tmp_path, media=media)

    command = build_ffmpeg_command(request)

    assert "-an" in command
    assert command.count("-map") == 1


def test_render_request_rejects_invalid_mode_dimensions_and_shared_paths(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="aspect ratio"):
        _request(tmp_path, aspect_ratio="4:3")
    with pytest.raises(ValueError, match="positive even"):
        RenderRequest(
            source=AcquiredSource(tmp_path / "source.mp4", "sha256-v1:source"),
            media=MediaInfo(20.0, 640, 360, 640, 360, 0, None),
            refined=_refined(duration=20.0),
            aspect_ratio="original",
            target_width=1079,
            target_height=1920,
            temporary_path=tmp_path / "clip.mp4",
            output_path=tmp_path / "clip.mp4",
            renderer_version="v1",
            cache_key="key",
        )


def test_validate_rendered_media_checks_geometry_duration_and_audio(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    valid = MediaInfo(3.62, 1920, 1080, 1920, 1080, 0, 1)
    validate_rendered_media(request, valid)

    with pytest.raises(RenderingError, match="geometry"):
        validate_rendered_media(request, MediaInfo(3.5, 640, 360, 640, 360, 0, 1))
    with pytest.raises(RenderingError, match="duration"):
        validate_rendered_media(request, MediaInfo(1.0, 1920, 1080, 1920, 1080, 0, 1))
    with pytest.raises(RenderingError, match="audio"):
        validate_rendered_media(
            request, MediaInfo(3.5, 1920, 1080, 1920, 1080, 0, None)
        )


def test_renderer_publishes_validated_result_and_cleans_private_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request.source.local_path.write_bytes(b"source")
    media = MediaInfo(3.5, 1920, 1080, 1920, 1080, 0, 1)
    calls: list[list[str]] = []

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        request.temporary_path.parent.mkdir(parents=True, exist_ok=True)
        request.temporary_path.write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0, "", "")

    renderer = FfmpegRenderer()
    monkeypatch.setattr("multicuts.rendering.cutter.subprocess.run", fake_run)
    monkeypatch.setattr(renderer, "inspect", lambda _path: media)

    result = renderer.render(request)

    assert result.path == request.output_path
    assert result.width == 1920
    assert result.height == 1080
    assert result.has_audio
    assert request.output_path.read_bytes() == b"rendered"
    assert not request.temporary_path.exists()
    assert calls and calls[0][0] == "ffmpeg"


def test_renderer_failure_is_bounded_and_leaves_no_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(tmp_path)
    request.source.local_path.write_bytes(b"source")
    diagnostic = "secret=" + ("x" * 5000)

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        request.temporary_path.parent.mkdir(parents=True, exist_ok=True)
        request.temporary_path.write_bytes(b"partial")
        return subprocess.CompletedProcess(command, 7, "", diagnostic)

    monkeypatch.setattr("multicuts.rendering.cutter.subprocess.run", fake_run)

    with pytest.raises(RenderingError) as caught:
        FfmpegRenderer().render(request)

    message = str(caught.value)
    assert len(message) < 2200
    assert "secret=<redacted>" in message
    assert "x" * 100 not in message
    assert not request.output_path.exists()
    assert not request.temporary_path.exists()


def test_renderer_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request.output_path.parent.mkdir(parents=True)
    request.output_path.write_bytes(b"existing")

    with pytest.raises(RenderingError, match="already exists"):
        FfmpegRenderer().render(request)

    assert request.output_path.read_bytes() == b"existing"

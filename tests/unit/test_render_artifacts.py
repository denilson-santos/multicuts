"""Raw-render cache behavior without invoking FFmpeg."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.artifacts import prepare_workspace
from multicuts.candidates.refinement import REFINE_VERSION
from multicuts.errors import ArtifactError
from multicuts.models import (
    SCORE_DIMENSIONS,
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    MediaInfo,
    RefinedSelection,
    RefinementReason,
    RenderedClip,
    RenderRequest,
    ScoredCandidate,
    ScoreDimension,
    ScoreResult,
    SelectedCandidate,
)
from multicuts.rendering.artifacts import (
    InvalidRenderArtifactError,
    read_render,
    render_cache_key,
    render_paths,
    write_render,
)


def _refined() -> RefinedSelection:
    candidate = Candidate("candidate-v1:one", 1.0, 3.0, "A useful point.", (0,), "1")
    evaluation = CandidateEvaluation(
        candidate,
        CandidateFeatures(duration=2.0, word_count=3, timed_word_count=3),
        (ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        1,
    )
    score = ScoreResult(
        50.0,
        50.0,
        0.8,
        tuple(ScoreDimension(name, 50.0) for name in SCORE_DIMENSIONS),
        (),
        "Clear candidate",
        1,
        "1",
        "heuristic",
    )
    return RefinedSelection(
        SelectedCandidate(
            evaluation, ScoredCandidate(candidate.candidate_id, score), 1
        ),
        0.85,
        3.25,
        0.15,
        0.25,
        (RefinementReason.PADDED,),
        REFINE_VERSION,
        5.0,
        False,
    )


def _setup(tmp_path: Path) -> tuple[RenderRequest, Path, MediaInfo]:
    source = AcquiredSource(tmp_path / "source.mp4", "sha256-v1:source")
    media = MediaInfo(5.0, 1920, 1080, 1920, 1080, 0, 1)
    refined = _refined()
    paths = prepare_workspace(
        tmp_path / "output", source, cache_key="sha256-v1:transcript"
    )
    key = render_cache_key(
        refined,
        media,
        source_fingerprint=source.fingerprint,
        aspect_ratio="original",
        target_width=1080,
        target_height=1920,
        renderer_version="ffmpeg test",
    )
    output_path, metadata_path = render_paths(paths, refined, key)
    request = RenderRequest(
        source,
        media,
        refined,
        "original",
        1080,
        1920,
        paths.work / "temporary.mp4",
        output_path,
        "ffmpeg test",
        key,
    )
    return request, metadata_path, media


def test_render_cache_identity_depends_on_render_inputs_only(tmp_path: Path) -> None:
    request, _, media = _setup(tmp_path)
    refined = request.refined
    base = request.cache_key
    changed_score = replace(
        refined,
        selected=replace(refined.selected, rank=2),
    )

    def key(
        item: RefinedSelection,
        *,
        aspect_ratio: str = "original",
        renderer_version: str = "ffmpeg test",
    ) -> str:
        return render_cache_key(
            item,
            media,
            source_fingerprint=request.source.fingerprint,
            aspect_ratio=aspect_ratio,
            target_width=1080,
            target_height=1920,
            renderer_version=renderer_version,
        )

    assert key(changed_score) == base
    assert key(replace(refined, render_end=3.3, post_roll=0.3)) != base
    assert key(refined, aspect_ratio="9:16") != base
    assert key(refined, renderer_version="ffmpeg changed") != base


def test_render_artifact_reuses_only_probed_valid_media(tmp_path: Path) -> None:
    request, metadata_path, media = _setup(tmp_path)
    paths = prepare_workspace(
        tmp_path / "output", request.source, cache_key="sha256-v1:transcript"
    )
    request.output_path.write_bytes(b"opaque video bytes")
    result = RenderedClip(
        request.refined,
        request.output_path,
        1920,
        1080,
        2.4,
        True,
        request.renderer_version,
        request.cache_key,
    )
    write_render(paths, request, result, metadata_path)
    inspected: list[Path] = []

    def inspect(path: Path) -> MediaInfo:
        inspected.append(path)
        return replace(media, duration=2.4)

    assert read_render(request, metadata_path, inspect=inspect) == result
    assert inspected == [request.output_path]

    with pytest.raises(InvalidRenderArtifactError, match="validation"):
        read_render(
            request,
            metadata_path,
            inspect=lambda _path: replace(media, duration=3.0),
        )


def test_render_artifact_rejects_tampered_metadata_and_missing_media(
    tmp_path: Path,
) -> None:
    request, metadata_path, media = _setup(tmp_path)
    paths = prepare_workspace(
        tmp_path / "output", request.source, cache_key="sha256-v1:transcript"
    )
    request.output_path.write_bytes(b"opaque video bytes")
    result = RenderedClip(
        request.refined,
        request.output_path,
        1920,
        1080,
        2.4,
        True,
        request.renderer_version,
        request.cache_key,
    )
    write_render(paths, request, result, metadata_path)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["duration"] = float("inf")
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidRenderArtifactError, match="geometry"):
        read_render(request, metadata_path, inspect=lambda _path: media)
    payload["duration"] = 2.4
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")
    request.output_path.unlink()
    with pytest.raises(InvalidRenderArtifactError, match="missing"):
        read_render(request, metadata_path, inspect=lambda _path: media)
    with pytest.raises(ArtifactError, match="Completed output"):
        paths.manifest.write_text("{}", encoding="utf-8")
        write_render(paths, request, result, metadata_path)


class FakeRenderer:
    def __init__(self) -> None:
        self.rendered: list[RenderRequest] = []
        self.inspected: list[Path] = []

    def version(self) -> str:
        return "ffmpeg test"

    def inspect(self, path: Path) -> MediaInfo:
        self.inspected.append(path)
        return MediaInfo(2.4, 1920, 1080, 1920, 1080, 0, 1)

    def render(self, request: RenderRequest) -> RenderedClip:
        self.rendered.append(request)
        request.output_path.write_bytes(b"fake media")
        return RenderedClip(
            request.refined,
            request.output_path,
            1920,
            1080,
            2.4,
            True,
            request.renderer_version,
            request.cache_key,
        )


def test_pipeline_render_stage_reuses_clip_and_respects_safe_selection(
    tmp_path: Path,
) -> None:
    from multicuts.config import RunConfig
    from multicuts.pipeline import load_or_render_selection

    request, _, media = _setup(tmp_path)
    config = RunConfig(
        source="source.mp4",
        output_dir=tmp_path / "output",
        clips=3,
        min_score=0,
        aspect_ratio="original",
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
    )
    from multicuts.models import Transcript, TranscriptSegment, Word

    transcript = Transcript(
        None,
        "en",
        5.0,
        "A useful point.",
        (TranscriptSegment("A useful point.", 1.0, 3.0),),
        (Word("A", 1.0, 1.2), Word("useful", 1.3, 2.0), Word("point.", 2.1, 3.0)),
        "multisubs",
        "4.2.0",
    )
    renderer = FakeRenderer()
    first = load_or_render_selection(
        config, request.source, media, transcript, (request.refined,), renderer=renderer
    )
    second = load_or_render_selection(
        config, request.source, media, transcript, (request.refined,), renderer=renderer
    )
    assert first == second
    assert len(renderer.rendered) == 1
    assert renderer.inspected == [first[0].path]

    unsafe = replace(
        request.refined,
        reasons=(RefinementReason.PADDED, RefinementReason.REQUIRES_RESCORE),
        requires_rescore=True,
    )
    assert (
        load_or_render_selection(
            config, request.source, media, transcript, (unsafe,), renderer=renderer
        )
        == ()
    )
    assert len(renderer.rendered) == 1

    with pytest.raises(ArtifactError, match="refusing to overwrite"):
        load_or_render_selection(
            replace(config, force_recompute=True),
            request.source,
            media,
            transcript,
            (request.refined,),
            renderer=renderer,
        )

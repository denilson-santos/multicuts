"""Hermetic acceptance of the complete local and normalized YouTube flow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from itertools import combinations
from pathlib import Path

import pytest

from multicuts.adapters.multisubs_subtitles import SubtitleArtifacts
from multicuts.candidates.filters import evaluate_candidates
from multicuts.config import RunConfig
from multicuts.errors import ArtifactError, RenderingError
from multicuts.final_artifacts import (
    ClipOutcome,
    RunOutcome,
    read_clip_metadata_payload,
    read_manifest_payload,
)
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationBatch,
    ClipTranscript,
    MediaInfo,
    RenderedClip,
    RenderRequest,
    ScoreResult,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import RunResult, run_pipeline
from multicuts.rendering.subtitles import SubtitledClip
from multicuts.scoring.heuristic import score_heuristically
from multicuts.source import acquire_source

_YOUTUBE_URL = "https://www.youtube.com/watch?v=abc123ABC_-&token=private"
_YOUTUBE_REFERENCE = "https://www.youtube.com/watch?v=abc123ABC_-"


def _source_transcript() -> Transcript:
    parts = (
        ("The first lesson explains why careful planning works.", 0.0, 8.0),
        ("A clear example shows how practice builds confidence.", 8.0, 16.0),
        ("Another story shows when teams choose better questions.", 18.0, 26.0),
        ("The final point explains why small steps matter.", 26.0, 34.0),
    )
    segments = tuple(TranscriptSegment(text, start, end) for text, start, end in parts)
    words = tuple(
        Word(token, start + index * 0.9, start + index * 0.9 + 0.4, 0.9)
        for text, start, _end in parts
        for index, token in enumerate(text.split())
    )
    return Transcript(
        None,
        "en",
        36.0,
        " ".join(text for text, _start, _end in parts),
        segments,
        words,
        "multisubs",
        "4.3.0",
    )


class _Transcriber:
    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.transcript = _source_transcript()

    def version(self) -> str:
        return self.transcript.provider_version

    def transcribe(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
    ) -> Transcript:
        del model, workspace
        self.calls.append(video_path)
        return replace(self.transcript, language_requested=language)


class _Renderer:
    def __init__(self, fail_rank: int | None = None) -> None:
        self.fail_rank = fail_rank
        self.calls: list[RenderRequest] = []

    def version(self) -> str:
        return "ffmpeg fixture"

    def inspect(self, path: Path) -> MediaInfo:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return MediaInfo(
            payload["duration"],
            payload["width"],
            payload["height"],
            payload["width"],
            payload["height"],
            0,
            1,
        )

    def render(self, request: RenderRequest) -> RenderedClip:
        self.calls.append(request)
        if request.refined.rank == self.fail_rank:
            request.temporary_path.write_bytes(b"incomplete private render")
            raise RenderingError("fixture render failed")
        width, height = (
            (request.target_width, request.target_height)
            if request.aspect_ratio == "9:16"
            else (request.media.presentation_width, request.media.presentation_height)
        )
        duration = request.refined.render_end - request.refined.render_start
        request.output_path.write_text(
            json.dumps(
                {
                    "duration": duration,
                    "width": width,
                    "height": height,
                    "subtitles": False,
                }
            ),
            encoding="utf-8",
        )
        return RenderedClip(
            request.refined,
            request.output_path,
            width,
            height,
            duration,
            True,
            request.renderer_version,
            request.cache_key,
        )


class _Subtitles:
    def __init__(self, renderer: _Renderer) -> None:
        self.renderer = renderer
        self.calls: list[ClipTranscript] = []

    def version(self) -> str:
        return "4.3.0"

    def inspect(self, path: Path) -> MediaInfo:
        return self.renderer.inspect(path)

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
        del template_dir
        self.calls.append(clip)
        workspace.mkdir(parents=True)
        cues = workspace / "clip.cues.json"
        srt = workspace / "clip.srt"
        ass = workspace / "clip.ass"
        cues.write_text("{}", encoding="utf-8")
        srt.write_text(clip.text, encoding="utf-8")
        ass.write_text("[Script Info]", encoding="utf-8")
        output_path.write_text(
            json.dumps(
                {
                    "duration": raw.duration,
                    "width": raw.width,
                    "height": raw.height,
                    "subtitles": True,
                }
            ),
            encoding="utf-8",
        )
        artifacts = SubtitleArtifacts(
            cues,
            srt,
            ass,
            output_path,
            self.version(),
            template,
            template or "default",
        )
        return SubtitledClip(
            raw, output_path, raw.width, raw.height, raw.duration, True, artifacts
        )


class _YoutubeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def acquire(self, source: str, workspace: Path) -> AcquiredSource:
        self.calls.append((source, workspace))
        downloaded = workspace / "download.mp4"
        downloaded.write_bytes(b"controlled video")
        return AcquiredSource(
            downloaded,
            "youtube-sha256-v1:fixture",
            source_kind="youtube",
            provider_id="abc123ABC_-",
            title="Controlled source",
            original_url=source,
        )


@dataclass
class _Harness:
    config: RunConfig
    transcriber: _Transcriber
    renderer: _Renderer
    subtitles: _Subtitles
    youtube: _YoutubeProvider
    score_calls: list[str]
    evaluation_calls: list[tuple[Candidate, ...]] = field(default_factory=list)

    def run(self, config: RunConfig | None = None) -> RunResult:
        def evaluate(
            candidates: tuple[Candidate, ...],
            transcript: Transcript,
            *,
            min_duration: float,
            max_duration: float,
            candidate_budget: int,
        ) -> CandidateEvaluationBatch:
            self.evaluation_calls.append(candidates)
            return evaluate_candidates(
                candidates,
                transcript,
                min_duration=min_duration,
                max_duration=max_duration,
                candidate_budget=candidate_budget,
            )

        def score(evaluation: CandidateEvaluation) -> ScoreResult:
            self.score_calls.append(evaluation.candidate.candidate_id)
            return score_heuristically(evaluation)

        def probe(source: AcquiredSource) -> MediaInfo:
            assert source.local_path.is_file()
            return MediaInfo(36.0, 640, 360, 640, 360, 0, 1)

        return run_pipeline(
            self.config if config is None else config,
            acquire=lambda source, workspace: acquire_source(
                source, workspace, youtube_provider=self.youtube
            ),
            probe=probe,
            transcriber=self.transcriber,
            candidate_evaluator=evaluate,
            heuristic_scorer=score,
            renderer=self.renderer,
            subtitle_renderer=self.subtitles,
        )


def _harness(
    tmp_path: Path,
    *,
    source_kind: str = "local",
    aspect_ratio: str = "original",
    subtitles_enabled: bool = True,
    fail_rank: int | None = None,
) -> _Harness:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"controlled video")
    config = RunConfig(
        source=str(source) if source_kind == "local" else _YOUTUBE_URL,
        output_dir=tmp_path / "output",
        clips=3,
        min_score=0,
        aspect_ratio=aspect_ratio,
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
        subtitles_enabled=subtitles_enabled,
        min_duration=15.0,
        max_duration=19.0,
        refinement_pre_roll=0.0,
        refinement_post_roll=0.0,
        vertical_width=720,
        vertical_height=1280,
    )
    renderer = _Renderer(fail_rank)
    return _Harness(
        config,
        _Transcriber(),
        renderer,
        _Subtitles(renderer),
        _YoutubeProvider(),
        [],
    )


@pytest.mark.parametrize("source_kind", ["local", "youtube"])
@pytest.mark.parametrize(
    ("aspect_ratio", "subtitles_enabled"),
    [
        ("original", True),
        ("original", False),
        ("9:16", True),
        ("9:16", False),
    ],
)
def test_complete_run_has_valid_artifacts_and_one_source_transcription(
    tmp_path: Path,
    source_kind: str,
    aspect_ratio: str,
    subtitles_enabled: bool,
) -> None:
    harness = _harness(
        tmp_path,
        source_kind=source_kind,
        aspect_ratio=aspect_ratio,
        subtitles_enabled=subtitles_enabled,
    )
    result = harness.run()
    manifest_payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest = read_manifest_payload(manifest_payload)

    assert result.outcome is RunOutcome.COMPLETED
    assert manifest.run_id == result.run_id
    assert manifest.outcome is RunOutcome.COMPLETED
    assert len(result.clip_paths) >= 2
    assert len(harness.transcriber.calls) == 1
    assert len(harness.renderer.calls) == len(result.clip_paths)
    assert len(harness.score_calls) == manifest.scoring.count
    assert len(harness.subtitles.calls) == (
        len(result.clip_paths) if subtitles_enabled else 0
    )
    assert manifest.selection.count == len(result.clip_paths)
    assert manifest.source.kind == source_kind
    assert len(harness.youtube.calls) == (1 if source_kind == "youtube" else 0)
    if source_kind == "youtube":
        assert manifest.source.reference == _YOUTUBE_REFERENCE
        assert "private" not in result.manifest_path.read_text(encoding="utf-8")
        assert harness.transcriber.calls[0].is_relative_to(harness.youtube.calls[0][1])
    else:
        assert manifest.source.reference.startswith("local:sha256-v1:")
        assert str(tmp_path) not in manifest.source.reference

    geometry = (720, 1280) if aspect_ratio == "9:16" else (640, 360)
    clip_records = []
    for reference in manifest.clips:
        assert reference.status is ClipOutcome.COMPLETED
        assert reference.metadata_path is not None
        assert reference.output_path is not None
        video = result.manifest_path.parent / reference.output_path
        metadata = result.manifest_path.parent / reference.metadata_path
        assert video in result.clip_paths
        assert video.is_file() and metadata.is_file()
        clip = read_clip_metadata_payload(
            json.loads(metadata.read_text(encoding="utf-8"))
        )
        clip_records.append(clip)
        assert clip.id == reference.id
        assert clip.output_path == reference.output_path
        assert 15.0 <= clip.duration <= 19.0
        assert 15.0 <= clip.source_end - clip.source_start <= 19.0
        assert clip.score.scorer == "heuristic"
        assert 0.0 <= clip.score.score <= 100.0
        assert 0.0 <= clip.confidence <= 1.0
        assert len(clip.dimension_scores) == 7
        assert clip.checklist
        assert clip.penalties
        assert clip.reason
        assert (clip.render_config.width, clip.render_config.height) == geometry
        assert clip.render_config.subtitles_enabled is subtitles_enabled
        assert (
            json.loads(video.read_text(encoding="utf-8"))["subtitles"]
            is subtitles_enabled
        )
        if subtitles_enabled:
            assert clip.render_config.template_requested == "yellow-pop"
            assert clip.render_config.template_resolved == "yellow-pop"
            assert clip.render_config.multisubs_version == "4.3.0"
        else:
            assert clip.render_config.template_requested is None
            assert clip.render_config.template_resolved is None

    for first, second in combinations(clip_records, 2):
        intersection = max(
            0.0,
            min(first.source_end, second.source_end)
            - max(first.source_start, second.source_start),
        )
        shorter = min(
            first.source_end - first.source_start,
            second.source_end - second.source_start,
        )
        assert intersection / shorter <= harness.config.overlap_threshold

    for clip in harness.subtitles.calls:
        assert clip.words
        assert all(
            word.start is not None
            and word.end is not None
            and 0.0 <= word.start < word.end <= clip.duration
            for word in clip.words
        )


def test_compatible_rerun_and_template_change_reuse_asr_and_scoring(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    first = harness.run()
    initial_scores = len(harness.score_calls)
    initial_subtitles = len(harness.subtitles.calls)
    assert initial_scores > 0
    assert initial_subtitles == len(first.clip_paths)

    first.manifest_path.unlink()
    for video in first.clip_paths:
        video.with_suffix(".json").unlink()
    second = harness.run()
    assert second.clip_paths == first.clip_paths
    assert len(harness.transcriber.calls) == 1
    assert len(harness.score_calls) == initial_scores
    assert len(harness.renderer.calls) == len(first.clip_paths)
    assert len(harness.subtitles.calls) == initial_subtitles

    second.manifest_path.unlink()
    changed = replace(harness.config, subtitle_template="other-template")
    third = harness.run(changed)
    assert len(third.clip_paths) == len(first.clip_paths)
    assert set(third.clip_paths).isdisjoint(first.clip_paths)
    assert len(harness.transcriber.calls) == 1
    assert len(harness.score_calls) == initial_scores
    assert len(harness.renderer.calls) == len(first.clip_paths)
    assert len(harness.subtitles.calls) == initial_subtitles + len(first.clip_paths)
    manifest = read_manifest_payload(
        json.loads(third.manifest_path.read_text(encoding="utf-8"))
    )
    assert manifest.config.subtitle_template == "other-template"
    for video in third.clip_paths:
        clip = read_clip_metadata_payload(
            json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
        )
        assert clip.render_config.template_resolved == "other-template"


def test_failed_render_has_no_completed_output_or_misleading_manifest(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, subtitles_enabled=False, fail_rank=2)
    result = harness.run()
    manifest = read_manifest_payload(
        json.loads(result.manifest_path.read_text(encoding="utf-8"))
    )

    assert result.outcome is RunOutcome.PARTIAL
    assert len(result.clip_paths) == 2
    assert len(harness.transcriber.calls) == 1
    failed = tuple(item for item in manifest.clips if item.status is ClipOutcome.FAILED)
    assert len(failed) == 1
    assert failed[0].rank == 2
    assert failed[0].output_path is None
    assert failed[0].metadata_path is None
    assert failed[0].warning == "raw_render_failed"
    assert tuple((result.manifest_path.parent / "clips").glob("*.mp4")) != ()
    assert len(tuple((result.manifest_path.parent / "clips").glob("*.mp4"))) == 2
    assert len(tuple((result.manifest_path.parent / "clips").glob("*.json"))) == 2


def _interrupt_run(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch, *, before_render: bool = False
) -> Path:
    import multicuts.pipeline as pipeline

    def interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(
            pipeline,
            "load_or_render_selection" if before_render else "publish_run_manifest",
            interrupt,
        )
        with pytest.raises(KeyboardInterrupt):
            harness.run()
    root = next(harness.config.output_dir.glob("source-*"))
    assert not (root / "manifest.json").exists()
    return root


def _file_bytes(root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _call_counts(harness: _Harness) -> tuple[int, ...]:
    return (
        len(harness.transcriber.calls),
        len(harness.evaluation_calls),
        len(harness.score_calls),
        len(harness.renderer.calls),
        len(harness.subtitles.calls),
    )


def test_resume_before_manifest_reuses_all_checkpoints_without_rewriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch)
    before = _file_bytes(root)
    calls = _call_counts(harness)

    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert len(result.clip_paths) == 3
    assert _call_counts(harness) == calls
    assert all(path.read_bytes() == content for path, content in before.items())
    assert result.manifest_path.is_file()


def test_resume_after_one_clip_preserves_completed_clip_and_finishes_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import multicuts.pipeline as pipeline

    harness = _harness(tmp_path)
    publish = pipeline.publish_clip_metadata

    def interrupt_after_clip(*args, **kwargs) -> None:
        publish(*args, **kwargs)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "publish_clip_metadata", interrupt_after_clip)
        with pytest.raises(KeyboardInterrupt):
            harness.run()
    video = next(harness.config.output_dir.glob("source-*/clips/*.mp4"))
    before = (video.read_bytes(), video.with_suffix(".json").read_bytes())
    scores = len(harness.score_calls)
    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert video in result.clip_paths
    assert before == (video.read_bytes(), video.with_suffix(".json").read_bytes())
    assert _call_counts(harness) == (1, 1, scores, 3, 3)


_STAGE_FILES = (
    "transcript/transcript.json",
    "candidates/candidates.json",
    "scoring/scores.json",
    "selection/selection.json",
    "refinement/refinement.json",
)


@pytest.mark.parametrize("artifact", _STAGE_FILES)
@pytest.mark.parametrize("damage", ["missing", "malformed", "stale"])
def test_invalid_derived_checkpoint_recomputes_only_affected_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: str, damage: str
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch)
    target = root / artifact
    original = target.read_bytes()
    clips = _file_bytes(root / "clips")
    scores = len(harness.score_calls)
    if damage == "missing":
        target.unlink()
    elif damage == "malformed":
        target.write_bytes(b"{unfinished")
    else:
        payload = json.loads(original)
        payload["cache_key"] = "sha256-v1:stale"
        target.write_text(json.dumps(payload), encoding="utf-8")

    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert target.read_bytes() == original
    assert _file_bytes(root / "clips") == clips
    assert _call_counts(harness) == (
        2 if artifact.startswith("transcript/") else 1,
        2 if artifact.startswith("candidates/") else 1,
        scores * (2 if artifact.startswith("scoring/") else 1),
        3,
        3,
    )


@pytest.mark.parametrize(
    "artifact",
    (
        *_STAGE_FILES,
        "raw_media",
        "raw_metadata",
        "final_media",
        "final_metadata",
        "clip_metadata",
    ),
)
@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_unreadable_checkpoint_stops_without_expensive_recomputation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
    error_type: type[OSError],
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch)
    video = sorted((root / "clips").glob("*.mp4"))[0]
    raw = harness.renderer.calls[0].output_path
    target = {
        "raw_media": raw,
        "raw_metadata": root / "rendering" / f"{raw.stem}.json",
        "final_media": video,
        "final_metadata": root / "rendering/subtitles" / f"{video.stem}.json",
        "clip_metadata": video.with_suffix(".json"),
    }.get(artifact, root / artifact)
    before = _file_bytes(root)
    calls = _call_counts(harness)
    original_open = Path.open

    def deny_read(path: Path, *args, **kwargs):
        if path == target:
            raise error_type("injected cache read failure")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", deny_read)
        with pytest.raises(ArtifactError, match="Could not") as failure:
            harness.run()
        assert isinstance(failure.value.__cause__, error_type)

    assert _call_counts(harness) == calls
    assert _file_bytes(root) == before


@pytest.mark.parametrize(
    "artifact",
    ["raw_media", "raw_metadata", "final_media", "final_metadata", "subtitle_srt"],
)
def test_incomplete_media_checkpoint_is_preserved_and_requires_explicit_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: str
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch)
    video = sorted((root / "clips").glob("*.mp4"))[0]
    raw = harness.renderer.calls[0].output_path
    target = {
        "raw_media": raw,
        "raw_metadata": root / "rendering" / f"{raw.stem}.json",
        "final_media": video,
        "final_metadata": root / "rendering/subtitles" / f"{video.stem}.json",
        "subtitle_srt": root / "rendering/subtitles" / f"{video.stem}.srt",
    }[artifact]
    target.unlink()
    remaining = _file_bytes(root)
    calls = _call_counts(harness)

    with pytest.raises(ArtifactError, match="retry|output directory"):
        harness.run()

    assert _call_counts(harness) == calls
    assert _file_bytes(root) == remaining


@pytest.mark.parametrize("force", [False, True])
def test_completed_manifest_blocks_rerun_and_force_before_provider_calls(
    tmp_path: Path, force: bool
) -> None:
    harness = _harness(tmp_path)
    result = harness.run()
    before = _file_bytes(result.manifest_path.parent)
    calls = _call_counts(harness)

    with pytest.raises(ArtifactError, match="Completed output already exists"):
        harness.run(replace(harness.config, force_recompute=force))

    assert _call_counts(harness) == calls
    assert _file_bytes(result.manifest_path.parent) == before


def test_regenerated_transcript_invalidates_evaluation_and_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch, before_render=True)
    old_evaluation = json.loads((root / _STAGE_FILES[1]).read_text(encoding="utf-8"))
    old_scores = (root / _STAGE_FILES[2]).read_bytes()
    (root / _STAGE_FILES[0]).write_bytes(b"{interrupted")
    original = harness.transcriber.transcript
    harness.transcriber.transcript = replace(
        original,
        words=tuple(replace(word, confidence=0.5) for word in original.words),
    )
    score_calls = len(harness.score_calls)

    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert _call_counts(harness) == (2, 2, score_calls * 2, 3, 3)
    current = json.loads((root / _STAGE_FILES[1]).read_text(encoding="utf-8"))
    assert current["cache_key"] != old_evaluation["cache_key"]
    assert current["transcript_fingerprint"] != old_evaluation["transcript_fingerprint"]
    assert current["evaluations"][0]["features"]["transcript_confidence"] == 0.5
    assert (root / _STAGE_FILES[2]).read_bytes() != old_scores


@pytest.mark.parametrize(
    ("changes", "invalidated"),
    [
        ({"clips": 2}, {"selection", "refinement"}),
        ({"refinement_post_roll": 0.1}, {"refinement"}),
        ({"aspect_ratio": "9:16"}, set()),
        ({"subtitle_template": "other-template"}, set()),
    ],
)
def test_downstream_configuration_preserves_asr_evaluation_and_scores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
    invalidated: set[str],
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch, before_render=True)
    original = {name: (root / name).read_bytes() for name in _STAGE_FILES}
    scores = len(harness.score_calls)

    result = harness.run(replace(harness.config, **changes))

    if "refinement_post_roll" in changes:
        assert result.outcome is RunOutcome.PARTIAL
        assert result.warnings == ("refinement_requires_rescore",)
    else:
        assert result.outcome is RunOutcome.COMPLETED
    assert _call_counts(harness)[:3] == (1, 1, scores)
    for name, contents in original.items():
        assert ((root / name).read_bytes() != contents) == (
            name.split("/")[0] in invalidated
        )
    for video in result.clip_paths:
        clip = read_clip_metadata_payload(
            json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
        )
        if "aspect_ratio" in changes:
            assert (clip.render_config.width, clip.render_config.height) == (720, 1280)
        if "subtitle_template" in changes:
            assert clip.render_config.template_resolved == "other-template"


@pytest.mark.parametrize("change", ["source", "model", "language", "provider"])
def test_transcription_inputs_create_independent_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    harness = _harness(tmp_path)
    old_root = _interrupt_run(harness, monkeypatch, before_render=True)
    before = _file_bytes(old_root)
    config = harness.config
    if change == "source":
        Path(config.source).write_bytes(b"different source content")
    elif change == "model":
        config = replace(config, model="another-model")
    elif change == "language":
        config = replace(config, language="en")
    else:
        harness.transcriber.transcript = replace(
            harness.transcriber.transcript, provider_version="4.3.1"
        )

    result = harness.run(config)

    assert result.outcome is RunOutcome.COMPLETED
    assert result.manifest_path.parent != old_root
    assert _file_bytes(old_root) == before
    assert _call_counts(harness)[:2] == (2, 2)
    assert (
        read_manifest_payload(
            json.loads(result.manifest_path.read_text(encoding="utf-8"))
        ).config.transcription_model
        == config.model
    )


def test_scoring_version_change_reuses_transcript_and_deterministic_features(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from multicuts.scoring import artifacts

    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch, before_render=True)
    transcript = (root / _STAGE_FILES[0]).read_bytes()
    evaluation = (root / _STAGE_FILES[1]).read_bytes()
    scores = (root / _STAGE_FILES[2]).read_bytes()
    calls = len(harness.score_calls)
    monkeypatch.setattr(artifacts, "SCORING_STAGE_VERSION", 3)

    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert _call_counts(harness)[:3] == (1, 1, calls * 2)
    assert (root / _STAGE_FILES[0]).read_bytes() == transcript
    assert (root / _STAGE_FILES[1]).read_bytes() == evaluation
    assert (root / _STAGE_FILES[2]).read_bytes() != scores


def test_custom_template_content_change_reuses_raw_clips_and_upstream_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    templates = tmp_path / "templates"
    templates.mkdir()
    template = templates / "custom.json"
    template.write_text('{"font_size": 30}', encoding="utf-8")
    harness.config = replace(harness.config, subtitle_template_dir=templates)
    root = _interrupt_run(harness, monkeypatch)
    before = _file_bytes(root)
    calls = _call_counts(harness)
    template.write_text('{"font_size": 36}', encoding="utf-8")

    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert _call_counts(harness) == (*calls[:4], calls[4] * 2)
    assert all(path.read_bytes() == content for path, content in before.items())
    assert all(video not in before for video in result.clip_paths)


def test_mismatched_candidate_evidence_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch, before_render=True)
    target = root / _STAGE_FILES[1]
    before = target.read_bytes()
    payload = json.loads(before)
    payload["evaluations"][0]["candidate"]["text"] = "Fabricated candidate text."
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert target.read_bytes() == before
    assert len(harness.evaluation_calls) == 2
    assert len(harness.transcriber.calls) == 1


@pytest.mark.parametrize("damage", ["malformed", "conflicting"])
def test_invalid_completed_clip_metadata_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch)
    target = sorted((root / "clips").glob("*.json"))[0]
    if damage == "malformed":
        target.write_bytes(b"{unfinished")
    else:
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["transcript"] = "Unrelated transcript."
        target.write_text(json.dumps(payload), encoding="utf-8")
    before = _file_bytes(root)
    calls = _call_counts(harness)

    with pytest.raises(
        ArtifactError, match="Completed clip metadata.*output directory"
    ):
        harness.run()

    assert _file_bytes(root) == before
    assert _call_counts(harness) == calls


def test_final_checkpoint_stat_error_is_not_a_cache_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch)
    video = sorted((root / "clips").glob("*.mp4"))[0]
    target = root / "rendering/subtitles" / f"{video.stem}.json"
    calls = _call_counts(harness)
    original_lstat = Path.lstat

    def deny_stat(path: Path):
        if path == target:
            raise PermissionError("injected metadata stat failure")
        return original_lstat(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", deny_stat)
        with pytest.raises(ArtifactError, match="Could not inspect cached final"):
            harness.run()

    assert _call_counts(harness) == calls
    assert not (root / "manifest.json").exists()


def test_previous_evaluation_schema_recomputes_without_retranscription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch, before_render=True)
    target = root / _STAGE_FILES[1]
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    del payload["transcript_fingerprint"]
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert _call_counts(harness)[:2] == (1, 2)
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == 2


@pytest.mark.parametrize("changed_version", ["renderer", "subtitle"])
def test_media_provider_versions_invalidate_only_dependent_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_version: str
) -> None:
    harness = _harness(tmp_path)
    root = _interrupt_run(harness, monkeypatch)
    before = _file_bytes(root)
    counts = _call_counts(harness)
    if changed_version == "renderer":
        monkeypatch.setattr(harness.renderer, "version", lambda: "ffmpeg fixture v2")
    else:
        monkeypatch.setattr(harness.subtitles, "version", lambda: "4.3.1")

    result = harness.run()

    assert result.outcome is RunOutcome.COMPLETED
    assert _call_counts(harness)[:3] == counts[:3]
    assert len(harness.renderer.calls) == counts[3] * (
        2 if changed_version == "renderer" else 1
    )
    assert len(harness.subtitles.calls) == counts[4] * 2
    assert all(video not in before for video in result.clip_paths)
    assert all(path.read_bytes() == content for path, content in before.items())

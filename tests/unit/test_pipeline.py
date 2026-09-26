import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.adapters.multisubs_subtitles import SubtitleArtifacts
from multicuts.artifacts import WorkspacePaths
from multicuts.config import RunConfig
from multicuts.errors import (
    AcquisitionError,
    ArtifactError,
    MediaError,
    RenderingError,
    TranscriptionError,
)
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationBatch,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    ClipTranscript,
    MediaInfo,
    RefinedSelection,
    RenderedClip,
    RenderRequest,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import RunResult, run_pipeline
from multicuts.rendering.subtitles import SubtitledClip


@pytest.fixture
def config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        source="source.mp4",
        output_dir=tmp_path / "output",
        clips=3,
        min_score=0,
        aspect_ratio="original",
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
    )


class FakeTranscriber:
    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.calls: list[tuple[Path, str | None, str, Path]] = []
        self.provider_version = transcript.provider_version

    def version(self) -> str:
        return self.provider_version

    def transcribe(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
    ) -> Transcript:
        self.calls.append((video_path, language, model, workspace))
        return self.transcript


class FakeSubtitleRenderer:
    def __init__(self) -> None:
        self.calls = 0

    def version(self) -> str:
        return "4.3.0"

    def inspect(self, path: Path) -> MediaInfo:
        del path
        return MediaInfo(30.25, 1920, 1080, 1920, 1080, 0, 1)

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
        del clip, template_dir
        self.calls += 1
        workspace.mkdir(parents=True)
        cues = workspace / "clip.cues.json"
        srt = workspace / "clip.srt"
        ass = workspace / "clip.ass"
        for path, content in (
            (cues, b"{}"),
            (srt, b"1\n00:00:00,000 --> 00:00:01,000\ncaption"),
            (ass, b"[Script Info]"),
        ):
            path.write_bytes(content)
        output_path.write_bytes(b"subtitled media")
        artifacts = SubtitleArtifacts(
            cues, srt, ass, output_path, "4.3.0", template, template or "default"
        )
        return SubtitledClip(raw, output_path, 1920, 1080, 30.25, True, artifacts)


@pytest.fixture
def transcript() -> Transcript:
    return Transcript(
        language_requested=None,
        language_detected="pt",
        duration=12.0,
        text="Olá mundo",
        segments=(TranscriptSegment("Olá mundo", 0.0, 2.0),),
        words=(Word("Olá", 0.0, 0.5), Word("mundo", 0.6, 1.2)),
        provider="multisubs",
        provider_version="4.1.0",
    )


def test_pipeline_runs_acquisition_before_media_probe(
    config: RunConfig,
    transcript: Transcript,
) -> None:
    events: list[tuple[str, object]] = []
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)

    def acquire(value: str, _workspace: Path) -> AcquiredSource:
        events.append(("acquire", value))
        return source

    def probe(value: AcquiredSource) -> MediaInfo:
        events.append(("probe", value))
        return media

    def generate(
        transcript: Transcript,
        *,
        source_fingerprint: str,
        min_duration: float,
        max_duration: float,
    ) -> tuple[Candidate, ...]:
        events.append(
            (
                "generate",
                (transcript, source_fingerprint, min_duration, max_duration),
            )
        )
        return ()

    transcriber = FakeTranscriber(transcript)
    run_pipeline(
        config,
        acquire=acquire,
        probe=probe,
        transcriber=transcriber,
        candidate_generator=generate,
    )

    assert events == [
        ("acquire", "source.mp4"),
        ("probe", source),
        (
            "generate",
            (transcript, source.fingerprint, config.min_duration, config.max_duration),
        ),
    ]
    assert len(transcriber.calls) == 1
    assert transcriber.calls[0][:3] == (source.local_path, None, "default")
    assert (config.output_dir).is_dir()
    manifest = json.loads(
        next(config.output_dir.rglob("manifest.json")).read_text(encoding="utf-8")
    )
    assert manifest["outcome"] == "zero_selection"
    assert manifest["clips"] == []
    assert manifest["candidate_generation"]["count"] == 0
    assert list(config.output_dir.rglob("refinement.json")) == []


def test_pipeline_passes_explicit_acquisition_workspace(
    config: RunConfig,
    transcript: Transcript,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    calls: list[tuple[str, Path]] = []

    def acquire(value: str, workspace: Path) -> AcquiredSource:
        calls.append((value, workspace))
        return source

    run_pipeline(
        config,
        acquire=acquire,
        probe=lambda _source: media,
        transcriber=FakeTranscriber(transcript),
    )

    assert calls == [
        (config.source, (config.output_dir / ".work" / "acquisition").resolve())
    ]


def test_pipeline_propagates_acquisition_errors_without_probing(
    config: RunConfig,
) -> None:
    called = False

    def acquire(_value: str, _workspace: Path) -> AcquiredSource:
        raise AcquisitionError("source unavailable")

    def probe(_value: AcquiredSource) -> MediaInfo:
        nonlocal called
        called = True
        raise AssertionError("probe must not run after acquisition failure")

    with pytest.raises(AcquisitionError, match="source unavailable"):
        run_pipeline(config, acquire=acquire, probe=probe)

    assert not called


def test_pipeline_propagates_media_errors_without_fabricating_completion(
    config: RunConfig,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")

    def acquire(_value: str, _workspace: Path) -> AcquiredSource:
        return source

    def probe(_value: AcquiredSource) -> MediaInfo:
        raise MediaError("media unavailable")

    with pytest.raises(MediaError, match="media unavailable"):
        run_pipeline(config, acquire=acquire, probe=probe)


def test_pipeline_logs_stage_and_safe_resource_context(
    config: RunConfig,
    transcript: Transcript,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = replace(
        config,
        source="https://example.test/video.mp4?token=super-secret",
    )
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)

    with caplog.at_level(logging.INFO, logger="multicuts.pipeline"):
        run_pipeline(
            config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=FakeTranscriber(transcript),
        )

    messages = [record.getMessage() for record in caplog.records]
    assert any("stage=acquire origin=remote" in message for message in messages)
    assert any("stage=probe complete origin=remote" in message for message in messages)
    assert any("stage=transcribe cache=miss" in message for message in messages)
    assert any("stage=candidates complete count=0" in message for message in messages)
    assert all("example.test" not in message for message in messages)
    assert all("video.mp4" not in message for message in messages)
    assert all("source.mp4" not in message for message in messages)
    assert all("super-secret" not in message for message in messages)


def test_pipeline_reuses_persisted_transcript_without_new_asr(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    transcriber = FakeTranscriber(transcript)
    generated: list[Transcript] = []

    def generate(
        transcript: Transcript,
        *,
        source_fingerprint: str,
        min_duration: float,
        max_duration: float,
    ) -> tuple[Candidate, ...]:
        generated.append(transcript)
        return ()

    for attempt in range(2):
        run_pipeline(
            config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=transcriber,
            candidate_generator=generate,
        )
        if attempt == 0:
            # Simulate an unfinished run whose stage cache remains reusable.
            next(config.output_dir.rglob("manifest.json")).unlink()

    assert len(transcriber.calls) == 1
    assert generated == [transcript, transcript]
    assert list(config.output_dir.rglob("transcript.json"))


def test_pipeline_propagates_candidate_generation_errors(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)

    def generate(
        transcript: Transcript,
        *,
        source_fingerprint: str,
        min_duration: float,
        max_duration: float,
    ) -> tuple[Candidate, ...]:
        raise ValueError("candidate generation failed")

    with pytest.raises(ValueError, match="candidate generation failed"):
        run_pipeline(
            config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=FakeTranscriber(transcript),
            candidate_generator=generate,
        )


def test_pipeline_reuses_same_content_after_source_rename(
    config: RunConfig, transcript: Transcript
) -> None:
    first = AcquiredSource(Path("/tmp/first.mp4"), "sha256-v1:abc")
    renamed = AcquiredSource(Path("/tmp/renamed.mp4"), first.fingerprint)
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    transcriber = FakeTranscriber(transcript)

    for source in (first, renamed):

        def acquire(
            _value: str,
            _workspace: Path,
            selected: AcquiredSource = source,
        ) -> AcquiredSource:
            return selected

        run_pipeline(
            config,
            acquire=acquire,
            probe=lambda _value: media,
            transcriber=transcriber,
        )
        if source is first:
            next(config.output_dir.rglob("manifest.json")).unlink()

    assert len(transcriber.calls) == 1


def test_pipeline_invalid_cache_is_recomputed(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    transcriber = FakeTranscriber(transcript)

    def run() -> None:
        run_pipeline(
            config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=transcriber,
        )

    run()
    artifact = next(config.output_dir.rglob("transcript.json"))
    artifact.write_text("{incomplete", encoding="utf-8")
    next(config.output_dir.rglob("manifest.json")).unlink()
    run()

    assert len(transcriber.calls) == 2
    assert '"schema_version": 1' in artifact.read_text(encoding="utf-8")


def test_pipeline_rejects_incompatible_provider_provenance_before_publication(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    transcriber = FakeTranscriber(replace(transcript, provider="other"))

    with pytest.raises(TranscriptionError, match="incompatible provenance"):
        run_pipeline(
            config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=transcriber,
        )

    assert list(config.output_dir.rglob("transcript.json")) == []


def test_pipeline_force_recompute_bypasses_cache_but_not_completed_output(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    transcriber = FakeTranscriber(transcript)
    forced = replace(config, force_recompute=True)

    for run_config in (config, forced):
        run_pipeline(
            run_config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=transcriber,
        )
        if run_config is config:
            next(config.output_dir.rglob("manifest.json")).unlink()
    assert len(transcriber.calls) == 2

    manifest = next(config.output_dir.rglob("manifest.json"))
    assert manifest.is_file()
    with pytest.raises(ArtifactError, match="Completed output already exists"):
        run_pipeline(
            forced,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=transcriber,
        )
    assert len(transcriber.calls) == 2


def test_pipeline_ignores_non_transcription_config_for_cache(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    transcriber = FakeTranscriber(transcript)
    changed = replace(
        config,
        clips=7,
        min_score=40,
        aspect_ratio="9:16",
        subtitle_template="different",
    )

    for run_config in (config, changed):
        run_pipeline(
            run_config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=transcriber,
        )
        if run_config is config:
            next(config.output_dir.rglob("manifest.json")).unlink()

    assert len(transcriber.calls) == 1


def test_pipeline_allows_hybrid_mode_without_credentials_when_shortlist_is_empty(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    run_pipeline(
        replace(config, scorer="hybrid"),
        acquire=lambda _value, _workspace: source,
        probe=lambda _value: media,
        transcriber=FakeTranscriber(transcript),
    )
    manifest = json.loads(
        next(config.output_dir.rglob("manifest.json")).read_text(encoding="utf-8")
    )
    assert manifest["scoring"]["configured_mode"] == "hybrid"
    assert manifest["scoring"]["count"] == 0
    assert manifest["scoring"]["provider"] is None
    assert manifest["scoring"]["model"] is None


def test_pipeline_selects_scored_shortlist_before_boundary_refinement(
    config: RunConfig, transcript: Transcript, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(40.0, 1920, 1080, 1920, 1080, 0, 1)
    candidate = Candidate(
        "candidate-v1:one", 0.0, 30.0, "A complete example with a payoff.", (0,), "1"
    )
    evaluated = CandidateEvaluation(
        candidate=candidate,
        features=CandidateFeatures(
            duration=30.0,
            word_count=6,
            timed_word_count=6,
            words_per_second=1.5,
            opening_quality=0.8,
            standalone_context=0.75,
            payoff=0.7,
        ),
        checklist=(ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        shortlist_rank=1,
    )

    def evaluator(*_args: object, **_kwargs: object) -> CandidateEvaluationBatch:
        return CandidateEvaluationBatch((evaluated,), (evaluated,))

    class FakeRenderer:
        def __init__(self) -> None:
            self.render_calls = 0

        def version(self) -> str:
            return "ffmpeg test"

        def inspect(self, path: Path) -> MediaInfo:
            return MediaInfo(30.25, 1920, 1080, 1920, 1080, 0, 1)

        def render(self, request: RenderRequest) -> RenderedClip:
            self.render_calls += 1
            request.output_path.write_bytes(b"fake media")
            return RenderedClip(
                request.refined,
                request.output_path,
                1920,
                1080,
                30.25,
                True,
                request.renderer_version,
                request.cache_key,
            )

    renderer = FakeRenderer()
    subtitle_renderer = FakeSubtitleRenderer()
    first_result = run_pipeline(
        config,
        acquire=lambda _value, _workspace: source,
        probe=lambda _value: media,
        transcriber=FakeTranscriber(transcript),
        candidate_generator=lambda *_args, **_kwargs: (candidate,),
        candidate_evaluator=evaluator,
        renderer=renderer,
        subtitle_renderer=subtitle_renderer,
    )

    first_outputs = first_result.clip_paths
    assert len(first_outputs) == 1
    assert first_result.outcome.value == "completed"
    assert first_result.manifest_path.is_file()
    assert first_outputs[0].is_file()
    assert subtitle_renderer.calls == 1
    manifest = next(config.output_dir.rglob("manifest.json"))
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    clip_payload = json.loads(
        first_outputs[0].with_suffix(".json").read_text(encoding="utf-8")
    )
    assert manifest_payload["outcome"] == "completed"
    assert manifest_payload["clips"][0]["output_path"] == clip_payload["output_path"]
    assert manifest_payload["source"]["reference"] == "local:sha256-v1:abc"
    assert clip_payload["source_end"] == 30.0
    assert clip_payload["render_end"] == 30.25
    assert clip_payload["render_config"]["template_resolved"] == "yellow-pop"
    assert all(item["duration_seconds"] >= 0 for item in manifest_payload["timings"])
    score_path = next(config.output_dir.rglob("scores.json"))
    assert '"candidate_id": "candidate-v1:one"' in score_path.read_text(
        encoding="utf-8"
    )
    selection_path = next(config.output_dir.rglob("selection.json"))
    selection_payload = selection_path.read_text(encoding="utf-8")
    assert '"candidate_id": "candidate-v1:one"' in selection_payload
    assert '"status": "selected"' in selection_payload

    refinement_path = next(config.output_dir.rglob("refinement.json"))
    refinement_payload = refinement_path.read_text(encoding="utf-8")
    assert '"candidate_id": "candidate-v1:one"' in refinement_payload
    assert '"scored_end": 30.0' in refinement_payload
    assert '"render_end": 30.25' in refinement_payload

    def unexpected_refinement(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("matching refinement artifact should be reused")

    monkeypatch.setattr("multicuts.pipeline.refine_selection", unexpected_refinement)
    next(config.output_dir.rglob("manifest.json")).unlink()
    first_outputs[0].with_suffix(".json").unlink()
    run_pipeline(
        config,
        acquire=lambda _value, _workspace: source,
        probe=lambda _value: media,
        transcriber=FakeTranscriber(transcript),
        candidate_generator=lambda *_args, **_kwargs: (candidate,),
        candidate_evaluator=evaluator,
        renderer=renderer,
        subtitle_renderer=subtitle_renderer,
    )
    assert subtitle_renderer.calls == 1
    assert renderer.render_calls == 1

    next(config.output_dir.rglob("manifest.json")).unlink()
    changed_template = replace(config, subtitle_template="different-template")
    run_pipeline(
        changed_template,
        acquire=lambda _value, _workspace: source,
        probe=lambda _value: media,
        transcriber=FakeTranscriber(transcript),
        candidate_generator=lambda *_args, **_kwargs: (candidate,),
        candidate_evaluator=evaluator,
        renderer=renderer,
        subtitle_renderer=subtitle_renderer,
    )
    assert renderer.render_calls == 1
    assert subtitle_renderer.calls == 2


@pytest.mark.parametrize(
    ("failing_ranks", "failure_stage", "expected_outcome", "expected_completed"),
    [
        ({2}, "raw", "partial", 1),
        ({1, 2}, "raw", "failed", 0),
        ({2}, "final", "partial", 1),
    ],
)
def test_pipeline_records_render_failures_and_keeps_successful_clips(
    config: RunConfig,
    transcript: Transcript,
    failing_ranks: set[int],
    failure_stage: str,
    expected_outcome: str,
    expected_completed: int,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(60.0, 1920, 1080, 1920, 1080, 0, 1)
    config = replace(
        config,
        clips=2,
        subtitles_enabled=failure_stage == "final",
        refinement_pre_roll=0.0,
        refinement_post_roll=0.0,
    )
    transcript = replace(
        transcript,
        duration=60.0,
        text="Alpha point. Beta point.",
        segments=(
            TranscriptSegment("Alpha point.", 0.0, 20.0),
            TranscriptSegment("Beta point.", 30.0, 50.0),
        ),
        words=(
            Word("Alpha", 0.0, 0.5),
            Word("point.", 19.5, 20.0),
            Word("Beta", 30.0, 30.5),
            Word("point.", 49.5, 50.0),
        ),
    )
    candidates = (
        Candidate("candidate-v1:alpha", 0.0, 20.0, "Alpha point.", (0,), "1"),
        Candidate("candidate-v1:beta", 30.0, 50.0, "Beta point.", (1,), "1"),
    )
    evaluations = tuple(
        CandidateEvaluation(
            candidate=candidate,
            features=CandidateFeatures(
                duration=20.0,
                word_count=2,
                timed_word_count=2,
                words_per_second=0.1,
                opening_quality=0.8,
                standalone_context=0.75,
                payoff=0.7,
            ),
            checklist=(ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
            shortlist_rank=index,
        )
        for index, candidate in enumerate(candidates, start=1)
    )

    class FailingRenderer:
        def __init__(self) -> None:
            self.calls: list[int] = []
            self.version_calls = 0

        def version(self) -> str:
            self.version_calls += 1
            return "ffmpeg test"

        def inspect(self, path: Path) -> MediaInfo:
            del path
            return MediaInfo(20.0, 1920, 1080, 1920, 1080, 0, 1)

        def render(self, request: RenderRequest) -> RenderedClip:
            rank = request.refined.rank
            self.calls.append(rank)
            if failure_stage == "raw" and rank in failing_ranks:
                raise RenderingError("synthetic render failure")
            request.output_path.write_bytes(b"fake media")
            return RenderedClip(
                request.refined,
                request.output_path,
                1920,
                1080,
                20.0,
                True,
                request.renderer_version,
                request.cache_key,
            )

    class FailingSubtitleRenderer:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def version(self) -> str:
            return "4.3.0"

        def inspect(self, path: Path) -> MediaInfo:
            del path
            return MediaInfo(20.0, 1920, 1080, 1920, 1080, 0, 1)

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
            del clip, template_dir
            rank = raw.refined.rank
            self.calls.append(rank)
            if rank in failing_ranks:
                raise RenderingError("synthetic subtitle failure")
            workspace.mkdir(parents=True)
            cues = workspace / "clip.cues.json"
            srt = workspace / "clip.srt"
            ass = workspace / "clip.ass"
            for path in (cues, srt, ass):
                path.write_bytes(b"subtitle")
            output_path.write_bytes(b"final")
            artifacts = SubtitleArtifacts(
                cues, srt, ass, output_path, "4.3.0", template, template or "default"
            )
            return SubtitledClip(raw, output_path, 1920, 1080, 20.0, True, artifacts)

    subtitle_renderer = FailingSubtitleRenderer()
    renderer = FailingRenderer()
    transcriber = FakeTranscriber(transcript)
    result = run_pipeline(
        config,
        acquire=lambda _value, _workspace: source,
        probe=lambda _value: media,
        transcriber=transcriber,
        candidate_generator=lambda *_args, **_kwargs: candidates,
        candidate_evaluator=lambda *_args, **_kwargs: CandidateEvaluationBatch(
            evaluations, evaluations
        ),
        renderer=renderer,
        subtitle_renderer=subtitle_renderer if failure_stage == "final" else None,
    )

    assert result.outcome.value == expected_outcome
    assert result.manifest_path.is_file()
    assert len(result.clip_paths) == expected_completed
    assert all(
        path.is_file() and path.with_suffix(".json").is_file()
        for path in result.clip_paths
    )
    assert len(transcriber.calls) == 1
    assert sorted(renderer.calls) == [1, 2]
    assert renderer.version_calls == 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [item["status"] for item in manifest["clips"]].count(
        "completed"
    ) == expected_completed
    assert [item["status"] for item in manifest["clips"]].count(
        "failed"
    ) == 2 - expected_completed
    assert (
        "final_render_failed" if failure_stage == "final" else "raw_render_failed"
    ) in manifest["warnings"]
    if failure_stage == "final":
        assert sorted(subtitle_renderer.calls) == [1, 2]
    assert result.warnings == tuple(manifest["warnings"])


@pytest.mark.parametrize(
    ("interrupt_stage", "cleanup_fails"),
    [
        ("before_metadata", False),
        ("after_metadata", False),
        ("inside_renderer", False),
        ("before_metadata", True),
    ],
)
def test_keyboard_interrupt_during_raw_render_publication_is_preserved(
    tmp_path: Path,
    transcript: Transcript,
    config: RunConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    interrupt_stage: str,
    cleanup_fails: bool,
) -> None:
    from multicuts import pipeline

    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:interrupt")
    media = MediaInfo(60.0, 1920, 1080, 1920, 1080, 0, 1)
    transcript = replace(
        transcript,
        duration=60.0,
        text="A complete point.",
        segments=(TranscriptSegment("A complete point.", 0.0, 30.0),),
        words=(Word("A", 0.0, 0.5), Word("point.", 29.5, 30.0)),
    )
    candidate = Candidate(
        "candidate-v1:interrupt", 0.0, 30.0, "A complete point.", (0,), "1"
    )
    evaluation = CandidateEvaluation(
        candidate,
        CandidateFeatures(
            duration=30.0,
            word_count=3,
            timed_word_count=2,
            words_per_second=0.1,
        ),
        (ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        1,
    )
    config = replace(
        config,
        clips=1,
        subtitles_enabled=False,
        min_duration=15.0,
        max_duration=30.0,
        refinement_pre_roll=0.0,
        refinement_post_roll=0.0,
    )

    class Renderer:
        def __init__(self) -> None:
            self.calls = 0
            self.output_path: Path | None = None
            self.interrupt_after_publish = False

        def version(self) -> str:
            return "ffmpeg test"

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
            self.calls += 1
            self.output_path = request.output_path
            duration = request.refined.render_end - request.refined.render_start
            request.output_path.write_text(
                json.dumps(
                    {
                        "duration": duration,
                        "width": request.media.presentation_width,
                        "height": request.media.presentation_height,
                    }
                ),
                encoding="utf-8",
            )
            if self.interrupt_after_publish:
                raise KeyboardInterrupt
            return RenderedClip(
                request.refined,
                request.output_path,
                request.media.presentation_width,
                request.media.presentation_height,
                duration,
                True,
                request.renderer_version,
                request.cache_key,
            )

    renderer = Renderer()
    transcriber = FakeTranscriber(transcript)

    def run() -> RunResult:
        return run_pipeline(
            config,
            acquire=lambda _value, _workspace: source,
            probe=lambda _value: media,
            transcriber=transcriber,
            candidate_generator=lambda *_args, **_kwargs: (candidate,),
            candidate_evaluator=lambda *_args, **_kwargs: CandidateEvaluationBatch(
                (evaluation,), (evaluation,)
            ),
            renderer=renderer,
        )

    original_write_render = pipeline.write_render
    original_render_paths = pipeline.render_paths
    render_metadata_paths: list[Path] = []

    def capture_render_paths(
        paths: WorkspacePaths, refined: RefinedSelection, cache_key: str
    ) -> tuple[Path, Path]:
        output_path, metadata_path = original_render_paths(paths, refined, cache_key)
        render_metadata_paths.append(metadata_path)
        return output_path, metadata_path

    monkeypatch.setattr(pipeline, "render_paths", capture_render_paths)
    if interrupt_stage == "before_metadata":

        def interrupt_before_metadata(*_args: object, **_kwargs: object) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(pipeline, "write_render", interrupt_before_metadata)
    elif interrupt_stage == "after_metadata":

        def interrupt_after_metadata(
            paths: WorkspacePaths,
            request: RenderRequest,
            result: RenderedClip,
            metadata_path: Path,
        ) -> None:
            original_write_render(paths, request, result, metadata_path)
            raise KeyboardInterrupt

        monkeypatch.setattr(pipeline, "write_render", interrupt_after_metadata)
    else:
        renderer.interrupt_after_publish = True

    caplog.set_level(logging.WARNING, logger="multicuts.pipeline")
    original_unlink = Path.unlink
    if cleanup_fails:

        def fail_raw_unlink(path: Path, missing_ok: bool = False) -> None:
            if path == renderer.output_path:
                raise PermissionError("synthetic cleanup failure")
            original_unlink(path, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", fail_raw_unlink)

    with pytest.raises(KeyboardInterrupt):
        run()

    raw_path = renderer.output_path
    assert raw_path is not None
    assert len(render_metadata_paths) == 1
    metadata_path = render_metadata_paths[0]
    assert not tuple(config.output_dir.rglob("manifest.json"))
    if cleanup_fails:
        assert raw_path.is_file()
        assert not metadata_path.exists()
        assert "stage=render cleanup=failed artifact=media rank=1" in caplog.text
        original_unlink(raw_path)
        return

    assert not raw_path.exists()
    assert not metadata_path.exists()
    renderer.interrupt_after_publish = False
    monkeypatch.setattr(pipeline, "write_render", original_write_render)
    result = run()
    assert result.outcome.value == "completed"
    assert renderer.calls == 2
    assert len(transcriber.calls) == 1

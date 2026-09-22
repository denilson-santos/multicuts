import logging
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.config import RunConfig
from multicuts.errors import (
    AcquisitionError,
    ArtifactError,
    MediaError,
    ScoringError,
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
    MediaInfo,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import PipelineNotReadyError, run_pipeline


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
    with pytest.raises(PipelineNotReadyError, match="after heuristic scoring"):
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

    with pytest.raises(PipelineNotReadyError):
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
        with pytest.raises(PipelineNotReadyError):
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

    for _ in range(2):
        with pytest.raises(PipelineNotReadyError):
            run_pipeline(
                config,
                acquire=lambda _value, _workspace: source,
                probe=lambda _value: media,
                transcriber=transcriber,
                candidate_generator=generate,
            )

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

        with pytest.raises(PipelineNotReadyError):
            run_pipeline(
                config,
                acquire=acquire,
                probe=lambda _value: media,
                transcriber=transcriber,
            )

    assert len(transcriber.calls) == 1


def test_pipeline_invalid_cache_is_recomputed(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    transcriber = FakeTranscriber(transcript)

    def run() -> None:
        with pytest.raises(PipelineNotReadyError):
            run_pipeline(
                config,
                acquire=lambda _value, _workspace: source,
                probe=lambda _value: media,
                transcriber=transcriber,
            )

    run()
    artifact = next(config.output_dir.rglob("transcript.json"))
    artifact.write_text("{incomplete", encoding="utf-8")
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
        with pytest.raises(PipelineNotReadyError):
            run_pipeline(
                run_config,
                acquire=lambda _value, _workspace: source,
                probe=lambda _value: media,
                transcriber=transcriber,
            )
    assert len(transcriber.calls) == 2

    manifest = (
        next(config.output_dir.rglob("transcript.json")).parent.parent / "manifest.json"
    )
    manifest.write_text("{}", encoding="utf-8")
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
        with pytest.raises(PipelineNotReadyError):
            run_pipeline(
                run_config,
                acquire=lambda _value, _workspace: source,
                probe=lambda _value: media,
                transcriber=transcriber,
            )

    assert len(transcriber.calls) == 1


def test_pipeline_rejects_unsupported_scorer_after_reusing_transcript(
    config: RunConfig, transcript: Transcript
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)
    with pytest.raises(ScoringError, match="Unsupported scorer"):
        run_pipeline(
            replace(config, scorer="hybrid"),
            acquire=lambda _value: source,
            probe=lambda _value: media,
            transcriber=FakeTranscriber(transcript),
        )


def test_pipeline_scores_shortlist_before_selection_boundary(
    config: RunConfig, transcript: Transcript
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

    with pytest.raises(PipelineNotReadyError, match="after heuristic scoring"):
        run_pipeline(
            config,
            acquire=lambda _value: source,
            probe=lambda _value: media,
            transcriber=FakeTranscriber(transcript),
            candidate_generator=lambda *_args, **_kwargs: (candidate,),
            candidate_evaluator=evaluator,
        )

    score_path = next(config.output_dir.rglob("scores.json"))
    assert '"candidate_id": "candidate-v1:one"' in score_path.read_text(
        encoding="utf-8"
    )

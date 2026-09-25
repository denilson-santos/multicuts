import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.adapters.multisubs_subtitles import SubtitleArtifacts
from multicuts.config import RunConfig
from multicuts.errors import (
    AcquisitionError,
    ArtifactError,
    MediaError,
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
    RenderedClip,
    RenderRequest,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import run_pipeline
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
    first_outputs = run_pipeline(
        config,
        acquire=lambda _value, _workspace: source,
        probe=lambda _value: media,
        transcriber=FakeTranscriber(transcript),
        candidate_generator=lambda *_args, **_kwargs: (candidate,),
        candidate_evaluator=evaluator,
        renderer=renderer,
        subtitle_renderer=subtitle_renderer,
    )

    assert len(first_outputs) == 1
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

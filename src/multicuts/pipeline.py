"""Synchronous orchestration boundary for one multicuts run."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, Protocol
from urllib.parse import urlsplit

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.artifacts import (
    InvalidCandidateEvaluationArtifactError,
    InvalidTranscriptArtifactError,
    candidate_evaluation_cache_key,
    prepare_workspace,
    read_candidate_evaluation,
    read_transcript,
    transcription_cache_key,
    write_candidate_evaluation,
    write_transcript,
)
from multicuts.candidates.filters import (
    CANDIDATE_EVALUATION_VERSION,
    evaluate_candidates,
)
from multicuts.candidates.generator import (
    CANDIDATE_GENERATOR_VERSION,
    generate_candidates,
)
from multicuts.config import RunConfig
from multicuts.errors import TranscriptionError
from multicuts.local_source import acquire_local_source
from multicuts.media import probe_media
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluationArtifact,
    CandidateEvaluationBatch,
    MediaInfo,
    Transcript,
)

AcquireSource = Callable[[str], AcquiredSource]
ProbeMedia = Callable[[AcquiredSource], MediaInfo]

logger = logging.getLogger(__name__)
TRANSCRIPTION_PROVIDER = "multisubs"


class TranscriptionProvider(Protocol):
    """The substitutable source transcription boundary."""

    def version(self) -> str: ...

    def transcribe(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
    ) -> Transcript: ...


class CandidateGenerator(Protocol):
    """The substitutable pure candidate-generation boundary."""

    def __call__(
        self,
        transcript: Transcript,
        *,
        source_fingerprint: str,
        min_duration: float,
        max_duration: float,
    ) -> tuple[Candidate, ...]: ...


class CandidateEvaluator(Protocol):
    """The substitutable pure candidate-evaluation boundary."""

    def __call__(
        self,
        candidates: tuple[Candidate, ...],
        transcript: Transcript,
        *,
        min_duration: float,
        max_duration: float,
        candidate_budget: int,
    ) -> CandidateEvaluationBatch: ...


class PipelineNotReadyError(RuntimeError):
    """Raised while downstream scoring and final publication are unavailable."""


def _source_origin(source: str) -> str:
    """Classify the source without retaining user-provided identifiers."""
    try:
        parsed = urlsplit(source)
    except ValueError:
        return "unknown"
    return "remote" if parsed.scheme and parsed.netloc else "local"


def load_or_transcribe(
    config: RunConfig, source: AcquiredSource, *, provider: TranscriptionProvider
) -> Transcript:
    """Reuse a matching source transcript or publish one new ASR result."""
    version = provider.version()
    key = transcription_cache_key(
        source_fingerprint=source.fingerprint,
        provider=TRANSCRIPTION_PROVIDER,
        provider_version=version,
        model=config.model,
        language=config.language,
    )
    paths = prepare_workspace(config.output_dir, source, cache_key=key)
    if not config.force_recompute:
        try:
            cached = read_transcript(paths, cache_key=key)
        except InvalidTranscriptArtifactError:
            logger.warning("stage=transcribe cache=invalid; recomputing")
        else:
            if cached is not None and (
                cached.provider == TRANSCRIPTION_PROVIDER
                and cached.provider_version == version
                and cached.language_requested == config.language
            ):
                logger.info("stage=transcribe cache=hit")
                return cached

    logger.info("stage=transcribe cache=miss")
    transcript = provider.transcribe(
        source.local_path,
        language=config.language,
        model=config.model,
        workspace=paths.work,
    )
    if (
        transcript.provider != TRANSCRIPTION_PROVIDER
        or transcript.provider_version != version
        or transcript.language_requested != config.language
    ):
        raise TranscriptionError(
            "Transcription provider returned incompatible provenance"
        )
    write_transcript(
        paths,
        transcript,
        cache_key=key,
        replace=paths.transcript.exists(),
    )
    return transcript


def load_or_evaluate_candidates(
    config: RunConfig,
    source: AcquiredSource,
    transcript: Transcript,
    candidates: tuple[Candidate, ...],
    *,
    evaluator: CandidateEvaluator = evaluate_candidates,
) -> CandidateEvaluationArtifact:
    """Reuse or safely publish deterministic candidate evaluation results."""
    key = candidate_evaluation_cache_key(
        source_fingerprint=source.fingerprint,
        candidate_generator_version=CANDIDATE_GENERATOR_VERSION,
        evaluation_version=CANDIDATE_EVALUATION_VERSION,
        min_duration=config.min_duration,
        max_duration=config.max_duration,
        candidate_budget=config.candidate_budget,
    )
    transcription_key = transcription_cache_key(
        source_fingerprint=source.fingerprint,
        provider=TRANSCRIPTION_PROVIDER,
        provider_version=transcript.provider_version,
        model=config.model,
        language=config.language,
    )
    paths = prepare_workspace(config.output_dir, source, cache_key=transcription_key)
    if not config.force_recompute:
        try:
            cached = read_candidate_evaluation(paths, cache_key=key)
        except InvalidCandidateEvaluationArtifactError:
            logger.warning("stage=evaluate cache=invalid; recomputing")
        else:
            if cached is not None:
                logger.info("stage=evaluate cache=hit")
                return cached

    logger.info("stage=evaluate cache=miss")
    batch = evaluator(
        candidates,
        transcript,
        min_duration=config.min_duration,
        max_duration=config.max_duration,
        candidate_budget=config.candidate_budget,
    )
    artifact = CandidateEvaluationArtifact(
        source_fingerprint=source.fingerprint,
        candidate_generator_version=CANDIDATE_GENERATOR_VERSION,
        evaluation_version=CANDIDATE_EVALUATION_VERSION,
        min_duration=config.min_duration,
        max_duration=config.max_duration,
        candidate_budget=config.candidate_budget,
        evaluations=batch.evaluations,
    )
    write_candidate_evaluation(
        paths,
        artifact,
        cache_key=key,
        replace=paths.candidates.exists(),
    )
    return artifact


def run_pipeline(
    config: RunConfig,
    *,
    acquire: AcquireSource = acquire_local_source,
    probe: ProbeMedia = probe_media,
    transcriber: TranscriptionProvider | None = None,
    candidate_generator: CandidateGenerator = generate_candidates,
    candidate_evaluator: CandidateEvaluator = evaluate_candidates,
) -> NoReturn:
    """Run the implemented synchronous stages for one validated configuration.

    The pipeline deliberately stops after candidate evaluation until scoring and
    final artifact publication are available. Raising here prevents the CLI
    from reporting a completed run for a partial pipeline.
    """
    source_origin = _source_origin(config.source)
    logger.info("stage=acquire origin=%s", source_origin)
    source = acquire(config.source)
    logger.info("stage=acquire complete origin=%s", source_origin)
    logger.info("stage=probe origin=%s", source_origin)
    media = probe(source)
    logger.info(
        "stage=probe complete origin=%s duration=%.3f geometry=%dx%d",
        source_origin,
        media.duration,
        media.presentation_width,
        media.presentation_height,
    )
    transcript = load_or_transcribe(
        config,
        source,
        provider=transcriber if transcriber is not None else MultisubsAdapter(),
    )
    logger.info("stage=candidates")
    candidates = candidate_generator(
        transcript,
        source_fingerprint=source.fingerprint,
        min_duration=config.min_duration,
        max_duration=config.max_duration,
    )
    logger.info("stage=candidates complete count=%d", len(candidates))
    logger.info("stage=evaluate")
    evaluation = load_or_evaluate_candidates(
        config,
        source,
        transcript,
        candidates,
        evaluator=candidate_evaluator,
    )
    hard_failed = sum(item.hard_failed for item in evaluation.evaluations)
    logger.info(
        "stage=evaluate complete generated=%d hard_failed=%d shortlisted=%d",
        len(evaluation.evaluations),
        hard_failed,
        len(evaluation.shortlist_ids),
    )
    raise PipelineNotReadyError(
        "Pipeline stops after candidate generation and candidate evaluation "
        "until scoring and final artifact publication are implemented"
    )

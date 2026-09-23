"""Synchronous orchestration boundary for one multicuts run."""

import logging
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, Protocol
from urllib.parse import urlsplit

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.adapters.scoring import OpenAISemanticAdapter
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
from multicuts.candidates.ranking import NormalizedTextRedundancy, select_candidates
from multicuts.candidates.refinement import refine_selection
from multicuts.candidates.refinement_artifacts import (
    InvalidRefinementArtifactError,
    read_refinement,
    refinement_cache_key,
    write_refinement,
)
from multicuts.candidates.selection_artifacts import (
    InvalidSelectionArtifactError,
    read_selection,
    selection_cache_key,
    write_selection,
)
from multicuts.config import RunConfig
from multicuts.errors import (
    ArtifactError,
    RenderingError,
    ScoringError,
    TranscriptionError,
)
from multicuts.media import probe_media
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationArtifact,
    CandidateEvaluationBatch,
    CandidateScoringFailure,
    MediaInfo,
    RefinedSelection,
    RenderedClip,
    RenderRequest,
    ScoredCandidate,
    ScoreResult,
    ScoringBatch,
    ScoringProvenance,
    SelectionResult,
    SelectionStatus,
    Transcript,
)
from multicuts.rendering.artifacts import (
    InvalidRenderArtifactError,
    read_render,
    render_cache_key,
    render_paths,
    write_render,
)
from multicuts.rendering.cutter import FfmpegRenderer
from multicuts.scoring.artifacts import (
    InvalidScoringArtifactError,
    read_scores,
    scoring_cache_key,
    write_scores,
)
from multicuts.scoring.heuristic import score_heuristically
from multicuts.scoring.hybrid import compose_hybrid_score, score_with_heuristic_fallback
from multicuts.scoring.semantic import (
    SEMANTIC_PROMPT_VERSION,
    SemanticProviderError,
    SemanticScorer,
    build_semantic_request,
)
from multicuts.source import (
    acquire_source,
    prepare_acquisition_workspace,
)

AcquireSource = Callable[[str, Path], AcquiredSource]
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


class RenderProvider(Protocol):
    """The substitutable FFmpeg rendering boundary."""

    def version(self) -> str: ...

    def inspect(self, path: Path) -> MediaInfo: ...

    def render(self, request: RenderRequest) -> RenderedClip: ...


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


HeuristicScorer = Callable[[CandidateEvaluation], ScoreResult]


def _scoring_provenance(config: RunConfig) -> ScoringProvenance:
    if config.scorer == "heuristic":
        return ScoringProvenance("heuristic")
    return ScoringProvenance(
        mode="hybrid",
        provider=config.semantic_provider,
        model=config.semantic_model,
        prompt_version=SEMANTIC_PROMPT_VERSION,
        reasoning_effort=config.semantic_reasoning_effort,
        fallback=config.semantic_fallback,
    )


def _scoring_cache_key(
    config: RunConfig,
    *,
    evaluation_key: str,
    shortlist: tuple[CandidateEvaluation, ...],
) -> str:
    if config.scorer == "heuristic":
        return scoring_cache_key(
            evaluation_key=evaluation_key,
            shortlist=shortlist,
        )
    return scoring_cache_key(
        evaluation_key=evaluation_key,
        shortlist=shortlist,
        scorer="hybrid",
        semantic_provider=config.semantic_provider,
        semantic_model=config.semantic_model,
        semantic_prompt_version=SEMANTIC_PROMPT_VERSION,
        semantic_reasoning_effort=config.semantic_reasoning_effort,
        semantic_fallback=config.semantic_fallback,
    )


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


def load_or_score_candidates(
    config: RunConfig,
    source: AcquiredSource,
    transcript: Transcript,
    evaluation: CandidateEvaluationArtifact,
    *,
    scorer: HeuristicScorer = score_heuristically,
    semantic_scorer: SemanticScorer | None = None,
) -> ScoringBatch:
    """Reuse or publish scores for the bounded, eligible candidate shortlist."""
    evaluation_key = candidate_evaluation_cache_key(
        source_fingerprint=evaluation.source_fingerprint,
        candidate_generator_version=evaluation.candidate_generator_version,
        evaluation_version=evaluation.evaluation_version,
        min_duration=evaluation.min_duration,
        max_duration=evaluation.max_duration,
        candidate_budget=evaluation.candidate_budget,
    )
    shortlisted = tuple(
        sorted(
            (
                item
                for item in evaluation.evaluations
                if item.shortlist_rank is not None
            ),
            key=lambda item: item.shortlist_rank or 0,
        )
    )
    key = _scoring_cache_key(
        config, evaluation_key=evaluation_key, shortlist=shortlisted
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
            cached = read_scores(
                paths,
                cache_key=key,
                expected_ids=evaluation.shortlist_ids,
                expected_provenance=_scoring_provenance(config),
            )
        except InvalidScoringArtifactError:
            logger.warning("stage=score cache=invalid; recomputing")
        else:
            if cached is not None:
                logger.info(
                    "stage=score cache=hit count=%d failures=%d",
                    len(cached.scores),
                    len(cached.failures),
                )
                return cached

    logger.info("stage=score cache=miss count=%d", len(shortlisted))
    scores: list[ScoredCandidate] = []
    failures: list[CandidateScoringFailure] = []
    provider = semantic_scorer
    if config.scorer == "hybrid" and provider is None and shortlisted:
        provider = OpenAISemanticAdapter.from_environment(
            model=config.semantic_model,
            reasoning_effort=config.semantic_reasoning_effort,
        )
    for item in shortlisted:
        if config.scorer == "heuristic":
            try:
                result = scorer(item)
                if result.scorer != "heuristic":
                    raise ValueError("scorer returned incompatible provenance")
                scores.append(ScoredCandidate(item.candidate.candidate_id, result))
            except ValueError as exc:
                raise ScoringError(
                    "Heuristic scoring failed for a shortlisted candidate"
                ) from exc
            continue

        if provider is None:
            raise AssertionError("hybrid scoring provider was not initialized")
        try:
            judgment = provider.score(build_semantic_request(item, transcript))
            result = compose_hybrid_score(item, judgment)
            if (
                result.provider != config.semantic_provider
                or result.model != config.semantic_model
                or result.prompt_version != SEMANTIC_PROMPT_VERSION
            ):
                raise ValueError("semantic scorer returned incompatible provenance")
            scores.append(ScoredCandidate(item.candidate.candidate_id, result))
        except SemanticProviderError as exc:
            failure = CandidateScoringFailure(
                candidate_id=item.candidate.candidate_id,
                code=exc.code,
                warning=exc.warning,
                provider=config.semantic_provider,
                model=config.semantic_model,
                prompt_version=SEMANTIC_PROMPT_VERSION,
                retryable=exc.retryable,
            )
            failures.append(failure)
            logger.warning(
                "stage=score candidate_id=%s provider_failure=%s fallback=%s",
                item.candidate.candidate_id,
                exc.code,
                config.semantic_fallback,
            )
            if config.semantic_fallback == "heuristic":
                scores.append(
                    ScoredCandidate(
                        item.candidate.candidate_id,
                        score_with_heuristic_fallback(item, scorer=scorer),
                    )
                )
        except ValueError as exc:
            raise ScoringError(
                "Hybrid scoring returned incompatible candidate evidence"
            ) from exc
    completed = ScoringBatch(
        tuple(scores), tuple(failures), _scoring_provenance(config)
    )
    write_scores(paths, completed, cache_key=key, replace=paths.scores.exists())
    return completed


def load_or_select_candidates(
    config: RunConfig,
    source: AcquiredSource,
    transcript: Transcript,
    evaluation: CandidateEvaluationArtifact,
    scores: tuple[ScoredCandidate, ...],
) -> SelectionResult:
    """Reuse or publish deterministic top-K selection and suppression evidence."""
    evaluation_key = candidate_evaluation_cache_key(
        source_fingerprint=evaluation.source_fingerprint,
        candidate_generator_version=evaluation.candidate_generator_version,
        evaluation_version=evaluation.evaluation_version,
        min_duration=evaluation.min_duration,
        max_duration=evaluation.max_duration,
        candidate_budget=evaluation.candidate_budget,
    )
    shortlisted = tuple(
        sorted(
            (
                item
                for item in evaluation.evaluations
                if item.shortlist_rank is not None
            ),
            key=lambda item: item.shortlist_rank or 0,
        )
    )
    scoring_key = _scoring_cache_key(
        config, evaluation_key=evaluation_key, shortlist=shortlisted
    )
    score_ids = {item.candidate_id for item in scores}
    selection_evaluations = tuple(
        item
        for item in evaluation.evaluations
        if item.shortlist_rank is None or item.candidate.candidate_id in score_ids
    )
    key = selection_cache_key(
        scoring_key=scoring_key,
        scores=scores,
        top_k=config.clips,
        min_score=config.min_score,
        overlap_threshold=config.overlap_threshold,
        text_similarity_threshold=config.text_similarity_threshold,
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
            cached = read_selection(
                paths,
                cache_key=key,
                evaluations=selection_evaluations,
                scores=scores,
                overlap_threshold=config.overlap_threshold,
                text_similarity_threshold=config.text_similarity_threshold,
            )
        except InvalidSelectionArtifactError:
            logger.warning("stage=select cache=invalid; recomputing")
        else:
            if cached is not None:
                logger.info("stage=select cache=hit selected=%d", len(cached.selected))
                return cached

    logger.info("stage=select cache=miss candidates=%d", len(scores))
    selection = select_candidates(
        selection_evaluations,
        scores,
        top_k=config.clips,
        min_score=config.min_score,
        overlap_threshold=config.overlap_threshold,
        redundancy_policy=NormalizedTextRedundancy(config.text_similarity_threshold),
    )
    write_selection(
        paths,
        selection,
        cache_key=key,
        evaluations=selection_evaluations,
        scores=scores,
        overlap_threshold=config.overlap_threshold,
        text_similarity_threshold=config.text_similarity_threshold,
        replace=paths.selection.exists(),
    )
    return selection


def load_or_refine_selection(
    config: RunConfig,
    source: AcquiredSource,
    media: MediaInfo,
    transcript: Transcript,
    selection: SelectionResult,
) -> tuple[RefinedSelection, ...]:
    """Reuse or publish transcript-aware intervals for selected candidates."""
    if not selection.selected:
        logger.info("stage=refine skipped selected=0")
        return ()
    key = refinement_cache_key(
        selection,
        transcript,
        source_fingerprint=source.fingerprint,
        source_duration=media.duration,
        pre_roll=config.refinement_pre_roll,
        post_roll=config.refinement_post_roll,
        search_radius=config.refinement_search_radius,
        pause_threshold=config.refinement_pause_threshold,
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
            cached = read_refinement(
                paths,
                cache_key=key,
                selection=selection,
                source_duration=media.duration,
            )
        except InvalidRefinementArtifactError:
            logger.warning("stage=refine cache=invalid; recomputing")
        else:
            if cached is not None:
                logger.info("stage=refine cache=hit selected=%d", len(cached))
                return cached

    logger.info("stage=refine cache=miss selected=%d", len(selection.selected))
    refined = refine_selection(
        selection,
        transcript,
        media.duration,
        pre_roll=config.refinement_pre_roll,
        post_roll=config.refinement_post_roll,
        search_radius=config.refinement_search_radius,
        pause_threshold=config.refinement_pause_threshold,
    )
    write_refinement(
        paths,
        refined,
        cache_key=key,
        selection=selection,
        source_duration=media.duration,
        replace=paths.refinement.exists(),
    )
    return refined


def load_or_render_selection(
    config: RunConfig,
    source: AcquiredSource,
    media: MediaInfo,
    transcript: Transcript,
    refined: tuple[RefinedSelection, ...],
    *,
    renderer: RenderProvider | None = None,
) -> tuple[RenderedClip, ...]:
    """Render safe refined intervals and reuse only validated raw clips."""
    safe = tuple(item for item in refined if not item.requires_rescore)
    if len(safe) != len(refined):
        logger.warning(
            "stage=render skipped_requires_rescore=%d",
            len(refined) - len(safe),
        )
    if not safe:
        logger.info("stage=render skipped eligible=0")
        return ()

    backend = renderer if renderer is not None else FfmpegRenderer()
    version = backend.version()
    transcription_key = transcription_cache_key(
        source_fingerprint=source.fingerprint,
        provider=TRANSCRIPTION_PROVIDER,
        provider_version=transcript.provider_version,
        model=config.model,
        language=config.language,
    )
    paths = prepare_workspace(config.output_dir, source, cache_key=transcription_key)
    rendered: list[RenderedClip] = []
    for item in safe:
        key = render_cache_key(
            item,
            media,
            source_fingerprint=source.fingerprint,
            aspect_ratio=config.aspect_ratio,
            target_width=config.vertical_width,
            target_height=config.vertical_height,
            renderer_version=version,
        )
        output_path, metadata_path = render_paths(paths, item, key)
        temporary_path = paths.work / f"render-{secrets.token_hex(16)}.mp4"
        request = RenderRequest(
            source=source,
            media=media,
            refined=item,
            aspect_ratio=config.aspect_ratio,
            target_width=config.vertical_width,
            target_height=config.vertical_height,
            temporary_path=temporary_path,
            output_path=output_path,
            renderer_version=version,
            cache_key=key,
        )
        if not config.force_recompute:
            try:
                cached = read_render(request, metadata_path, inspect=backend.inspect)
            except InvalidRenderArtifactError as exc:
                raise ArtifactError(
                    "Existing raw render is invalid; remove its artifact to retry"
                ) from exc
            if cached is not None:
                logger.info("stage=render cache=hit rank=%d", item.rank)
                rendered.append(cached)
                continue
        if output_path.exists() or output_path.is_symlink():
            raise RenderingError(
                "Raw clip already exists; refusing to overwrite completed media"
            )
        logger.info("stage=render cache=miss rank=%d", item.rank)
        result = backend.render(request)
        try:
            write_render(paths, request, result, metadata_path)
        except Exception:
            # The raw clip was just published, but without valid metadata it is
            # incomplete as a reusable stage artifact.
            if result.path == output_path:
                output_path.unlink(missing_ok=True)
            raise
        rendered.append(result)
    logger.info("stage=render complete count=%d", len(rendered))
    return tuple(rendered)


def run_pipeline(
    config: RunConfig,
    *,
    acquire: AcquireSource = acquire_source,
    probe: ProbeMedia = probe_media,
    transcriber: TranscriptionProvider | None = None,
    candidate_generator: CandidateGenerator = generate_candidates,
    candidate_evaluator: CandidateEvaluator = evaluate_candidates,
    heuristic_scorer: HeuristicScorer = score_heuristically,
    semantic_scorer: SemanticScorer | None = None,
    renderer: RenderProvider | None = None,
) -> NoReturn:
    """Run the implemented synchronous stages for one validated configuration.

    The pipeline deliberately stops after raw rendering until subtitles
    and final artifact publication are available. Raising here prevents the
    CLI from reporting a completed run for a partial pipeline.
    """
    source_origin = _source_origin(config.source)
    logger.info("stage=acquire origin=%s", source_origin)
    workspace = prepare_acquisition_workspace(config.output_dir)
    source = acquire(config.source, workspace)
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
    scoring = load_or_score_candidates(
        config,
        source,
        transcript,
        evaluation,
        scorer=heuristic_scorer,
        semantic_scorer=semantic_scorer,
    )
    scores = scoring.scores
    logger.info(
        "stage=score complete count=%d failures=%d",
        len(scores),
        len(scoring.failures),
    )
    selection = load_or_select_candidates(
        config,
        source,
        transcript,
        evaluation,
        scores,
    )
    suppressed = sum(
        decision.status
        in (SelectionStatus.TEMPORAL_OVERLAP, SelectionStatus.TEXT_REDUNDANCY)
        for decision in selection.decisions
    )
    eligible = sum(
        decision.status is not SelectionStatus.BELOW_THRESHOLD
        for decision in selection.decisions
    )
    logger.info(
        "stage=select complete eligible=%d suppressed=%d selected=%d",
        eligible,
        suppressed,
        len(selection.selected),
    )
    for selected in selection.selected:
        logger.info(
            "stage=select rank=%d candidate_id=%s score=%.2f",
            selected.rank,
            selected.candidate_id,
            selected.result.score,
        )
    refined = load_or_refine_selection(config, source, media, transcript, selection)
    requires_rescore = sum(item.requires_rescore for item in refined)
    logger.info(
        "stage=refine complete selected=%d requires_rescore=%d",
        len(refined),
        requires_rescore,
    )
    for item in refined:
        logger.info(
            "stage=refine rank=%d candidate_id=%s reasons=%s requires_rescore=%s",
            item.selected.rank,
            item.selected.candidate_id,
            ",".join(reason.value for reason in item.reasons),
            item.requires_rescore,
        )
    load_or_render_selection(
        config,
        source,
        media,
        transcript,
        refined,
        renderer=renderer,
    )
    raise PipelineNotReadyError(
        "Pipeline stops after raw clip rendering until subtitles and final "
        "artifact publication are implemented"
    )

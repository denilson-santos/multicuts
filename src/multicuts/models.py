"""Project-owned values shared across the synchronous pipeline."""

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from pathlib import Path


def _validate_interval(start: float | None, end: float | None) -> None:
    if (start is None) != (end is None):
        raise ValueError("start and end must both be present or absent")
    if start is not None and end is not None:
        if not isfinite(start) or not isfinite(end) or start < 0 or end <= start:
            raise ValueError("timed intervals must have finite, ordered seconds")


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    """A source available locally with identity and safe origin metadata.

    ``provider_id``, ``title``, and ``original_url`` are populated only for
    remote providers.  Keeping these values optional lets local acquisition
    retain its existing semantics without fabricating remote metadata.
    """

    local_path: Path
    fingerprint: str
    source_kind: str = "local"
    provider_id: str | None = None
    title: str | None = None
    original_url: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.local_path, Path):
            raise ValueError("source local path must be a Path")
        if not isinstance(self.fingerprint, str) or not self.fingerprint.strip():
            raise ValueError("source fingerprint must not be empty")
        if self.source_kind not in ("local", "youtube"):
            raise ValueError("source kind must be 'local' or 'youtube'")
        for field_name in ("provider_id", "title", "original_url"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"source {field_name} must be non-empty when present")
        if self.source_kind == "local" and (
            self.provider_id is not None
            or self.title is not None
            or self.original_url is not None
        ):
            raise ValueError("local sources must not carry remote metadata")
        if self.source_kind == "youtube" and (
            self.provider_id is None or self.title is None or self.original_url is None
        ):
            raise ValueError("YouTube sources require ID, title, and original URL")

    @property
    def source_id(self) -> str | None:
        """Return the provider ID under the source-oriented metadata name."""
        return self.provider_id

    @property
    def source_title(self) -> str | None:
        """Return the normalized title under an explicit metadata name."""
        return self.title


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Usable streams and geometry after rotation and aspect-ratio correction."""

    duration: float
    coded_width: int
    coded_height: int
    presentation_width: int
    presentation_height: int
    video_stream_index: int
    audio_stream_index: int | None
    rotation_degrees: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.duration) or self.duration <= 0:
            raise ValueError("media duration must be finite and positive")
        if (
            min(
                self.coded_width,
                self.coded_height,
                self.presentation_width,
                self.presentation_height,
            )
            <= 0
        ):
            raise ValueError("media dimensions must be positive")
        if self.video_stream_index < 0 or (
            self.audio_stream_index is not None and self.audio_stream_index < 0
        ):
            raise ValueError("stream indexes must be non-negative")
        if not isfinite(self.rotation_degrees):
            raise ValueError("media rotation must be finite")

    @property
    def has_audio(self) -> bool:
        """Whether probing selected a usable audio stream."""
        return self.audio_stream_index is not None


@dataclass(frozen=True, slots=True)
class Word:
    """A transcript word, with missing timing represented explicitly."""

    text: str
    start: float | None
    end: float | None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("word text must not be empty")
        _validate_interval(self.start, self.end)
        if self.confidence is not None and not isfinite(self.confidence):
            raise ValueError("word confidence must be finite")


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A text segment with provider-supplied timing when available."""

    text: str
    start: float | None
    end: float | None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("segment text must not be empty")
        _validate_interval(self.start, self.end)


@dataclass(frozen=True, slots=True)
class Transcript:
    """A normalized transcript independent of the provider's JSON schema."""

    language_requested: str | None
    language_detected: str | None
    duration: float
    text: str
    segments: tuple[TranscriptSegment, ...]
    words: tuple[Word, ...]
    provider: str
    provider_version: str

    def __post_init__(self) -> None:
        if not isfinite(self.duration) or self.duration <= 0:
            raise ValueError("transcript duration must be finite and positive")
        if not self.text.strip():
            raise ValueError("transcript text must not be empty")
        if not self.provider or not self.provider_version:
            raise ValueError("transcript provider and version must not be empty")
        if not isinstance(self.segments, tuple) or not isinstance(self.words, tuple):
            raise ValueError("transcript segments and words must be tuples")


@dataclass(frozen=True, slots=True)
class SemanticUnit:
    """One timed transcript unit bounded by observed source timestamps."""

    text: str
    start: float
    end: float

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("semantic unit text must not be empty")
        _validate_interval(self.start, self.end)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A contiguous semantic-unit window proposed for later evaluation."""

    candidate_id: str
    start: float
    end: float
    text: str
    unit_indexes: tuple[int, ...]
    generator_version: str

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate ID must not be empty")
        if not self.text.strip():
            raise ValueError("candidate text must not be empty")
        if not self.generator_version.strip():
            raise ValueError("candidate generator version must not be empty")
        _validate_interval(self.start, self.end)
        if not isinstance(self.unit_indexes, tuple) or not self.unit_indexes:
            raise ValueError("candidate unit indexes must be a nonempty tuple")
        if any(type(index) is not int or index < 0 for index in self.unit_indexes):
            raise ValueError("candidate unit indexes must be non-negative integers")
        expected = tuple(
            range(self.unit_indexes[0], self.unit_indexes[0] + len(self.unit_indexes))
        )
        if self.unit_indexes != expected:
            raise ValueError("candidate unit indexes must be contiguous")


class ChecklistOutcome(str, Enum):
    """The closed set of outcomes emitted by a candidate checklist rule."""

    PASS = "PASS"
    SOFT_FAIL = "SOFT_FAIL"
    HARD_FAIL = "HARD_FAIL"
    UNKNOWN = "UNKNOWN"


# The shorter name is useful at call sites that refer to a rule rather than a
# checklist, while keeping one serialized enum and one validation contract.
RuleOutcome = ChecklistOutcome
ChecklistStatus = ChecklistOutcome
FilterOutcome = ChecklistOutcome


@dataclass(frozen=True, slots=True)
class CandidateFeatures:
    """Deterministic evidence computed from one candidate and transcript."""

    duration: float
    word_count: int
    timed_word_count: int
    speech_duration: float | None = None
    words_per_second: float | None = None
    speech_ratio: float | None = None
    pause_duration: float | None = None
    pause_ratio: float | None = None
    max_pause: float | None = None
    opening_quality: float | None = None
    ending_quality: float | None = None
    standalone_context: float | None = None
    payoff: float | None = None
    filler_ratio: float | None = None
    transcript_confidence: float | None = None
    timing_coverage: float | None = None
    feature_version: str = "1"

    def __post_init__(self) -> None:
        if (
            isinstance(self.duration, bool)
            or not isinstance(self.duration, (int, float))
            or not isfinite(self.duration)
            or self.duration <= 0
        ):
            raise ValueError("feature duration must be finite and positive")
        for field_name in ("word_count", "timed_word_count"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.speech_duration is not None and (
            isinstance(self.speech_duration, bool)
            or not isinstance(self.speech_duration, (int, float))
            or not isfinite(self.speech_duration)
            or self.speech_duration < 0
            or self.speech_duration > self.duration
        ):
            raise ValueError("speech duration must be within the candidate duration")
        for field_name in ("words_per_second", "max_pause"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{field_name} must be finite and non-negative")
        if self.pause_duration is not None and (
            isinstance(self.pause_duration, bool)
            or not isinstance(self.pause_duration, (int, float))
            or not isfinite(self.pause_duration)
            or self.pause_duration < 0
        ):
            raise ValueError("pause duration must be finite and non-negative")
        if self.pause_duration is not None and self.pause_duration > self.duration:
            raise ValueError("pause duration must not exceed candidate duration")
        for field_name in (
            "speech_ratio",
            "pause_ratio",
            "opening_quality",
            "ending_quality",
            "standalone_context",
            "payoff",
            "filler_ratio",
            "transcript_confidence",
            "timing_coverage",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or not 0.0 <= value <= 1.0
            ):
                raise ValueError(f"{field_name} must be a finite ratio from 0 to 1")
        if (
            not isinstance(self.feature_version, str)
            or not self.feature_version.strip()
        ):
            raise ValueError("feature version must not be empty")

    @property
    def text_word_count(self) -> int:
        """Backward-compatible descriptive name for the candidate word count."""
        return self.word_count

    @property
    def speech_word_count(self) -> int:
        """Return the number of words with real source timing."""
        return self.timed_word_count

    @property
    def confidence(self) -> float | None:
        """Return the aggregate transcript confidence, when fully observed."""
        return self.transcript_confidence

    @property
    def speech_density(self) -> float | None:
        """Return words per second under the descriptive density name."""
        return self.words_per_second

    @property
    def pause_evidence(self) -> float | None:
        """Return the transcript-gap pause proxy, when available."""
        return self.pause_ratio


@dataclass(frozen=True, slots=True)
class ChecklistResult:
    """One explainable result for one deterministic candidate rule."""

    rule_code: str
    outcome: ChecklistOutcome
    reason: str | None = None
    evidence: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rule_code, str) or not self.rule_code.strip():
            raise ValueError("checklist rule code must not be empty")
        if isinstance(self.outcome, str):
            try:
                object.__setattr__(self, "outcome", ChecklistOutcome(self.outcome))
            except ValueError as exc:
                raise ValueError("checklist outcome is invalid") from exc
        elif not isinstance(self.outcome, ChecklistOutcome):
            raise ValueError("checklist outcome is invalid")
        for field_name in ("reason", "evidence"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(
                    f"checklist {field_name} must be non-empty when present"
                )

    @property
    def code(self) -> str:
        """Return the stable rule code under a concise name."""
        return self.rule_code

    @property
    def status(self) -> ChecklistOutcome:
        """Return the closed rule outcome under a status-oriented name."""
        return self.outcome


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Candidate evidence and every checklist result retained for traceability."""

    candidate: Candidate
    features: CandidateFeatures
    checklist: tuple[ChecklistResult, ...]
    shortlist_rank: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.checklist, tuple) or not self.checklist:
            raise ValueError("candidate checklist must be a non-empty tuple")
        rule_codes = tuple(result.rule_code for result in self.checklist)
        if len(set(rule_codes)) != len(rule_codes):
            raise ValueError("candidate checklist rule codes must be unique")
        if self.shortlist_rank is not None and (
            type(self.shortlist_rank) is not int or self.shortlist_rank <= 0
        ):
            raise ValueError("shortlist rank must be a positive integer when present")

    @property
    def hard_failed(self) -> bool:
        """Whether any rule makes this candidate ineligible for scoring."""
        return any(
            result.outcome is ChecklistOutcome.HARD_FAIL for result in self.checklist
        )

    @property
    def eligible_for_scoring(self) -> bool:
        """Whether the candidate survived hard filtering."""
        return not self.hard_failed

    @property
    def checklist_results(self) -> tuple[ChecklistResult, ...]:
        """Return all rule results under the explicit metadata name."""
        return self.checklist


@dataclass(frozen=True, slots=True)
class CandidateEvaluationBatch:
    """All evaluations plus the deterministic bounded scoring shortlist."""

    evaluations: tuple[CandidateEvaluation, ...]
    shortlist: tuple[CandidateEvaluation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.evaluations, tuple) or not isinstance(
            self.shortlist, tuple
        ):
            raise ValueError("candidate evaluations and shortlist must be tuples")
        evaluation_ids = {item.candidate.candidate_id for item in self.evaluations}
        shortlist_ids = tuple(item.candidate.candidate_id for item in self.shortlist)
        if any(
            item.candidate.candidate_id not in evaluation_ids for item in self.shortlist
        ):
            raise ValueError("shortlist candidates must be part of evaluations")
        if len(set(shortlist_ids)) != len(shortlist_ids):
            raise ValueError("shortlist candidates must be unique")
        if any(item.hard_failed for item in self.shortlist):
            raise ValueError("hard-failed candidates must not reach the shortlist")

    @property
    def shortlisted(self) -> tuple[CandidateEvaluation, ...]:
        """Return the bounded evaluations sent to downstream scoring."""
        return self.shortlist


@dataclass(frozen=True, slots=True)
class CandidateEvaluationArtifact:
    """Versioned project-owned payload persisted for candidate evaluation."""

    source_fingerprint: str
    candidate_generator_version: str
    evaluation_version: str
    min_duration: float
    max_duration: float
    candidate_budget: int
    evaluations: tuple[CandidateEvaluation, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "source_fingerprint",
            "candidate_generator_version",
            "evaluation_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if (
            isinstance(self.min_duration, bool)
            or not isinstance(self.min_duration, (int, float))
            or isinstance(self.max_duration, bool)
            or not isinstance(self.max_duration, (int, float))
            or not isfinite(self.min_duration)
            or not isfinite(self.max_duration)
            or self.min_duration <= 0
            or self.max_duration < self.min_duration
        ):
            raise ValueError("candidate evaluation duration limits are invalid")
        if type(self.candidate_budget) is not int or self.candidate_budget <= 0:
            raise ValueError("candidate evaluation budget must be positive")
        if not isinstance(self.evaluations, tuple):
            raise ValueError("candidate evaluations must be a tuple")
        candidate_ids = tuple(
            evaluation.candidate.candidate_id for evaluation in self.evaluations
        )
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate evaluation IDs must be unique")
        if any(
            evaluation.candidate.generator_version != self.candidate_generator_version
            for evaluation in self.evaluations
        ):
            raise ValueError(
                "candidate generator versions must match the artifact provenance"
            )
        ranks = tuple(
            evaluation.shortlist_rank
            for evaluation in self.evaluations
            if evaluation.shortlist_rank is not None
        )
        if len(ranks) > self.candidate_budget or set(ranks) != set(
            range(1, len(ranks) + 1)
        ):
            raise ValueError("candidate shortlist ranks must be bounded and contiguous")

    @property
    def shortlist_ids(self) -> tuple[str, ...]:
        """Return shortlisted IDs in deterministic rank order."""
        ranked = (
            evaluation
            for evaluation in self.evaluations
            if evaluation.shortlist_rank is not None
        )
        return tuple(
            evaluation.candidate.candidate_id
            for evaluation in sorted(ranked, key=lambda item: item.shortlist_rank or 0)
        )


SCORE_DIMENSIONS = (
    "hook",
    "standalone_context",
    "payoff",
    "clarity",
    "emotion_surprise",
    "quotability",
    "information_density",
)


@dataclass(frozen=True, slots=True)
class ScoreDimension:
    name: str
    value: float

    def __post_init__(self) -> None:
        if self.name not in SCORE_DIMENSIONS:
            raise ValueError("unknown score dimension")
        if (
            isinstance(self.value, bool)
            or not isinstance(self.value, (int, float))
            or not isfinite(self.value)
            or not 0 <= self.value <= 100
        ):
            raise ValueError("dimension value must be finite and within 0..100")


@dataclass(frozen=True, slots=True)
class ScorePenalty:
    code: str
    points: float
    reason: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, str)
            or not self.code.strip()
            or not isinstance(self.reason, str)
            or not self.reason.strip()
        ):
            raise ValueError("penalty code and reason must not be empty")
        if (
            isinstance(self.points, bool)
            or not isinstance(self.points, (int, float))
            or not isfinite(self.points)
            or self.points < 0
        ):
            raise ValueError("penalty points must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Provider-independent, auditable score for one candidate."""

    score: float
    base_score: float
    confidence: float
    dimensions: tuple[ScoreDimension, ...]
    penalties: tuple[ScorePenalty, ...]
    reason: str
    scoring_schema_version: int
    scoring_algorithm_version: str
    scorer: str
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None

    def __post_init__(self) -> None:
        for name in ("score", "base_score"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or not 0 <= value <= 100
            ):
                raise ValueError(f"{name} must be finite and within 0..100")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("score confidence must be finite and within 0..1")
        if (
            not isinstance(self.dimensions, tuple)
            or any(not isinstance(item, ScoreDimension) for item in self.dimensions)
            or tuple(item.name for item in self.dimensions) != SCORE_DIMENSIONS
        ):
            raise ValueError("score dimensions must contain the closed ordered set")
        if not isinstance(self.penalties, tuple) or any(
            not isinstance(item, ScorePenalty) for item in self.penalties
        ):
            raise ValueError("score penalties must be structured values")
        if len({item.code for item in self.penalties}) != len(self.penalties):
            raise ValueError("score penalties must be unique")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("score reason must not be empty")
        if (
            type(self.scoring_schema_version) is not int
            or self.scoring_schema_version <= 0
        ):
            raise ValueError("scoring schema version must be positive")
        if (
            not isinstance(self.scoring_algorithm_version, str)
            or not self.scoring_algorithm_version.strip()
        ):
            raise ValueError("scoring algorithm version must not be empty")
        for name in ("provider", "model", "prompt_version"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be non-empty when present")
        if self.scorer == "heuristic":
            if any(
                value is not None
                for value in (self.provider, self.model, self.prompt_version)
            ):
                raise ValueError("heuristic scores cannot claim semantic provenance")
        elif self.scorer == "heuristic-fallback":
            if any(
                value is not None
                for value in (self.provider, self.model, self.prompt_version)
            ):
                raise ValueError("fallback scores cannot claim semantic provenance")
        elif self.scorer == "hybrid":
            if any(
                value is None
                for value in (self.provider, self.model, self.prompt_version)
            ):
                raise ValueError("hybrid scores require semantic provenance")
        elif not isinstance(self.scorer, str) or not self.scorer.strip():
            raise ValueError("scorer must not be empty")
        else:
            raise ValueError("scorer is unsupported")


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    candidate_id: str
    result: ScoreResult

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("scored candidate ID must not be empty")
        if not isinstance(self.result, ScoreResult):
            raise ValueError("scored candidate result must be a score")


@dataclass(frozen=True, slots=True)
class SemanticScoringRequest:
    """Minimum project-owned text and evidence sent to a semantic scorer."""

    candidate_id: str
    candidate_text: str
    context_before: str
    context_after: str
    features: CandidateFeatures

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("semantic request candidate ID must not be empty")
        if not isinstance(self.candidate_text, str) or not self.candidate_text.strip():
            raise ValueError("semantic request candidate text must not be empty")
        for field_name in ("context_before", "context_after"):
            if not isinstance(getattr(self, field_name), str):
                raise ValueError(f"semantic request {field_name} must be text")
        if not isinstance(self.features, CandidateFeatures):
            raise ValueError("semantic request features must be structured")


@dataclass(frozen=True, slots=True)
class SemanticJudgment:
    """Validated semantic dimensions returned through a provider adapter."""

    dimensions: tuple[ScoreDimension, ...]
    confidence: float
    reason: str
    provider: str
    model: str
    prompt_version: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.dimensions, tuple)
            or any(not isinstance(item, ScoreDimension) for item in self.dimensions)
            or tuple(item.name for item in self.dimensions) != SCORE_DIMENSIONS
        ):
            raise ValueError("semantic dimensions must contain the closed ordered set")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("semantic confidence must be finite and within 0..1")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("semantic reason must not be empty")
        for field_name in ("provider", "model", "prompt_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"semantic {field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class CandidateScoringFailure:
    """Safe candidate-level provider failure retained for audit and fallback."""

    candidate_id: str
    code: str
    warning: str
    provider: str
    model: str
    prompt_version: str
    retryable: bool

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "code",
            "warning",
            "provider",
            "model",
            "prompt_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"scoring failure {field_name} must not be empty")
        if type(self.retryable) is not bool:
            raise ValueError("scoring failure retryable flag must be boolean")


@dataclass(frozen=True, slots=True)
class ScoringProvenance:
    """Configured scoring route persisted independently from provider secrets."""

    mode: str
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    reasoning_effort: str | None = None
    fallback: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("heuristic", "hybrid"):
            raise ValueError("scoring provenance mode is unsupported")
        semantic_values = (
            self.provider,
            self.model,
            self.prompt_version,
            self.reasoning_effort,
            self.fallback,
        )
        if self.mode == "heuristic" and any(
            value is not None for value in semantic_values
        ):
            raise ValueError("heuristic provenance cannot claim semantic settings")
        if self.mode == "hybrid" and any(
            not isinstance(value, str) or not value.strip() for value in semantic_values
        ):
            raise ValueError("hybrid provenance requires semantic settings")
        if self.fallback is not None and self.fallback not in ("heuristic", "none"):
            raise ValueError("scoring provenance fallback is unsupported")


@dataclass(frozen=True, slots=True)
class ScoringBatch:
    """Successful candidate scores and explicit provider failures for one stage."""

    scores: tuple[ScoredCandidate, ...]
    failures: tuple[CandidateScoringFailure, ...] = ()
    provenance: ScoringProvenance = ScoringProvenance("heuristic")

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scores, tuple)
            or not isinstance(self.failures, tuple)
            or not isinstance(self.provenance, ScoringProvenance)
        ):
            raise ValueError("scoring batch values must be tuples")
        score_ids = tuple(item.candidate_id for item in self.scores)
        failure_ids = tuple(item.candidate_id for item in self.failures)
        if len(set(score_ids)) != len(score_ids):
            raise ValueError("scored candidate IDs must be unique")
        if len(set(failure_ids)) != len(failure_ids):
            raise ValueError("scoring failure IDs must be unique")
        if self.provenance.mode == "heuristic":
            if self.failures or any(
                item.result.scorer != "heuristic" for item in self.scores
            ):
                raise ValueError("heuristic batch cannot contain semantic outcomes")
            return
        failure_id_set = set(failure_ids)
        fallback_id_set: set[str] = set()
        for item in self.scores:
            if item.result.scorer == "hybrid":
                if (
                    item.result.provider != self.provenance.provider
                    or item.result.model != self.provenance.model
                    or item.result.prompt_version != self.provenance.prompt_version
                ):
                    raise ValueError("hybrid score provenance must match the batch")
            elif item.result.scorer == "heuristic-fallback":
                fallback_id_set.add(item.candidate_id)
                if (
                    self.provenance.fallback != "heuristic"
                    or item.candidate_id not in failure_id_set
                ):
                    raise ValueError("fallback scores require a matching failure")
            else:
                raise ValueError("hybrid batch contains an incompatible score")
        if any(
            failure.provider != self.provenance.provider
            or failure.model != self.provenance.model
            or failure.prompt_version != self.provenance.prompt_version
            for failure in self.failures
        ):
            raise ValueError("provider failures must match the batch provenance")
        scores_by_id = {item.candidate_id: item for item in self.scores}
        if any(
            failure.candidate_id in scores_by_id
            and scores_by_id[failure.candidate_id].result.scorer != "heuristic-fallback"
            for failure in self.failures
        ):
            raise ValueError(
                "provider failures may overlap only heuristic fallback scores"
            )
        if self.provenance.fallback == "heuristic" and (
            fallback_id_set != failure_id_set
        ):
            raise ValueError("each provider failure requires one heuristic fallback")


class SelectionStatus(str, Enum):
    """The closed set of outcomes for one ranked candidate."""

    SELECTED = "selected"
    BELOW_THRESHOLD = "below_threshold"
    TEMPORAL_OVERLAP = "temporal_overlap"
    TEXT_REDUNDANCY = "text_redundancy"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    """Explain why one scored candidate was selected or omitted."""

    candidate_id: str
    status: SelectionStatus
    reason_code: str
    rank: int | None = None
    suppressed_by: str | None = None
    evidence: float | None = None

    def __post_init__(self) -> None:
        for field_name in ("candidate_id", "reason_code"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"selection {field_name} must not be empty")
        if isinstance(self.status, str):
            try:
                object.__setattr__(self, "status", SelectionStatus(self.status))
            except ValueError as exc:
                raise ValueError("selection status is invalid") from exc
        elif not isinstance(self.status, SelectionStatus):
            raise ValueError("selection status is invalid")
        if self.rank is not None and (type(self.rank) is not int or self.rank <= 0):
            raise ValueError("selection rank must be a positive integer")
        if self.suppressed_by is not None and (
            not isinstance(self.suppressed_by, str) or not self.suppressed_by.strip()
        ):
            raise ValueError("selection suppressor must be non-empty when present")
        if self.evidence is not None and (
            isinstance(self.evidence, bool)
            or not isinstance(self.evidence, (int, float))
            or not isfinite(self.evidence)
            or not 0.0 <= self.evidence <= 1.0
        ):
            raise ValueError("selection evidence must be a finite ratio from 0 to 1")
        if self.status is SelectionStatus.SELECTED:
            if self.rank is None or self.suppressed_by is not None:
                raise ValueError("selected decisions require rank and no suppressor")
        elif self.rank is not None:
            raise ValueError("omitted decisions cannot have a rank")
        if self.status in (
            SelectionStatus.TEMPORAL_OVERLAP,
            SelectionStatus.TEXT_REDUNDANCY,
        ):
            if self.suppressed_by is None or self.evidence is None:
                raise ValueError("redundancy decisions require suppressor and evidence")
        elif self.suppressed_by is not None:
            raise ValueError("non-redundancy decisions cannot have a suppressor")


@dataclass(frozen=True, slots=True)
class SelectedCandidate:
    """One ranked candidate with its original evidence and scored interval."""

    evaluation: CandidateEvaluation
    scored: ScoredCandidate
    rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.scored, ScoredCandidate):
            raise ValueError("selected candidate score link is invalid")
        if self.evaluation.candidate.candidate_id != self.scored.candidate_id:
            raise ValueError("selected candidate identity is inconsistent")
        if self.evaluation.hard_failed or self.evaluation.shortlist_rank is None:
            raise ValueError("selected candidates must come from the scoring shortlist")
        if type(self.rank) is not int or self.rank <= 0:
            raise ValueError("selected candidate rank must be positive")

    @property
    def candidate_id(self) -> str:
        return self.evaluation.candidate.candidate_id

    @property
    def result(self) -> ScoreResult:
        return self.scored.result

    @property
    def start(self) -> float:
        return self.evaluation.candidate.start

    @property
    def end(self) -> float:
        return self.evaluation.candidate.end


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Selected candidates and a decision for every scored candidate."""

    selected: tuple[SelectedCandidate, ...]
    decisions: tuple[SelectionDecision, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.selected, tuple) or not isinstance(
            self.decisions, tuple
        ):
            raise ValueError("selection values must be tuples")
        selected_ids = tuple(item.candidate_id for item in self.selected)
        decision_ids = tuple(item.candidate_id for item in self.decisions)
        if len(set(selected_ids)) != len(selected_ids):
            raise ValueError("selected candidate IDs must be unique")
        if len(set(decision_ids)) != len(decision_ids):
            raise ValueError("selection decision IDs must be unique")
        if tuple(item.rank for item in self.selected) != tuple(
            range(1, len(self.selected) + 1)
        ):
            raise ValueError("selected candidate ranks must be contiguous")
        selected_decisions = tuple(
            item for item in self.decisions if item.status is SelectionStatus.SELECTED
        )
        if tuple(
            item.candidate_id for item in selected_decisions
        ) != selected_ids or tuple(item.rank for item in selected_decisions) != tuple(
            item.rank for item in self.selected
        ):
            raise ValueError("selected candidates and decisions must agree")


class RefinementReason(str, Enum):
    """Closed reason codes describing one boundary-refinement result."""

    UNCHANGED = "unchanged"
    WORD_ALIGNED = "word_aligned"
    SEGMENT_ALIGNED = "segment_aligned"
    PAUSE_ALIGNED = "pause_aligned"
    PADDED = "padded"
    CLAMPED = "clamped"
    REJECTED = "rejected"
    REQUIRES_RESCORE = "requires_rescore"


@dataclass(frozen=True, slots=True)
class RefinedSelection:
    """A selected candidate with a source-bounded interval for rendering.

    The selected value remains the sole owner of candidate, checklist, score,
    rank, and provider provenance. The render interval is kept separately so a
    padded cut cannot be mistaken for the interval that was scored.
    Pre-roll and post-roll are the padding actually present after source
    duration clamping.
    """

    selected: SelectedCandidate
    render_start: float
    render_end: float
    pre_roll: float
    post_roll: float
    reasons: tuple[RefinementReason, ...]
    version: str
    source_duration: float
    requires_rescore: bool

    def __post_init__(self) -> None:
        if not isinstance(self.selected, SelectedCandidate):
            raise ValueError("refined selection must retain a selected candidate")
        if (
            isinstance(self.source_duration, bool)
            or not isinstance(self.source_duration, (int, float))
            or not isfinite(self.source_duration)
            or self.source_duration <= 0
        ):
            raise ValueError("refined source duration must be finite and positive")
        if self.selected.end > self.source_duration:
            raise ValueError("selected candidate must fit within source duration")
        for field_name in ("render_start", "render_end", "pre_roll", "post_roll"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
                raise ValueError(f"refined {field_name} must be finite")
        if (
            self.render_start < 0
            or self.render_end <= self.render_start
            or self.render_end > self.source_duration
        ):
            raise ValueError("refined render interval is outside source duration")
        if self.pre_roll < 0 or self.post_roll < 0:
            raise ValueError("refined padding must be non-negative")
        if self.render_start + self.pre_roll >= self.render_end - self.post_roll:
            raise ValueError("refined padding leaves no semantic interval")
        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise ValueError("refinement reasons must be a non-empty tuple")
        normalized_reasons: list[RefinementReason] = []
        for reason in self.reasons:
            if isinstance(reason, str):
                try:
                    reason = RefinementReason(reason)
                except ValueError as exc:
                    raise ValueError("refinement reason is invalid") from exc
            elif not isinstance(reason, RefinementReason):
                raise ValueError("refinement reason is invalid")
            normalized_reasons.append(reason)
        if len(set(normalized_reasons)) != len(normalized_reasons):
            raise ValueError("refinement reasons must be unique")
        object.__setattr__(self, "reasons", tuple(normalized_reasons))
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("refinement version must not be empty")
        if type(self.requires_rescore) is not bool:
            raise ValueError("refinement rescore flag must be boolean")
        if self.requires_rescore != (RefinementReason.REQUIRES_RESCORE in self.reasons):
            raise ValueError("refinement rescore flag and reason must agree")

    @property
    def candidate_id(self) -> str:
        """Return the retained candidate identity."""
        return self.selected.candidate_id

    @property
    def rank(self) -> int:
        """Return the retained selection rank."""
        return self.selected.rank

    @property
    def scored_start(self) -> float:
        """Return the original start timestamp used for scoring."""
        return self.selected.start

    @property
    def scored_end(self) -> float:
        """Return the original end timestamp used for scoring."""
        return self.selected.end

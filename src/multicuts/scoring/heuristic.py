"""Versioned deterministic score for shortlisted candidates."""

from math import isclose

from multicuts.candidates.filters import (
    MAX_FILLER_RATIO,
    MAX_PAUSE_RATIO,
    PREFERRED_DURATION_MAX,
    PREFERRED_DURATION_MIN,
)
from multicuts.models import (
    SCORE_DIMENSIONS,
    CandidateEvaluation,
    ScoreDimension,
    ScorePenalty,
    ScoreResult,
)

SCORING_SCHEMA_VERSION = 1
SCORING_ALGORITHM_VERSION = "scoring-v1"
SCORING_WEIGHTS = (
    ("hook", 0.20),
    ("standalone_context", 0.15),
    ("payoff", 0.20),
    ("clarity", 0.15),
    ("emotion_surprise", 0.10),
    ("quotability", 0.10),
    ("information_density", 0.10),
)
SCORING_THRESHOLDS = (
    ("max_filler_ratio", MAX_FILLER_RATIO),
    ("max_pause_ratio", MAX_PAUSE_RATIO),
    ("preferred_duration_min", PREFERRED_DURATION_MIN),
    ("preferred_duration_max", PREFERRED_DURATION_MAX),
    ("density_words_per_second", 3.0),
)
DURATION_FIT_PENALTY = 6.0
PAUSE_PROXY_PENALTY = 5.0
FILLER_PENALTY = 4.0
PENALTY_POINTS = (
    ("DURATION_FIT", DURATION_FIT_PENALTY),
    ("PAUSE_PROXY", PAUSE_PROXY_PENALTY),
    ("FILLER", FILLER_PENALTY),
)

if tuple(name for name, _ in SCORING_WEIGHTS) != SCORE_DIMENSIONS or not isclose(
    sum(weight for _, weight in SCORING_WEIGHTS), 1.0, abs_tol=1e-9
):
    raise RuntimeError("scoring-v1 weights must cover all dimensions and sum to one")


def _ratio_score(value: float | None) -> float:
    """Unknown evidence receives a visible neutral judgment, never a positive one."""
    return 50.0 if value is None else round(value * 100, 2)


def _clarity(evaluation: CandidateEvaluation) -> float:
    features = evaluation.features
    evidence = tuple(
        value
        for value in (features.transcript_confidence, features.timing_coverage)
        if value is not None
    )
    return 50.0 if not evidence else round(sum(evidence) / len(evidence) * 100, 2)


def compose_score(
    dimensions: tuple[ScoreDimension, ...],
    penalties: tuple[ScorePenalty, ...],
) -> tuple[float, float]:
    """Return a two-decimal weighted base and clamped final review priority."""
    if tuple(item.name for item in dimensions) != SCORE_DIMENSIONS:
        raise ValueError("score dimensions must match scoring-v1")
    base = round(
        sum(
            item.value * weight
            for item, (_, weight) in zip(dimensions, SCORING_WEIGHTS, strict=True)
        ),
        2,
    )
    final = round(
        max(0.0, min(100.0, base - sum(item.points for item in penalties))), 2
    )
    return base, final


def deterministic_penalties(
    evaluation: CandidateEvaluation,
) -> tuple[ScorePenalty, ...]:
    """Return the shared project-owned penalties for any scoring mode."""
    features = evaluation.features
    penalties: list[ScorePenalty] = []
    if not PREFERRED_DURATION_MIN <= features.duration <= PREFERRED_DURATION_MAX:
        penalties.append(
            ScorePenalty(
                "DURATION_FIT",
                DURATION_FIT_PENALTY,
                "Outside the preferred 25–45 second band",
            )
        )
    if features.pause_ratio is not None and features.pause_ratio > MAX_PAUSE_RATIO:
        penalties.append(
            ScorePenalty(
                "PAUSE_PROXY",
                PAUSE_PROXY_PENALTY,
                "Transcript gaps exceed the pause proxy threshold",
            )
        )
    if features.filler_ratio is not None and features.filler_ratio > MAX_FILLER_RATIO:
        penalties.append(
            ScorePenalty(
                "FILLER", FILLER_PENALTY, "Filler word ratio exceeds the threshold"
            )
        )
    return tuple(penalties)


def score_heuristically(evaluation: CandidateEvaluation) -> ScoreResult:
    """Judge only measured deterministic signals; no semantic inference is claimed."""
    if evaluation.hard_failed or evaluation.shortlist_rank is None:
        raise ValueError("only shortlisted eligible candidates may be scored")
    features = evaluation.features
    density = (
        None
        if features.words_per_second is None
        else min(1.0, features.words_per_second / 3.0)
    )
    dimensions = tuple(
        ScoreDimension(name, value)
        for name, value in zip(
            SCORE_DIMENSIONS,
            (
                _ratio_score(features.opening_quality),
                _ratio_score(features.standalone_context),
                _ratio_score(features.payoff),
                _clarity(evaluation),
                50.0,  # No deterministic evidence for emotion or surprise.
                50.0,  # No deterministic evidence for quotability.
                _ratio_score(density),
            ),
            strict=True,
        )
    )
    penalties = deterministic_penalties(evaluation)
    measured = (
        features.opening_quality,
        features.standalone_context,
        features.payoff,
        features.transcript_confidence,
        features.timing_coverage,
        features.words_per_second,
        features.pause_ratio,
        features.filler_ratio,
    )
    # Two semantic dimensions remain deliberately neutral even with all measured
    # fields present, so heuristic confidence never reaches one.
    confidence = round(sum(value is not None for value in measured) / 10, 2)
    unknown = [
        name
        for name, value in zip(
            (
                "opening",
                "context",
                "payoff",
                "ASR confidence",
                "timing",
                "density",
                "pause",
                "filler",
            ),
            measured,
            strict=True,
        )
        if value is None
    ]
    evidence_note = (
        "all available deterministic evidence"
        if not unknown
        else "missing " + ", ".join(unknown)
    )
    reason = (
        "Deterministic opening, context, payoff, transcript quality, "
        "and speech density signals; "
        "emotion/surprise and quotability held neutral; " + evidence_note + "."
    )
    base, final = compose_score(dimensions, penalties)
    return ScoreResult(
        score=final,
        base_score=base,
        confidence=confidence,
        dimensions=dimensions,
        penalties=penalties,
        reason=reason,
        scoring_schema_version=SCORING_SCHEMA_VERSION,
        scoring_algorithm_version=SCORING_ALGORITHM_VERSION,
        scorer="heuristic",
    )

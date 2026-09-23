"""Project-owned hybrid composition over validated semantic judgments."""

from collections.abc import Callable
from dataclasses import replace

from multicuts.models import CandidateEvaluation, ScoreResult, SemanticJudgment
from multicuts.scoring.heuristic import (
    SCORING_SCHEMA_VERSION,
    compose_score,
    deterministic_penalties,
    score_heuristically,
)

HYBRID_ALGORITHM_VERSION = "hybrid-scoring-v1"
HYBRID_FALLBACK_ALGORITHM_VERSION = "hybrid-fallback-v1"


def compose_hybrid_score(
    evaluation: CandidateEvaluation, judgment: SemanticJudgment
) -> ScoreResult:
    """Compose semantic dimensions with deterministic penalties exactly once."""
    if evaluation.hard_failed or evaluation.shortlist_rank is None:
        raise ValueError("only shortlisted eligible candidates may be scored")
    penalties = deterministic_penalties(evaluation)
    base, final = compose_score(judgment.dimensions, penalties)
    return ScoreResult(
        score=final,
        base_score=base,
        confidence=judgment.confidence,
        dimensions=judgment.dimensions,
        penalties=penalties,
        reason=judgment.reason,
        scoring_schema_version=SCORING_SCHEMA_VERSION,
        scoring_algorithm_version=HYBRID_ALGORITHM_VERSION,
        scorer="hybrid",
        provider=judgment.provider,
        model=judgment.model,
        prompt_version=judgment.prompt_version,
    )


def score_with_heuristic_fallback(
    evaluation: CandidateEvaluation,
    *,
    scorer: Callable[[CandidateEvaluation], ScoreResult] = score_heuristically,
) -> ScoreResult:
    """Return an explicitly labeled local score after provider failure."""
    result = scorer(evaluation)
    if result.scorer != "heuristic":
        raise ValueError("fallback scorer returned incompatible provenance")
    return replace(
        result,
        scorer="heuristic-fallback",
        scoring_algorithm_version=HYBRID_FALLBACK_ALGORITHM_VERSION,
    )

"""Deterministic ranking, overlap suppression, and top-K selection."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from multicuts.models import (
    Candidate,
    CandidateEvaluation,
    ScoredCandidate,
    SelectedCandidate,
    SelectionDecision,
    SelectionResult,
    SelectionStatus,
)

SELECTION_ALGORITHM_VERSION = "1"
DEFAULT_OVERLAP_THRESHOLD = 0.60
DEFAULT_TEXT_SIMILARITY_THRESHOLD = 0.90
TEXT_POLICY_VERSION = "normalized-token-jaccard-v1"

REASON_SELECTED = "selected_by_rank"
REASON_BELOW_THRESHOLD = "below_min_score"
REASON_TEMPORAL_OVERLAP = "temporal_overlap_threshold"
REASON_TEXT_REDUNDANCY = "normalized_text_similarity"
REASON_BUDGET_EXHAUSTED = "top_k_budget_exhausted"

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RedundancyEvidence:
    """Stable evidence returned by a non-temporal redundancy policy."""

    reason_code: str
    similarity: float

    def __post_init__(self) -> None:
        if not self.reason_code.strip():
            raise ValueError("redundancy reason code must not be empty")
        if not isfinite(self.similarity) or not 0.0 <= self.similarity <= 1.0:
            raise ValueError("redundancy similarity must be within 0..1")


class RedundancyPolicy(Protocol):
    """A replaceable non-temporal redundancy boundary."""

    def compare(
        self, candidate: Candidate, selected: Candidate
    ) -> RedundancyEvidence | None: ...


@dataclass(frozen=True, slots=True)
class NormalizedTextRedundancy:
    """Suppress near-identical normalized token sets at an inclusive threshold."""

    threshold: float = DEFAULT_TEXT_SIMILARITY_THRESHOLD

    def __post_init__(self) -> None:
        _validate_ratio(self.threshold, "text similarity threshold")

    def compare(
        self, candidate: Candidate, selected: Candidate
    ) -> RedundancyEvidence | None:
        candidate_tokens = set(_TOKEN_PATTERN.findall(candidate.text.casefold()))
        selected_tokens = set(_TOKEN_PATTERN.findall(selected.text.casefold()))
        union = candidate_tokens | selected_tokens
        similarity = (
            len(candidate_tokens & selected_tokens) / len(union) if union else 0.0
        )
        if similarity < self.threshold:
            return None
        return RedundancyEvidence(REASON_TEXT_REDUNDANCY, similarity)


@dataclass(frozen=True, slots=True)
class _RankedInput:
    evaluation: CandidateEvaluation
    scored: ScoredCandidate

    @property
    def candidate(self) -> Candidate:
        return self.evaluation.candidate


def _validate_ratio(value: float, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        raise ValueError(f"{label} must be a finite ratio from 0 to 1")


def overlap_ratio(first: Candidate, second: Candidate) -> float:
    """Return intersection duration divided by the shorter source interval."""
    intersection = max(0.0, min(first.end, second.end) - max(first.start, second.start))
    return intersection / min(first.end - first.start, second.end - second.start)


def semantic_completeness(scored: ScoredCandidate) -> float:
    """Use the validated standalone-context score as semantic completeness."""
    return next(
        dimension.value
        for dimension in scored.result.dimensions
        if dimension.name == "standalone_context"
    )


def _static_key(item: _RankedInput) -> tuple[float, float, float, float, str]:
    return (
        -item.scored.result.score,
        -item.scored.result.confidence,
        -semantic_completeness(item.scored),
        item.candidate.start,
        item.candidate.candidate_id,
    )


def _dynamic_key(
    item: _RankedInput, selected: Sequence[SelectedCandidate]
) -> tuple[float, float, float, float, float, str]:
    maximum_overlap = max(
        (
            overlap_ratio(item.candidate, chosen.evaluation.candidate)
            for chosen in selected
        ),
        default=0.0,
    )
    return (
        -item.scored.result.score,
        -item.scored.result.confidence,
        maximum_overlap,
        -semantic_completeness(item.scored),
        item.candidate.start,
        item.candidate.candidate_id,
    )


def _redundancy_decision(
    item: _RankedInput,
    selected: Sequence[SelectedCandidate],
    *,
    overlap_threshold: float,
    policy: RedundancyPolicy,
) -> SelectionDecision | None:
    temporal = sorted(
        (
            (
                overlap_ratio(item.candidate, chosen.evaluation.candidate),
                chosen.rank,
                chosen,
            )
            for chosen in selected
        ),
        key=lambda value: (-value[0], value[1]),
    )
    if temporal and temporal[0][0] >= overlap_threshold:
        ratio, _, suppressor = temporal[0]
        return SelectionDecision(
            item.candidate.candidate_id,
            SelectionStatus.TEMPORAL_OVERLAP,
            REASON_TEMPORAL_OVERLAP,
            suppressed_by=suppressor.candidate_id,
            evidence=ratio,
        )

    text_matches: list[tuple[float, int, SelectedCandidate, RedundancyEvidence]] = []
    for chosen in selected:
        evidence = policy.compare(item.candidate, chosen.evaluation.candidate)
        if evidence is not None:
            text_matches.append((evidence.similarity, chosen.rank, chosen, evidence))
    if text_matches:
        _, _, suppressor, evidence = min(
            text_matches, key=lambda value: (-value[0], value[1])
        )
        return SelectionDecision(
            item.candidate.candidate_id,
            SelectionStatus.TEXT_REDUNDANCY,
            evidence.reason_code,
            suppressed_by=suppressor.candidate_id,
            evidence=evidence.similarity,
        )
    return None


def select_candidates(
    evaluations: tuple[CandidateEvaluation, ...],
    scores: tuple[ScoredCandidate, ...],
    *,
    top_k: int,
    min_score: float,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    redundancy_policy: RedundancyPolicy | None = None,
) -> SelectionResult:
    """Select a deterministic, non-redundant top-K and retain every decision."""
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top-K must be a positive integer")
    if (
        isinstance(min_score, bool)
        or not isinstance(min_score, (int, float))
        or not isfinite(min_score)
        or not 0.0 <= min_score <= 100.0
    ):
        raise ValueError("minimum score must be finite and within 0..100")
    _validate_ratio(overlap_threshold, "overlap threshold")
    policy = redundancy_policy or NormalizedTextRedundancy()

    evaluations_by_id = {
        item.candidate.candidate_id: item
        for item in evaluations
        if item.shortlist_rank is not None and not item.hard_failed
    }
    if len(evaluations_by_id) != len(scores) or set(evaluations_by_id) != {
        item.candidate_id for item in scores
    }:
        raise ValueError("scores must match the eligible evaluation shortlist")
    if len({item.candidate_id for item in scores}) != len(scores):
        raise ValueError("scored candidate IDs must be unique")

    ordered = sorted(
        (_RankedInput(evaluations_by_id[item.candidate_id], item) for item in scores),
        key=_static_key,
    )
    pending: list[_RankedInput] = []
    decisions: dict[str, SelectionDecision] = {}
    for item in ordered:
        if item.scored.result.score < min_score:
            decisions[item.candidate.candidate_id] = SelectionDecision(
                item.candidate.candidate_id,
                SelectionStatus.BELOW_THRESHOLD,
                REASON_BELOW_THRESHOLD,
                evidence=item.scored.result.score / 100.0,
            )
        else:
            pending.append(item)

    selected: list[SelectedCandidate] = []
    while pending and len(selected) < top_k:
        pending.sort(key=lambda item: _dynamic_key(item, selected))
        item = pending.pop(0)
        redundant = _redundancy_decision(
            item,
            selected,
            overlap_threshold=overlap_threshold,
            policy=policy,
        )
        if redundant is not None:
            decisions[item.candidate.candidate_id] = redundant
            continue
        chosen = SelectedCandidate(item.evaluation, item.scored, len(selected) + 1)
        selected.append(chosen)
        decisions[item.candidate.candidate_id] = SelectionDecision(
            item.candidate.candidate_id,
            SelectionStatus.SELECTED,
            REASON_SELECTED,
            rank=chosen.rank,
        )

    for item in sorted(pending, key=_static_key):
        redundant = _redundancy_decision(
            item,
            selected,
            overlap_threshold=overlap_threshold,
            policy=policy,
        )
        decisions[item.candidate.candidate_id] = redundant or SelectionDecision(
            item.candidate.candidate_id,
            SelectionStatus.BUDGET_EXHAUSTED,
            REASON_BUDGET_EXHAUSTED,
        )

    selected_ids = {item.candidate_id for item in selected}
    ordered_decisions = tuple(
        decisions[item.candidate_id] for item in selected
    ) + tuple(
        decisions[item.candidate.candidate_id]
        for item in ordered
        if item.candidate.candidate_id not in selected_ids
    )
    return SelectionResult(selected=tuple(selected), decisions=ordered_decisions)

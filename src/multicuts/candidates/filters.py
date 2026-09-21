"""Deterministic candidate features, checklist rules, and scoring budget."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from math import isfinite

from multicuts.candidates.features import FEATURE_VERSION, compute_candidate_features
from multicuts.models import (
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationBatch,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    Transcript,
)

CANDIDATE_EVALUATION_VERSION = "1"
DEFAULT_CANDIDATE_BUDGET = 50
MIN_SPEECH_WORDS = 5
MIN_WORDS_PER_SECOND = 0.1
MAX_PAUSE_RATIO = 0.55
MIN_BOUNDARY_QUALITY = 0.5
MIN_STANDALONE_CONTEXT = 0.5
MIN_PAYOFF_SIGNAL = 0.5
MIN_TRANSCRIPT_CONFIDENCE = 0.55
MIN_TIMING_COVERAGE = 0.5
MAX_FILLER_RATIO = 0.3
PREFERRED_DURATION_MIN = 25.0
PREFERRED_DURATION_MAX = 45.0
PREFERRED_DURATION_MIDPOINT = 35.0

RULE_VALID_DURATION = "valid_duration"
RULE_SUFFICIENT_SPEECH = "sufficient_speech"
RULE_EXCESSIVE_SILENCE = "excessive_silence_proxy"
RULE_OPENING_BOUNDARY = "acceptable_opening_boundary"
RULE_ENDING_BOUNDARY = "acceptable_ending_boundary"
RULE_STANDALONE_CONTEXT = "standalone_context"
RULE_PAYOFF = "payoff_presence"
RULE_TRANSCRIPT_QUALITY = "transcript_quality"


def _validate_budget(candidate_budget: int) -> None:
    if type(candidate_budget) is not int or candidate_budget <= 0:
        raise ValueError("candidate budget must be a positive integer")


def _validate_duration_limits(min_duration: float, max_duration: float) -> None:
    if (
        not isfinite(min_duration)
        or not isfinite(max_duration)
        or min_duration <= 0
        or max_duration <= 0
        or min_duration > max_duration
    ):
        raise ValueError(
            "candidate duration limits must be finite, positive, and ordered"
        )


def _result(
    rule_code: str,
    outcome: ChecklistOutcome,
    reason: str,
    evidence: str,
) -> ChecklistResult:
    return ChecklistResult(rule_code, outcome, reason, evidence)


def evaluate_checklist(
    features: CandidateFeatures,
    *,
    min_duration: float,
    max_duration: float,
) -> tuple[ChecklistResult, ...]:
    """Apply the versioned initial checklist to already computed features."""
    _validate_duration_limits(min_duration, max_duration)

    if not min_duration <= features.duration <= max_duration:
        duration_result = _result(
            RULE_VALID_DURATION,
            ChecklistOutcome.HARD_FAIL,
            "Candidate duration is outside the configured range",
            f"duration={features.duration:.6f};range={min_duration:.6f}-{max_duration:.6f}",
        )
    else:
        duration_result = _result(
            RULE_VALID_DURATION,
            ChecklistOutcome.PASS,
            "Candidate duration is within the configured range",
            f"duration={features.duration:.6f}",
        )

    speech_failure = features.word_count < MIN_SPEECH_WORDS or (
        features.words_per_second is not None
        and features.words_per_second < MIN_WORDS_PER_SECOND
    )
    if speech_failure:
        speech_result = _result(
            RULE_SUFFICIENT_SPEECH,
            ChecklistOutcome.HARD_FAIL,
            "Candidate does not contain enough timed speech text",
            f"words={features.word_count};words_per_second={features.words_per_second!s}",
        )
    else:
        speech_result = _result(
            RULE_SUFFICIENT_SPEECH,
            ChecklistOutcome.PASS,
            "Candidate contains enough speech text for downstream scoring",
            f"words={features.word_count};words_per_second={features.words_per_second!s}",
        )

    if features.pause_ratio is None:
        silence_result = _result(
            RULE_EXCESSIVE_SILENCE,
            ChecklistOutcome.UNKNOWN,
            "Transcript timing does not provide an internal pause proxy",
            "pause_ratio=unknown",
        )
    elif features.pause_ratio > MAX_PAUSE_RATIO:
        silence_result = _result(
            RULE_EXCESSIVE_SILENCE,
            ChecklistOutcome.SOFT_FAIL,
            "Transcript timing suggests an excessive internal pause ratio",
            f"pause_ratio={features.pause_ratio:.6f};threshold={MAX_PAUSE_RATIO:.6f}",
        )
    else:
        silence_result = _result(
            RULE_EXCESSIVE_SILENCE,
            ChecklistOutcome.PASS,
            "Transcript timing does not suggest excessive internal pauses",
            f"pause_ratio={features.pause_ratio:.6f}",
        )

    opening_result = _boundary_result(
        RULE_OPENING_BOUNDARY,
        features.opening_quality,
        "opening boundary",
    )
    ending_result = _boundary_result(
        RULE_ENDING_BOUNDARY,
        features.ending_quality,
        "ending boundary",
    )
    context_result = _threshold_result(
        RULE_STANDALONE_CONTEXT,
        features.standalone_context,
        MIN_STANDALONE_CONTEXT,
        "standalone context",
    )
    payoff_result = _threshold_result(
        RULE_PAYOFF,
        features.payoff,
        MIN_PAYOFF_SIGNAL,
        "payoff evidence",
    )

    quality_evidence = [
        features.transcript_confidence is not None,
        features.timing_coverage is not None,
        features.filler_ratio is not None,
    ]
    if not any(quality_evidence):
        quality_result = _result(
            RULE_TRANSCRIPT_QUALITY,
            ChecklistOutcome.UNKNOWN,
            "Transcript quality evidence is unavailable",
            "confidence=unknown;timing_coverage=unknown;filler_ratio=unknown",
        )
    elif features.transcript_confidence is None:
        quality_result = _result(
            RULE_TRANSCRIPT_QUALITY,
            ChecklistOutcome.UNKNOWN,
            "Word confidence is unavailable for this candidate",
            f"timing_coverage={features.timing_coverage!s};filler_ratio={features.filler_ratio!s}",
        )
    elif (
        features.transcript_confidence < MIN_TRANSCRIPT_CONFIDENCE
        or (
            features.timing_coverage is not None
            and features.timing_coverage < MIN_TIMING_COVERAGE
        )
        or (
            features.filler_ratio is not None
            and features.filler_ratio > MAX_FILLER_RATIO
        )
    ):
        quality_result = _result(
            RULE_TRANSCRIPT_QUALITY,
            ChecklistOutcome.SOFT_FAIL,
            "Transcript quality evidence is below the initial soft threshold",
            "confidence="
            f"{features.transcript_confidence:.6f};timing_coverage={features.timing_coverage!s};"
            f"filler_ratio={features.filler_ratio!s}",
        )
    else:
        quality_result = _result(
            RULE_TRANSCRIPT_QUALITY,
            ChecklistOutcome.PASS,
            "Transcript quality evidence meets the initial threshold",
            "confidence="
            f"{features.transcript_confidence:.6f};timing_coverage={features.timing_coverage!s};"
            f"filler_ratio={features.filler_ratio!s}",
        )

    return (
        duration_result,
        speech_result,
        silence_result,
        opening_result,
        ending_result,
        context_result,
        payoff_result,
        quality_result,
    )


def _boundary_result(
    rule_code: str, value: float | None, label: str
) -> ChecklistResult:
    return _threshold_result(rule_code, value, MIN_BOUNDARY_QUALITY, label)


def _threshold_result(
    rule_code: str,
    value: float | None,
    threshold: float,
    label: str,
) -> ChecklistResult:
    if value is None:
        return _result(
            rule_code,
            ChecklistOutcome.UNKNOWN,
            f"Evidence for {label} is unavailable",
            f"value=unknown;threshold={threshold:.6f}",
        )
    if value < threshold:
        return _result(
            rule_code,
            ChecklistOutcome.SOFT_FAIL,
            f"Evidence for {label} is below the soft threshold",
            f"value={value:.6f};threshold={threshold:.6f}",
        )
    return _result(
        rule_code,
        ChecklistOutcome.PASS,
        f"Evidence for {label} meets the soft threshold",
        f"value={value:.6f};threshold={threshold:.6f}",
    )


def evaluate_candidate(
    candidate: Candidate,
    transcript: Transcript,
    *,
    min_duration: float,
    max_duration: float,
    feature_version: str = FEATURE_VERSION,
) -> CandidateEvaluation:
    """Compute evidence and checklist results for one candidate."""
    features = compute_candidate_features(
        candidate, transcript, feature_version=feature_version
    )
    return CandidateEvaluation(
        candidate=candidate,
        features=features,
        checklist=evaluate_checklist(
            features, min_duration=min_duration, max_duration=max_duration
        ),
    )


def _known(value: float | None) -> float:
    return value if value is not None else -1.0


def _preorder_key(evaluation: CandidateEvaluation) -> tuple[object, ...]:
    """Order by cheap evidence only; this is not the product score."""
    features = evaluation.features
    quality_values = (
        features.speech_ratio,
        features.opening_quality,
        features.ending_quality,
        features.standalone_context,
        features.payoff,
        features.transcript_confidence,
    )
    known_count = sum(value is not None for value in quality_values)
    quality_sum = sum(value for value in quality_values if value is not None)
    duration_distance = 0.0
    if not PREFERRED_DURATION_MIN <= features.duration <= PREFERRED_DURATION_MAX:
        duration_distance = abs(features.duration - PREFERRED_DURATION_MIDPOINT)
    soft_fail_count = sum(
        result.outcome is ChecklistOutcome.SOFT_FAIL for result in evaluation.checklist
    )
    unknown_count = sum(
        result.outcome is ChecklistOutcome.UNKNOWN for result in evaluation.checklist
    )
    return (
        -soft_fail_count,
        -known_count,
        -quality_sum,
        -_known(features.words_per_second),
        duration_distance,
        unknown_count,
        evaluation.candidate.start,
        evaluation.candidate.end,
        evaluation.candidate.candidate_id,
    )


def evaluate_candidates(
    candidates: Sequence[Candidate],
    transcript: Transcript,
    *,
    min_duration: float,
    max_duration: float,
    candidate_budget: int = DEFAULT_CANDIDATE_BUDGET,
    evaluation_version: str = CANDIDATE_EVALUATION_VERSION,
) -> CandidateEvaluationBatch:
    """Evaluate all candidates and return a stable bounded scoring shortlist."""
    _validate_budget(candidate_budget)
    _validate_duration_limits(min_duration, max_duration)
    if not evaluation_version.strip():
        raise ValueError("candidate evaluation version must not be empty")

    ordered_candidates = tuple(sorted(candidates, key=lambda item: item.candidate_id))
    candidate_ids = tuple(item.candidate_id for item in ordered_candidates)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate IDs must be unique for evaluation")
    evaluations = tuple(
        evaluate_candidate(
            candidate,
            transcript,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        for candidate in ordered_candidates
    )
    eligible = tuple(item for item in evaluations if item.eligible_for_scoring)
    selected = tuple(sorted(eligible, key=_preorder_key)[:candidate_budget])
    selected_ids = {item.candidate.candidate_id for item in selected}
    ranks = {
        item.candidate.candidate_id: index
        for index, item in enumerate(selected, start=1)
    }
    ranked_evaluations = tuple(
        replace(item, shortlist_rank=ranks.get(item.candidate.candidate_id))
        for item in evaluations
    )
    ranked_by_id = {item.candidate.candidate_id: item for item in ranked_evaluations}
    shortlist = tuple(ranked_by_id[candidate_id] for candidate_id in selected_ids)
    shortlist = tuple(sorted(shortlist, key=lambda item: item.shortlist_rank or 0))
    return CandidateEvaluationBatch(
        evaluations=ranked_evaluations,
        shortlist=shortlist,
    )


apply_checklist = evaluate_checklist
evaluate_candidate_set = evaluate_candidates
filter_candidates = evaluate_candidates
build_candidate_shortlist = evaluate_candidates

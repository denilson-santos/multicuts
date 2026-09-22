import json
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.artifacts import prepare_workspace
from multicuts.candidates.ranking import (
    NormalizedTextRedundancy,
    overlap_ratio,
    select_candidates,
)
from multicuts.candidates.selection_artifacts import (
    InvalidSelectionArtifactError,
    read_selection,
    selection_cache_key,
    write_selection,
)
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    ScoredCandidate,
    SelectedCandidate,
    SelectionStatus,
)
from multicuts.scoring.heuristic import score_heuristically


def _ranked(
    candidate_id: str,
    start: float,
    end: float,
    text: str,
    *,
    score: float,
    confidence: float = 0.8,
    completeness: float = 70.0,
    shortlist_rank: int = 1,
) -> tuple[CandidateEvaluation, ScoredCandidate]:
    candidate = Candidate(candidate_id, start, end, text, (shortlist_rank - 1,), "1")
    evaluation = CandidateEvaluation(
        candidate=candidate,
        features=CandidateFeatures(
            duration=end - start,
            word_count=10,
            timed_word_count=10,
            standalone_context=completeness / 100.0,
        ),
        checklist=(ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        shortlist_rank=shortlist_rank,
    )
    base = score_heuristically(evaluation)
    dimensions = tuple(
        replace(item, value=completeness) if item.name == "standalone_context" else item
        for item in base.dimensions
    )
    result = replace(
        base,
        score=score,
        base_score=score,
        confidence=confidence,
        dimensions=dimensions,
    )
    return evaluation, ScoredCandidate(candidate_id, result)


def _inputs() -> tuple[tuple[CandidateEvaluation, ...], tuple[ScoredCandidate, ...]]:
    values = (
        _ranked(
            "candidate-a",
            0.0,
            20.0,
            "A complete first idea",
            score=90,
            shortlist_rank=1,
        ),
        _ranked(
            "candidate-b",
            30.0,
            50.0,
            "A separate second idea",
            score=80,
            shortlist_rank=2,
        ),
        _ranked(
            "candidate-c",
            60.0,
            80.0,
            "A distinct third idea",
            score=70,
            shortlist_rank=3,
        ),
    )
    return tuple(item[0] for item in values), tuple(item[1] for item in values)


def test_overlap_ratio_uses_shorter_candidate_and_touching_is_zero() -> None:
    containing = Candidate("a", 0.0, 20.0, "one", (0,), "1")
    contained = Candidate("b", 5.0, 15.0, "two", (1,), "1")
    touching = Candidate("c", 20.0, 30.0, "three", (2,), "1")

    assert overlap_ratio(containing, contained) == 1.0
    assert overlap_ratio(containing, touching) == 0.0
    assert overlap_ratio(containing, containing) == 1.0


def test_selection_order_is_stable_across_input_permutations() -> None:
    evaluations, scores = _inputs()
    first = select_candidates(evaluations, scores, top_k=3, min_score=0)
    second = select_candidates(
        tuple(reversed(evaluations)), tuple(reversed(scores)), top_k=3, min_score=0
    )

    assert first == second
    assert tuple(item.candidate_id for item in first.selected) == (
        "candidate-a",
        "candidate-b",
        "candidate-c",
    )


def test_static_order_uses_confidence_completeness_time_and_id_ties() -> None:
    values = (
        _ranked(
            "candidate-a",
            100,
            120,
            "highest confidence",
            score=80,
            confidence=0.9,
            completeness=10,
            shortlist_rank=1,
        ),
        _ranked(
            "candidate-b",
            0,
            20,
            "highest completeness",
            score=80,
            confidence=0.8,
            completeness=100,
            shortlist_rank=2,
        ),
        _ranked(
            "candidate-d",
            40,
            60,
            "later source time",
            score=80,
            confidence=0.8,
            completeness=90,
            shortlist_rank=3,
        ),
        _ranked(
            "candidate-c",
            30,
            50,
            "earlier source time",
            score=80,
            confidence=0.8,
            completeness=90,
            shortlist_rank=4,
        ),
        _ranked(
            "candidate-f",
            70,
            90,
            "exact tie f",
            score=70,
            confidence=0.7,
            completeness=70,
            shortlist_rank=5,
        ),
        _ranked(
            "candidate-e",
            70,
            90,
            "exact tie e",
            score=70,
            confidence=0.7,
            completeness=70,
            shortlist_rank=6,
        ),
    )
    result = select_candidates(
        tuple(item[0] for item in reversed(values)),
        tuple(item[1] for item in reversed(values)),
        top_k=6,
        min_score=0,
        overlap_threshold=1.0,
        redundancy_policy=NormalizedTextRedundancy(1.0),
    )

    assert tuple(item.candidate_id for item in result.selected) == (
        "candidate-a",
        "candidate-b",
        "candidate-c",
        "candidate-d",
        "candidate-e",
    )
    exact_tie = next(
        item for item in result.decisions if item.candidate_id == "candidate-f"
    )
    assert exact_tie.suppressed_by == "candidate-e"


def test_selected_candidate_rejects_inconsistent_score_identity() -> None:
    first = _ranked("first", 0, 20, "first", score=90, shortlist_rank=1)
    second = _ranked("second", 30, 50, "second", score=80, shortlist_rank=2)

    with pytest.raises(ValueError, match="identity"):
        SelectedCandidate(first[0], second[1], 1)


def test_order_uses_confidence_overlap_completeness_then_source_time() -> None:
    first = _ranked("first", 0, 20, "first text", score=90, shortlist_rank=1)
    overlapping = _ranked(
        "overlapping",
        10,
        30,
        "overlapping text",
        score=80,
        completeness=100,
        shortlist_rank=2,
    )
    separate = _ranked(
        "separate",
        40,
        60,
        "separate text",
        score=80,
        completeness=10,
        shortlist_rank=3,
    )
    values = (first, overlapping, separate)
    result = select_candidates(
        tuple(item[0] for item in values),
        tuple(item[1] for item in values),
        top_k=2,
        min_score=0,
        overlap_threshold=0.60,
    )

    assert tuple(item.candidate_id for item in result.selected) == ("first", "separate")

    complete = select_candidates(
        tuple(item[0] for item in values),
        tuple(item[1] for item in values),
        top_k=3,
        min_score=0,
        overlap_threshold=0.60,
    )
    assert tuple(item.candidate_id for item in complete.selected) == (
        "first",
        "separate",
        "overlapping",
    )


def test_overlap_threshold_is_inclusive_and_names_suppressor() -> None:
    first = _ranked("first", 0, 10, "first idea", score=90, shortlist_rank=1)
    overlap = _ranked("overlap", 4, 14, "second idea", score=80, shortlist_rank=2)
    result = select_candidates(
        (first[0], overlap[0]),
        (first[1], overlap[1]),
        top_k=2,
        min_score=0,
        overlap_threshold=0.60,
    )

    decision = next(item for item in result.decisions if item.candidate_id == "overlap")
    assert decision.status is SelectionStatus.TEMPORAL_OVERLAP
    assert decision.suppressed_by == "first"
    assert decision.evidence == pytest.approx(0.60)


def test_text_policy_suppresses_normalized_near_duplicate() -> None:
    first = _ranked(
        "first", 0, 20, "Build APIs, test them well!", score=90, shortlist_rank=1
    )
    duplicate = _ranked(
        "duplicate", 30, 50, "Test them well; build APIs.", score=80, shortlist_rank=2
    )
    result = select_candidates(
        (first[0], duplicate[0]),
        (first[1], duplicate[1]),
        top_k=2,
        min_score=0,
        redundancy_policy=NormalizedTextRedundancy(0.90),
    )

    decision = next(
        item for item in result.decisions if item.candidate_id == "duplicate"
    )
    assert decision.status is SelectionStatus.TEXT_REDUNDANCY
    assert decision.suppressed_by == "first"
    assert decision.evidence == 1.0


def test_selection_retains_threshold_and_budget_decisions() -> None:
    evaluations, scores = _inputs()
    result = select_candidates(evaluations, scores, top_k=1, min_score=75)
    statuses = {item.candidate_id: item.status for item in result.decisions}

    assert tuple(item.rank for item in result.selected) == (1,)
    assert statuses == {
        "candidate-a": SelectionStatus.SELECTED,
        "candidate-b": SelectionStatus.BUDGET_EXHAUSTED,
        "candidate-c": SelectionStatus.BELOW_THRESHOLD,
    }


def test_selection_cache_roundtrip_and_invalidation(tmp_path: Path) -> None:
    evaluations, scores = _inputs()
    selection = select_candidates(evaluations, scores, top_k=2, min_score=0)
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:source")
    paths = prepare_workspace(tmp_path, source, cache_key="sha256-v1:transcript")
    key = selection_cache_key(
        scoring_key="sha256-v1:scoring",
        scores=scores,
        top_k=2,
        min_score=0,
        overlap_threshold=0.60,
        text_similarity_threshold=0.90,
    )

    write_selection(
        paths,
        selection,
        cache_key=key,
        evaluations=evaluations,
        scores=scores,
        overlap_threshold=0.60,
        text_similarity_threshold=0.90,
        replace=False,
    )
    assert (
        read_selection(
            paths,
            cache_key=key,
            evaluations=evaluations,
            scores=scores,
            overlap_threshold=0.60,
            text_similarity_threshold=0.90,
        )
        == selection
    )
    assert (
        read_selection(
            paths,
            cache_key="sha256-v1:other",
            evaluations=evaluations,
            scores=scores,
            overlap_threshold=0.60,
            text_similarity_threshold=0.90,
        )
        is None
    )
    assert (
        selection_cache_key(
            scoring_key="sha256-v1:scoring",
            scores=scores,
            top_k=3,
            min_score=0,
            overlap_threshold=0.60,
            text_similarity_threshold=0.90,
        )
        != key
    )
    changed_scores = (
        replace(scores[0], result=replace(scores[0].result, score=91)),
    ) + scores[1:]
    assert (
        selection_cache_key(
            scoring_key="sha256-v1:scoring",
            scores=changed_scores,
            top_k=2,
            min_score=0,
            overlap_threshold=0.60,
            text_similarity_threshold=0.90,
        )
        != key
    )

    payload = json.loads(paths.selection.read_text(encoding="utf-8"))
    payload["selected"][0]["score"] = -1
    paths.selection.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidSelectionArtifactError, match="provenance"):
        read_selection(
            paths,
            cache_key=key,
            evaluations=evaluations,
            scores=scores,
            overlap_threshold=0.60,
            text_similarity_threshold=0.90,
        )

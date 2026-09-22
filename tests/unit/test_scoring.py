import json
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.artifacts import prepare_workspace
from multicuts.config import RunConfig
from multicuts.models import (
    SCORE_DIMENSIONS,
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationArtifact,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    ScoredCandidate,
    ScoreDimension,
    ScorePenalty,
    Transcript,
    TranscriptSegment,
)
from multicuts.pipeline import load_or_score_candidates
from multicuts.scoring.artifacts import (
    InvalidScoringArtifactError,
    read_scores,
    scoring_cache_key,
    write_scores,
)
from multicuts.scoring.heuristic import (
    SCORING_WEIGHTS,
    compose_score,
    score_heuristically,
)


def _evaluation(**feature_changes: float | None) -> CandidateEvaluation:
    values = {
        "duration": 30.0,
        "word_count": 20,
        "timed_word_count": 20,
        "words_per_second": 2.0,
        "pause_ratio": 0.1,
        "opening_quality": 0.8,
        "ending_quality": 0.75,
        "standalone_context": 0.7,
        "payoff": 0.9,
        "filler_ratio": 0.1,
        "transcript_confidence": 0.8,
        "timing_coverage": 1.0,
    }
    values.update(feature_changes)
    features = CandidateFeatures(**values)  # type: ignore[arg-type]
    return CandidateEvaluation(
        candidate=Candidate(
            "candidate-v1:one", 0.0, 30.0, "A complete example.", (0,), "1"
        ),
        features=features,
        checklist=(ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        shortlist_rank=1,
    )


def test_scoring_contract_weights_and_composition() -> None:
    evaluation = _evaluation()
    result = score_heuristically(evaluation)

    assert tuple(name for name, _ in SCORING_WEIGHTS) == SCORE_DIMENSIONS
    assert sum(weight for _, weight in SCORING_WEIGHTS) == pytest.approx(1.0)
    assert tuple(item.name for item in result.dimensions) == SCORE_DIMENSIONS
    assert result.confidence == 0.8
    assert result.dimensions[4].value == result.dimensions[5].value == 50.0
    assert result.penalties == ()
    assert (result.base_score, result.score) == compose_score(
        result.dimensions, result.penalties
    )
    assert "held neutral" in result.reason


def test_unknown_evidence_reduces_confidence_without_claiming_semantics() -> None:
    result = score_heuristically(
        _evaluation(opening_quality=None, transcript_confidence=None)
    )
    assert result.confidence == 0.6
    assert result.dimensions[0].value == 50.0
    assert "missing opening, ASR confidence" in result.reason
    assert result.provider is result.model is result.prompt_version is None


def test_penalties_use_distinct_duration_pause_and_filler_signals() -> None:
    result = score_heuristically(
        _evaluation(duration=20.0, pause_ratio=0.6, filler_ratio=0.4)
    )
    assert [(item.code, item.points) for item in result.penalties] == [
        ("DURATION_FIT", 6.0),
        ("PAUSE_PROXY", 5.0),
        ("FILLER", 4.0),
    ]
    assert result.score == max(0, result.base_score - 15)
    assert (
        compose_score(result.dimensions, (ScorePenalty("large", 200, "example"),))[1]
        == 0
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 101.0])
def test_score_dimension_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValueError):
        ScoreDimension("hook", value)


def test_score_result_rejects_missing_dimension_and_semantic_provenance() -> None:
    result = score_heuristically(_evaluation())
    with pytest.raises(ValueError, match="closed ordered set"):
        replace(result, dimensions=result.dimensions[:-1])
    with pytest.raises(ValueError, match="semantic provenance"):
        replace(result, provider="invented")


def test_score_cache_roundtrip_invalidation_and_corrupt_result(tmp_path: Path) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:source")
    paths = prepare_workspace(tmp_path, source, cache_key="sha256-v1:transcript")
    evaluation = _evaluation()
    key = scoring_cache_key(
        evaluation_key="sha256-v1:evaluation", shortlist=(evaluation,)
    )
    scored = (
        ScoredCandidate(
            evaluation.candidate.candidate_id, score_heuristically(evaluation)
        ),
    )

    write_scores(paths, scored, cache_key=key, replace=False)
    assert (
        read_scores(
            paths, cache_key=key, expected_ids=(evaluation.candidate.candidate_id,)
        )
        == scored
    )
    assert (
        read_scores(
            paths,
            cache_key="sha256-v1:other",
            expected_ids=(evaluation.candidate.candidate_id,),
        )
        is None
    )
    assert (
        scoring_cache_key(
            evaluation_key="sha256-v1:evaluation",
            shortlist=(
                replace(evaluation, features=replace(evaluation.features, payoff=0.8)),
            ),
        )
        != key
    )

    payload = json.loads(paths.scores.read_text(encoding="utf-8"))
    payload["scores"][0]["result"]["score"] = 99
    paths.scores.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidScoringArtifactError, match="score composition"):
        read_scores(
            paths, cache_key=key, expected_ids=(evaluation.candidate.candidate_id,)
        )


def test_pipeline_score_cache_reuses_compatible_result_across_geometry(
    tmp_path: Path,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:source")
    config = RunConfig(
        source="source.mp4",
        output_dir=tmp_path,
        clips=2,
        min_score=60,
        aspect_ratio="original",
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
    )
    transcript = Transcript(
        language_requested=None,
        language_detected="en",
        duration=60,
        text="A complete example.",
        segments=(TranscriptSegment("A complete example.", 0, 30),),
        words=(),
        provider="multisubs",
        provider_version="4.2.0",
    )
    evaluation = _evaluation()
    artifact = CandidateEvaluationArtifact(
        source_fingerprint=source.fingerprint,
        candidate_generator_version="1",
        evaluation_version="1",
        min_duration=15,
        max_duration=60,
        candidate_budget=50,
        evaluations=(evaluation,),
    )
    calls = 0

    def scorer(item: CandidateEvaluation):
        nonlocal calls
        calls += 1
        return score_heuristically(item)

    first = load_or_score_candidates(
        config, source, transcript, artifact, scorer=scorer
    )
    changed = replace(config, aspect_ratio="9:16", subtitle_template="different")
    second = load_or_score_candidates(
        changed, source, transcript, artifact, scorer=scorer
    )

    assert first == second
    assert calls == 1

    score_path = next(tmp_path.rglob("scores.json"))
    score_path.write_text("{incomplete", encoding="utf-8")
    repaired = load_or_score_candidates(
        changed, source, transcript, artifact, scorer=scorer
    )
    assert repaired == first
    assert calls == 2

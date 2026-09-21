import json
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.artifacts import (
    InvalidCandidateEvaluationArtifactError,
    candidate_evaluation_cache_key,
    prepare_workspace,
    read_candidate_evaluation,
    write_candidate_evaluation,
)
from multicuts.candidates.features import compute_candidate_features
from multicuts.candidates.filters import (
    CANDIDATE_EVALUATION_VERSION,
    evaluate_candidate,
    evaluate_candidates,
)
from multicuts.cli import parse_run_config
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluationArtifact,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import load_or_evaluate_candidates


def _transcript(
    *,
    words: tuple[Word, ...],
    segments: tuple[TranscriptSegment, ...] | None = None,
    duration: float = 60.0,
    text: str | None = None,
) -> Transcript:
    return Transcript(
        language_requested=None,
        language_detected="en",
        duration=duration,
        text=text or " ".join(word.text for word in words) or "Transcript text",
        segments=(
            segments
            if segments is not None
            else (TranscriptSegment("A complete candidate.", 0.0, duration),)
        ),
        words=words,
        provider="multisubs",
        provider_version="4.2.0",
    )


def _candidate(
    candidate_id: str = "candidate-v1:one",
    *,
    start: float = 0.0,
    end: float = 30.0,
    text: str = "A complete candidate with a payoff.",
) -> Candidate:
    return Candidate(candidate_id, start, end, text, (0,), "1")


def _cache_key(**changes: object) -> str:
    values: dict[str, object] = {
        "source_fingerprint": "sha256-v1:source",
        "candidate_generator_version": "1",
        "evaluation_version": CANDIDATE_EVALUATION_VERSION,
        "min_duration": 15.0,
        "max_duration": 60.0,
        "candidate_budget": 50,
    }
    values.update(changes)
    return candidate_evaluation_cache_key(**values)  # type: ignore[arg-type]


def test_features_use_real_word_overlap_and_pause_proxies() -> None:
    transcript = _transcript(
        words=(
            Word("A", 0.0, 0.8, 0.9),
            Word("complete", 1.8, 2.6, 0.8),
            Word("candidate", 2.7, 3.5, 0.7),
            Word("outside", 30.0, 31.0, 0.6),
        ),
        segments=(TranscriptSegment("A complete candidate.", 0.0, 3.5),),
    )

    features = compute_candidate_features(
        _candidate(end=30.0, text="A complete candidate with a payoff."), transcript
    )

    assert features.timed_word_count == 3
    assert features.word_count == 6
    assert features.speech_duration == pytest.approx(2.4)
    assert features.pause_duration == pytest.approx(1.1)
    assert features.pause_ratio == pytest.approx(1.1 / 30)
    assert features.transcript_confidence == pytest.approx(0.8)
    assert features.timing_coverage == pytest.approx(0.5)
    assert features.opening_quality == 1.0
    assert features.ending_quality == 0.75


def test_features_keep_missing_confidence_and_timing_explicit() -> None:
    transcript = _transcript(
        words=(Word("A", 0.0, 0.5), Word("candidate", 1.0, 1.5)),
        segments=(TranscriptSegment("A candidate.", 0.0, 2.0),),
    )

    features = compute_candidate_features(_candidate(text="A candidate."), transcript)

    assert features.transcript_confidence is None
    assert features.timing_coverage == 1.0
    assert features.pause_ratio == pytest.approx(0.5 / 30)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"speech_ratio": 1.1},
        {"timing_coverage": -0.1},
        {"max_pause": -1.0},
    ],
)
def test_feature_model_rejects_out_of_range_values(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        CandidateFeatures(1.0, 1, 1, **kwargs)  # type: ignore[arg-type]


def test_checklist_preserves_unknown_and_hard_failure_severity() -> None:
    short = _candidate(end=10.0, text="Too short")
    transcript = _transcript(
        words=(Word("Too", 0.0, 1.0), Word("short", 1.1, 2.0)),
        duration=20.0,
    )

    evaluation = evaluate_candidate(
        short, transcript, min_duration=15.0, max_duration=60.0
    )
    outcomes = {result.rule_code: result.outcome for result in evaluation.checklist}

    assert outcomes["valid_duration"] is ChecklistOutcome.HARD_FAIL
    assert outcomes["sufficient_speech"] is ChecklistOutcome.HARD_FAIL
    assert outcomes["excessive_silence_proxy"] is ChecklistOutcome.PASS
    assert all(result.reason for result in evaluation.checklist)


def test_checklist_reports_unknown_when_pause_evidence_is_missing() -> None:
    candidate = _candidate(text="A candidate with enough words.")
    transcript = _transcript(
        words=(),
        segments=(TranscriptSegment("Untimed", None, None),),
        text="Untimed candidate",
    )

    # The candidate still has deterministic text evidence, but no invented word
    # timing is allowed to turn the pause rule into a pass or failure.
    evaluation = evaluate_candidate(
        candidate, transcript, min_duration=15.0, max_duration=60.0
    )

    result = next(
        result
        for result in evaluation.checklist
        if result.rule_code == "excessive_silence_proxy"
    )
    assert result.outcome is ChecklistOutcome.UNKNOWN


def test_evaluation_budget_and_order_are_stable_under_input_reordering() -> None:
    words = tuple(
        Word(f"word{index}", float(index), float(index) + 0.5, 0.8)
        for index in range(40)
    )
    transcript = _transcript(words=words, duration=60.0)
    candidates = tuple(
        _candidate(
            f"candidate-v1:{index}",
            start=float(index),
            end=float(index + 20),
            text="one two three four five six seven eight",
        )
        for index in range(3)
    )

    first = evaluate_candidates(
        candidates,
        transcript,
        min_duration=15.0,
        max_duration=60.0,
        candidate_budget=2,
    )
    second = evaluate_candidates(
        tuple(reversed(candidates)),
        transcript,
        min_duration=15.0,
        max_duration=60.0,
        candidate_budget=2,
    )

    assert len(first.shortlist) == 2
    assert [item.candidate.candidate_id for item in first.shortlist] == [
        item.candidate.candidate_id for item in second.shortlist
    ]
    assert all(not item.hard_failed for item in first.shortlist)
    assert all(item.shortlist_rank for item in first.shortlist)


def test_candidate_artifact_round_trip_and_config_key_invalidation(
    tmp_path: Path,
) -> None:
    transcript = _transcript(
        words=tuple(
            Word(f"word{index}", index, index + 0.5, 0.8) for index in range(6)
        ),
    )
    batch = evaluate_candidates(
        (_candidate(),),
        transcript,
        min_duration=15.0,
        max_duration=60.0,
        candidate_budget=50,
    )
    artifact = CandidateEvaluationArtifact(
        source_fingerprint="sha256-v1:source",
        candidate_generator_version="1",
        evaluation_version=CANDIDATE_EVALUATION_VERSION,
        min_duration=15.0,
        max_duration=60.0,
        candidate_budget=50,
        evaluations=batch.evaluations,
    )
    key = _cache_key()
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:source"),
        cache_key=key,
    )
    write_candidate_evaluation(paths, artifact, cache_key=key, replace=False)

    assert read_candidate_evaluation(paths, cache_key=key) == artifact
    assert (
        read_candidate_evaluation(paths, cache_key=_cache_key(candidate_budget=49))
        is None
    )


def test_invalid_candidate_artifact_is_rejected(tmp_path: Path) -> None:
    key = _cache_key()
    paths = prepare_workspace(
        tmp_path,
        AcquiredSource(Path("source.mp4"), "sha256-v1:source"),
        cache_key=key,
    )
    paths.candidates.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage_version": 1,
                "task": "candidate_evaluation",
                "cache_key": key,
                "source_fingerprint": "sha256-v1:source",
                "candidate_generator_version": "1",
                "evaluation_version": "1",
                "config": {
                    "min_duration": 15.0,
                    "max_duration": 60.0,
                    "candidate_budget": 50,
                },
                "evaluations": [{"partial": True}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(InvalidCandidateEvaluationArtifactError):
        read_candidate_evaluation(paths, cache_key=key)


def test_checklist_models_accept_only_closed_outcomes() -> None:
    result = ChecklistResult("rule", "PASS")  # type: ignore[arg-type]
    assert result.outcome is ChecklistOutcome.PASS
    with pytest.raises(ValueError, match="outcome"):
        ChecklistResult("rule", "provider-result")  # type: ignore[arg-type]


def test_run_config_candidate_budget_is_validated(tmp_path: Path) -> None:
    from multicuts.config import RunConfig
    from multicuts.errors import ConfigurationError

    base = RunConfig(
        source="source.mp4",
        output_dir=tmp_path,
        clips=1,
        min_score=0,
        aspect_ratio="original",
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
    )
    assert base.candidate_budget == 50
    with pytest.raises(ConfigurationError, match="candidate_budget"):
        replace(base, candidate_budget=0)


def test_cli_maps_candidate_budget_without_accessing_the_source() -> None:
    config = parse_run_config(["source.mp4", "--candidate-budget", "7"])

    assert config.candidate_budget == 7


def test_pipeline_reuses_candidate_evaluation_without_recomputing_it(
    tmp_path: Path,
) -> None:
    from multicuts.config import RunConfig

    config = RunConfig(
        source="source.mp4",
        output_dir=tmp_path,
        clips=1,
        min_score=0,
        aspect_ratio="original",
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
    )
    source = AcquiredSource(Path("source.mp4"), "sha256-v1:source")
    transcript = _transcript(
        words=tuple(
            Word(f"word{index}", index, index + 0.5, 0.8) for index in range(6)
        ),
    )
    candidates = (_candidate(),)
    calls = 0

    def evaluator(
        candidates: tuple[Candidate, ...],
        transcript: Transcript,
        *,
        min_duration: float,
        max_duration: float,
        candidate_budget: int,
    ):
        nonlocal calls
        calls += 1
        return evaluate_candidates(
            candidates,
            transcript,
            min_duration=min_duration,
            max_duration=max_duration,
            candidate_budget=candidate_budget,
        )

    first = load_or_evaluate_candidates(
        config, source, transcript, candidates, evaluator=evaluator
    )
    second = load_or_evaluate_candidates(
        replace(config, scorer="different", aspect_ratio="9:16"),
        source,
        transcript,
        candidates,
        evaluator=evaluator,
    )

    assert first == second
    assert calls == 1

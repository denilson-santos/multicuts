import json
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.artifacts import prepare_workspace
from multicuts.candidates.refinement import REFINE_VERSION
from multicuts.candidates.refinement_artifacts import (
    InvalidRefinementArtifactError,
    read_refinement,
    refinement_cache_key,
    write_refinement,
)
from multicuts.models import (
    SCORE_DIMENSIONS,
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    RefinedSelection,
    RefinementReason,
    ScoredCandidate,
    ScoreDimension,
    ScoreResult,
    SelectedCandidate,
    SelectionDecision,
    SelectionResult,
    SelectionStatus,
    Transcript,
    TranscriptSegment,
    Word,
)


def _selection() -> SelectionResult:
    candidate = Candidate("candidate-v1:one", 1.0, 3.0, "A useful point.", (0,), "1")
    evaluation = CandidateEvaluation(
        candidate,
        CandidateFeatures(duration=2.0, word_count=3, timed_word_count=3),
        (ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        1,
    )
    score = ScoreResult(
        50.0,
        50.0,
        0.8,
        tuple(ScoreDimension(name, 50.0) for name in SCORE_DIMENSIONS),
        (),
        "Clear candidate",
        1,
        "1",
        "heuristic",
    )
    selected = SelectedCandidate(
        evaluation, ScoredCandidate(candidate.candidate_id, score), 1
    )
    return SelectionResult(
        (selected,),
        (
            SelectionDecision(
                candidate.candidate_id, SelectionStatus.SELECTED, "top_k", 1
            ),
        ),
    )


def _transcript() -> Transcript:
    return Transcript(
        None,
        "en",
        5.0,
        "A useful point.",
        (TranscriptSegment("A useful point.", 1.0, 3.0),),
        (Word("A", 1.0, 1.2), Word("useful", 1.3, 2.0), Word("point.", 2.1, 3.0)),
        "multisubs",
        "4.2.0",
    )


def _key(
    selection: SelectionResult, transcript: Transcript, *, post_roll: float = 0.25
) -> str:
    return refinement_cache_key(
        selection,
        transcript,
        source_fingerprint="sha256-v1:source",
        source_duration=5.0,
        pre_roll=0.15,
        post_roll=post_roll,
        search_radius=0.5,
        pause_threshold=0.4,
    )


def test_refinement_cache_identity_changes_with_timing_and_padding() -> None:
    selection = _selection()
    transcript = _transcript()
    changed_timing = replace(
        transcript,
        words=(replace(transcript.words[0], start=1.05), *transcript.words[1:]),
    )

    assert _key(selection, transcript) != _key(selection, changed_timing)
    assert _key(selection, transcript) != _key(selection, transcript, post_roll=0.3)


def test_refinement_artifact_round_trip_and_rejects_invalid_rescore_state(
    tmp_path: Path,
) -> None:
    selection = _selection()
    source = AcquiredSource(tmp_path / "source.mp4", "sha256-v1:source")
    paths = prepare_workspace(
        tmp_path / "output", source, cache_key="sha256-v1:transcript"
    )
    key = _key(selection, _transcript())
    result = RefinedSelection(
        selection.selected[0],
        0.85,
        3.25,
        0.15,
        0.25,
        (RefinementReason.PADDED,),
        REFINE_VERSION,
        5.0,
        False,
    )

    write_refinement(
        paths,
        (result,),
        cache_key=key,
        selection=selection,
        source_duration=5.0,
        replace=False,
    )
    assert read_refinement(
        paths, cache_key=key, selection=selection, source_duration=5.0
    ) == (result,)

    payload = json.loads(paths.refinement.read_text(encoding="utf-8"))
    payload["results"][0]["requires_rescore"] = True
    paths.refinement.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidRefinementArtifactError, match="interval or state"):
        read_refinement(paths, cache_key=key, selection=selection, source_duration=5.0)

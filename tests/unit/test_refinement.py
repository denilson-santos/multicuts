import pytest

from multicuts.candidates.refinement import REFINE_VERSION, refine_selection
from multicuts.models import (
    Candidate,
    CandidateEvaluation,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    RefinedSelection,
    RefinementReason,
    ScoredCandidate,
    SelectedCandidate,
    SelectionDecision,
    SelectionResult,
    SelectionStatus,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.scoring.heuristic import score_heuristically


def _selected(
    start: float, end: float, *, candidate_id: str = "candidate"
) -> SelectedCandidate:
    candidate = Candidate(candidate_id, start, end, "A complete thought.", (0,), "1")
    evaluation = CandidateEvaluation(
        candidate=candidate,
        features=CandidateFeatures(
            duration=end - start,
            word_count=3,
            timed_word_count=3,
        ),
        checklist=(ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        shortlist_rank=1,
    )
    scored = ScoredCandidate(candidate_id, score_heuristically(evaluation))
    return SelectedCandidate(evaluation, scored, 1)


def _selection(selected: SelectedCandidate) -> SelectionResult:
    return SelectionResult(
        selected=(selected,),
        decisions=(
            SelectionDecision(
                selected.candidate_id,
                SelectionStatus.SELECTED,
                "selected_by_rank",
                rank=selected.rank,
            ),
        ),
    )


def _transcript(
    words: tuple[Word, ...],
    *,
    segments: tuple[TranscriptSegment, ...] = (),
    duration: float = 20.0,
) -> Transcript:
    return Transcript(
        language_requested=None,
        language_detected="en",
        duration=duration,
        text="A complete thought.",
        segments=segments,
        words=words,
        provider="fixture",
        provider_version="1",
    )


def test_word_alignment_adds_padding_without_changing_observed_membership() -> None:
    selected = _selected(5.2, 9.8)
    transcript = _transcript(
        (
            Word("before", 4.0, 4.4),
            Word("A", 5.0, 5.4),
            Word("complete", 7.0, 7.5),
            Word("thought", 9.0, 10.0),
            Word("after", 10.6, 11.0),
        )
    )

    result = refine_selection(
        _selection(selected),
        transcript,
        20.0,
        pre_roll=0.15,
        post_roll=0.25,
        search_radius=0.5,
        pause_threshold=0.4,
    )[0]

    assert result.render_start == pytest.approx(4.85)
    assert result.render_end == pytest.approx(10.25)
    assert result.pre_roll == pytest.approx(0.15)
    assert result.post_roll == pytest.approx(0.25)
    assert RefinementReason.WORD_ALIGNED in result.reasons
    assert RefinementReason.PADDED in result.reasons
    assert not result.requires_rescore
    assert result.selected is selected


def test_pause_alignment_prefers_boundary_inside_configured_neighborhood() -> None:
    selected = _selected(5.7, 9.7)
    transcript = _transcript(
        (
            Word("before", 4.0, 4.5),
            Word("first", 5.0, 5.4),
            Word("second", 6.0, 6.3),
            Word("last", 9.0, 9.5),
            Word("after", 10.1, 10.5),
        )
    )

    result = refine_selection(
        _selection(selected),
        transcript,
        20.0,
        pre_roll=0.0,
        post_roll=0.0,
        search_radius=0.5,
        pause_threshold=0.5,
    )[0]

    assert result.render_start == pytest.approx(6.0)
    assert result.render_end == pytest.approx(9.5)
    assert RefinementReason.PAUSE_ALIGNED in result.reasons


def test_timed_segments_are_used_when_words_have_no_timing() -> None:
    selected = _selected(5.2, 9.8)
    transcript = _transcript(
        (Word("untimed", None, None),),
        segments=(
            TranscriptSegment("before", 4.0, 4.5),
            TranscriptSegment("selected", 5.0, 10.0),
        ),
    )

    result = refine_selection(
        _selection(selected),
        transcript,
        20.0,
        pre_roll=0.0,
        post_roll=0.0,
        search_radius=0.5,
    )[0]

    assert result.render_start == pytest.approx(5.0)
    assert result.render_end == pytest.approx(10.0)
    assert RefinementReason.SEGMENT_ALIGNED in result.reasons
    assert not result.requires_rescore


def test_padding_is_clamped_at_source_edges_and_actual_padding_is_reported() -> None:
    selected = _selected(0.1, 19.8)
    transcript = _transcript(
        (
            Word("first", 0.1, 1.0),
            Word("last", 19.0, 19.8),
        )
    )

    result = refine_selection(
        _selection(selected),
        transcript,
        20.0,
        pre_roll=0.5,
        post_roll=0.5,
        search_radius=0.5,
    )[0]

    assert result.render_start == pytest.approx(0.0)
    assert result.render_end == pytest.approx(20.0)
    assert result.pre_roll == pytest.approx(0.1)
    assert result.post_roll == pytest.approx(0.2)
    assert RefinementReason.CLAMPED in result.reasons


def test_added_word_from_padding_requires_rescore() -> None:
    selected = _selected(5.0, 9.0)
    transcript = _transcript(
        (
            Word("before", 4.7, 4.9),
            Word("first", 5.0, 5.5),
            Word("last", 8.5, 9.0),
            Word("after", 9.1, 9.4),
        )
    )

    result = refine_selection(
        _selection(selected),
        transcript,
        20.0,
        pre_roll=0.2,
        post_roll=0.2,
        search_radius=0.5,
    )[0]

    assert result.render_start == pytest.approx(4.8)
    assert result.render_end == pytest.approx(9.2)
    assert result.requires_rescore
    assert RefinementReason.REQUIRES_RESCORE in result.reasons


def test_padding_beyond_search_radius_checks_full_mixed_membership() -> None:
    selected = _selected(5.0, 9.0)
    transcript = _transcript(
        (
            Word("first", 5.0, 5.5),
            Word("last", 8.5, 9.0),
        ),
        segments=(
            TranscriptSegment("before", 4.0, 4.9),
            TranscriptSegment("selected", 5.0, 9.0),
            TranscriptSegment("after", 9.1, 10.0),
        ),
    )

    result = refine_selection(
        _selection(selected),
        transcript,
        20.0,
        pre_roll=0.2,
        post_roll=0.9,
        search_radius=0.1,
    )[0]

    assert result.render_start == pytest.approx(4.8)
    assert result.render_end == pytest.approx(9.9)
    assert result.requires_rescore
    assert RefinementReason.REQUIRES_RESCORE in result.reasons


def test_missing_timing_keeps_candidate_boundaries_without_fabrication() -> None:
    selected = _selected(5.2, 9.8)
    transcript = _transcript((Word("untimed", None, None),))

    result = refine_selection(
        _selection(selected),
        transcript,
        20.0,
        pre_roll=0.0,
        post_roll=0.0,
    )[0]

    assert result.render_start == pytest.approx(selected.start)
    assert result.render_end == pytest.approx(selected.end)
    assert result.reasons == (RefinementReason.UNCHANGED,)
    assert not result.requires_rescore


def test_missing_timing_suppresses_unverifiable_default_padding() -> None:
    selected = _selected(5.2, 9.8)
    transcript = _transcript((Word("untimed", None, None),))

    result = refine_selection(_selection(selected), transcript, 20.0)[0]

    assert result.render_start == pytest.approx(selected.start)
    assert result.render_end == pytest.approx(selected.end)
    assert result.pre_roll == 0.0
    assert result.post_roll == 0.0
    assert result.reasons == (RefinementReason.UNCHANGED,)
    assert not result.requires_rescore


def test_refined_selection_normalizes_reasons_and_preserves_score_provenance() -> None:
    selected = _selected(5.0, 9.0)
    refined = RefinedSelection(
        selected=selected,
        render_start=4.8,
        render_end=9.2,
        pre_roll=0.2,
        post_roll=0.2,
        reasons=(RefinementReason.PADDED,),
        version=REFINE_VERSION,
        source_duration=20.0,
        requires_rescore=False,
    )

    assert refined.reasons == (RefinementReason.PADDED,)
    assert refined.candidate_id == selected.candidate_id
    assert refined.rank == selected.rank
    assert refined.scored_start == selected.start
    assert refined.scored_end == selected.end
    assert refined.selected.result is selected.result


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("render_start", -0.1),
        ("render_end", 20.1),
        ("pre_roll", -0.1),
        ("pre_roll", 5.0),
        ("post_roll", -0.1),
    ],
)
def test_refined_selection_rejects_invalid_render_contract(
    field: str, value: float
) -> None:
    selected = _selected(5.0, 9.0)
    values: dict[str, object] = {
        "selected": selected,
        "render_start": 4.8,
        "render_end": 9.2,
        "pre_roll": 0.2,
        "post_roll": 0.2,
        "reasons": (RefinementReason.PADDED,),
        "version": REFINE_VERSION,
        "source_duration": 20.0,
        "requires_rescore": False,
    }
    values[field] = value

    with pytest.raises(ValueError):
        RefinedSelection(**values)  # type: ignore[arg-type]


def test_refined_selection_rejects_inconsistent_rescore_state() -> None:
    selected = _selected(5.0, 9.0)

    with pytest.raises(ValueError, match="rescore"):
        RefinedSelection(
            selected=selected,
            render_start=5.0,
            render_end=9.0,
            pre_roll=0.0,
            post_roll=0.0,
            reasons=(RefinementReason.REQUIRES_RESCORE,),
            version=REFINE_VERSION,
            source_duration=20.0,
            requires_rescore=False,
        )


def test_refinement_is_deterministic_for_reversed_transcript_tie_inputs() -> None:
    selected = _selected(5.2, 9.8)
    transcript = _transcript(
        (
            Word("first", 5.0, 5.4),
            Word("last", 9.4, 10.0),
        )
    )

    first = refine_selection(_selection(selected), transcript, 20.0)
    second = refine_selection(_selection(selected), transcript, 20.0)

    assert first == second

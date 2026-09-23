import pytest

from multicuts.candidates.refinement import REFINE_VERSION
from multicuts.models import (
    Candidate,
    CandidateEvaluation,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    ClipTranscript,
    RefinedSelection,
    RefinementReason,
    ScoredCandidate,
    SelectedCandidate,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.scoring.heuristic import score_heuristically
from multicuts.transcripts import (
    CLIP_TRANSCRIPT_VERSION,
    derive_clip_local_transcript,
    derive_clip_transcript,
)


def _refined(
    start: float, end: float, *, source_duration: float = 10.0
) -> RefinedSelection:
    candidate = Candidate("candidate-v1:test", start, end, "selected text", (0,), "1")
    evaluation = CandidateEvaluation(
        candidate=candidate,
        features=CandidateFeatures(
            duration=end - start, word_count=2, timed_word_count=2
        ),
        checklist=(ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        shortlist_rank=1,
    )
    selected = SelectedCandidate(
        evaluation=evaluation,
        scored=ScoredCandidate(candidate.candidate_id, score_heuristically(evaluation)),
        rank=1,
    )
    return RefinedSelection(
        selected=selected,
        render_start=start,
        render_end=end,
        pre_roll=0.0,
        post_roll=0.0,
        reasons=(RefinementReason.UNCHANGED,),
        version=REFINE_VERSION,
        source_duration=source_duration,
        requires_rescore=False,
    )


def _transcript(
    segments: tuple[TranscriptSegment, ...],
    words: tuple[Word, ...],
    *,
    duration: float = 10.0,
) -> Transcript:
    return Transcript(
        language_requested=None,
        language_detected="en",
        duration=duration,
        text=" ".join(segment.text for segment in segments),
        segments=segments,
        words=words,
        provider="fixture",
        provider_version="provider-1",
    )


def test_derivation_shifts_clamps_and_preserves_source_relationships() -> None:
    transcript = _transcript(
        segments=(
            TranscriptSegment("before", 0.0, 2.0),
            TranscriptSegment("opening", 1.5, 2.5),
            TranscriptSegment("selected", 2.5, 4.8),
            TranscriptSegment("after", 5.0, 6.0),
        ),
        words=(
            Word("opening", 1.5, 2.5, 0.9),
            Word("selected", 2.5, 3.0, 0.8),
            Word("after", 5.0, 5.5, 0.7),
        ),
    )

    result = derive_clip_transcript(transcript, _refined(2.0, 5.0))

    assert result.duration == 3.0
    assert (result.source_start, result.source_end) == (2.0, 5.0)
    assert [segment.source_index for segment in result.segments] == [1, 2]
    assert [(segment.start, segment.end) for segment in result.segments] == [
        (0.0, 0.5),
        (0.5, 2.8),
    ]
    assert [word.source_index for word in result.words] == [0, 1]
    assert [(word.start, word.end) for word in result.words] == [
        (0.0, 0.5),
        (0.5, 1.0),
    ]
    assert [word.source_segment_index for word in result.words] == [1, 2]
    assert result.text == "opening selected"
    assert result.word_animation_safe
    assert CLIP_TRANSCRIPT_VERSION == "clip-transcript-v1"


def test_exact_boundaries_use_a_half_open_policy_with_tolerance() -> None:
    transcript = _transcript(
        segments=(
            TranscriptSegment("ends at start", 1.0, 2.0),
            TranscriptSegment("inside", 2.0, 3.0),
            TranscriptSegment("starts at end", 5.0, 6.0),
        ),
        words=(
            Word("ends", 1.0, 2.0),
            Word("inside", 2.0, 3.0),
            Word("starts", 5.0, 6.0),
        ),
    )

    result = derive_clip_transcript(transcript, _refined(2.0, 5.0))

    assert [segment.source_index for segment in result.segments] == [1]
    assert [word.source_index for word in result.words] == [1]
    assert result.words[0].start == 0.0


@pytest.mark.parametrize(
    ("overlap", "included"),
    [
        (0.5e-9, False),
        (2.0e-9, True),
    ],
)
def test_boundary_overlap_uses_explicit_float_tolerance(
    overlap: float, included: bool
) -> None:
    transcript = _transcript(
        segments=(TranscriptSegment("boundary", 1.0, 2.0 + overlap),),
        words=(Word("boundary", 1.0, 2.0 + overlap),),
    )

    result = derive_clip_transcript(transcript, _refined(2.0, 5.0))

    assert bool(result.segments) is included
    assert bool(result.words) is included
    if included:
        assert result.segments[0].end == pytest.approx(overlap)
        assert result.words[0].end == pytest.approx(overlap)


def test_missing_timing_is_not_invented_and_empty_span_is_explicit() -> None:
    transcript = _transcript(
        segments=(TranscriptSegment("unknown", None, None),),
        words=(Word("unknown", None, None),),
    )

    result = derive_clip_local_transcript(transcript, _refined(2.0, 5.0))

    assert result.is_empty
    assert result.text == ""
    assert result.segments == ()
    assert result.words == ()
    assert not result.word_animation_safe
    assert not result.word_timing_complete


def test_derivation_is_deterministically_serializable() -> None:
    import json
    from dataclasses import asdict

    transcript = _transcript(
        segments=(TranscriptSegment("selected", 2.0, 4.0),),
        words=(Word("selected", 2.0, 2.5, 0.9),),
    )

    first = derive_clip_transcript(transcript, _refined(2.0, 5.0))
    second = derive_clip_transcript(transcript, _refined(2.0, 5.0))

    def encode(value: ClipTranscript) -> str:
        return json.dumps(
            asdict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    assert encode(first) == encode(second)


def test_clip_transcript_rejects_invalid_local_timestamps_and_parent() -> None:
    from multicuts.models import (
        ClipTranscript,
        ClipTranscriptSegment,
        ClipTranscriptWord,
    )

    segment = ClipTranscriptSegment("selected", 0.0, 1.0, 4)
    word = ClipTranscriptWord("selected", 0.0, 0.5, None, 9, 4)

    ClipTranscript(
        None,
        "en",
        2.0,
        3.0,
        5.0,
        10.0,
        "selected",
        (segment,),
        (word,),
        "fixture",
        "provider-1",
        True,
    )

    bad_word = ClipTranscriptWord("bad", 2.0, 2.1, None, 9, 4)
    try:
        ClipTranscript(
            None,
            "en",
            2.0,
            3.0,
            5.0,
            10.0,
            "bad",
            (segment,),
            (bad_word,),
            "fixture",
            "provider-1",
            True,
        )
    except ValueError as exc:
        assert "clip-local" in str(exc)
    else:
        raise AssertionError("out-of-range local timestamp was accepted")

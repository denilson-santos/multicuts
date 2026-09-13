from dataclasses import replace

import pytest

from multicuts.candidates.generator import (
    CANDIDATE_GENERATOR_VERSION,
    SEMANTIC_PAUSE_THRESHOLD_SECONDS,
    build_semantic_units,
    candidate_id,
    generate_candidate_windows,
    generate_candidates,
)
from multicuts.models import (
    Candidate,
    SemanticUnit,
    Transcript,
    TranscriptSegment,
    Word,
)


def _transcript(
    *,
    duration: float = 90.0,
    segments: tuple[TranscriptSegment, ...] = (),
    words: tuple[Word, ...] = (),
    text: str = "Transcript text",
) -> Transcript:
    return Transcript(
        language_requested=None,
        language_detected="en",
        duration=duration,
        text=text,
        segments=segments,
        words=words,
        provider="multisubs",
        provider_version="4.1.0",
    )


def test_candidate_identity_is_stable_and_uses_every_required_input() -> None:
    identity = candidate_id("sha256-v1:abc", 1.25, 31.5)

    assert identity == candidate_id("sha256-v1:abc", 1.25, 31.5)
    assert identity.startswith(f"candidate-v{CANDIDATE_GENERATOR_VERSION}:")
    assert identity != candidate_id("sha256-v1:other", 1.25, 31.5)
    assert identity != candidate_id("sha256-v1:abc", 1.2500000000000002, 31.5)
    assert identity != candidate_id("sha256-v1:abc", 1.25, 31.6)
    assert identity != candidate_id("sha256-v1:abc", 1.25, 31.5, generator_version="2")
    assert candidate_id("sha256-v1:abc", -0.0, 31.5) == candidate_id(
        "sha256-v1:abc", 0.0, 31.5
    )


@pytest.mark.parametrize(
    ("fingerprint", "start", "end", "version"),
    [
        ("", 0.0, 1.0, "1"),
        ("source", -1.0, 1.0, "1"),
        ("source", 1.0, 1.0, "1"),
        ("source", 2.0, 1.0, "1"),
        ("source", float("nan"), 1.0, "1"),
        ("source", 0.0, 1.0, ""),
    ],
)
def test_candidate_identity_rejects_invalid_inputs(
    fingerprint: str, start: float, end: float, version: str
) -> None:
    with pytest.raises(ValueError):
        candidate_id(fingerprint, start, end, generator_version=version)


def test_semantic_units_use_segment_sentences_and_measured_pauses() -> None:
    transcript = _transcript(
        duration=20.0,
        text="A setup continues. A second idea.",
        segments=(
            TranscriptSegment("A setup", 0.0, 3.0),
            TranscriptSegment("continues.", 3.2, 6.0),
            TranscriptSegment("A second", 6.2, 8.0),
            TranscriptSegment("idea.", 9.0, 11.0),
        ),
    )

    assert build_semantic_units(transcript) == (
        SemanticUnit("A setup continues.", 0.0, 6.0),
        SemanticUnit("A second", 6.2, 8.0),
        SemanticUnit("idea.", 9.0, 11.0),
    )


def test_semantic_units_merge_overlaps_without_changing_observed_bounds() -> None:
    transcript = _transcript(
        duration=5.0,
        segments=(
            TranscriptSegment("First.", 0.0, 2.0),
            TranscriptSegment("Overlap.", 1.5, 3.0),
        ),
    )

    assert build_semantic_units(transcript) == (
        SemanticUnit("First. Overlap.", 0.0, 3.0),
    )


def test_semantic_units_fall_back_to_timed_words() -> None:
    transcript = _transcript(
        duration=8.0,
        text="Hello world. Next",
        segments=(TranscriptSegment("Hello world. Next", None, None),),
        words=(
            Word("Hello", 0.0, 0.8),
            Word("world.", 0.9, 1.8),
            Word("untimed", None, None),
            Word("Next", 3.0, 4.0),
        ),
    )

    assert build_semantic_units(transcript) == (
        SemanticUnit("Hello world.", 0.0, 1.8),
        SemanticUnit("Next", 3.0, 4.0),
    )


def test_semantic_units_prefer_timed_segments_over_partial_word_data() -> None:
    transcript = _transcript(
        duration=8.0,
        text="Olá mundo. 世界!",
        segments=(
            TranscriptSegment("Olá mundo.", 0.0, 2.0),
            TranscriptSegment("世界!", None, None),
        ),
        words=(Word("different", 4.0, 5.0),),
    )

    assert build_semantic_units(transcript) == (SemanticUnit("Olá mundo.", 0.0, 2.0),)


def test_semantic_units_do_not_invent_timing() -> None:
    transcript = _transcript(
        segments=(TranscriptSegment("Untimed", None, None),),
        words=(Word("Untimed", None, None),),
    )

    assert build_semantic_units(transcript) == ()


def test_semantic_units_preserve_multilingual_segment_text() -> None:
    transcript = _transcript(
        duration=8.0,
        text="Olá mundo. 世界!",
        segments=(
            TranscriptSegment("Olá mundo.", 0.0, 2.0),
            TranscriptSegment("世界!", 2.1, 4.0),
        ),
    )

    assert build_semantic_units(transcript) == (
        SemanticUnit("Olá mundo.", 0.0, 2.0),
        SemanticUnit("世界!", 2.1, 4.0),
    )


@pytest.mark.parametrize(
    "transcript",
    [
        _transcript(
            duration=3.0,
            segments=(TranscriptSegment("Too late", 1.0, 4.0),),
        ),
        _transcript(
            segments=(
                TranscriptSegment("Later", 2.0, 3.0),
                TranscriptSegment("Earlier", 1.0, 1.5),
            ),
        ),
        _transcript(
            duration=3.0,
            segments=(TranscriptSegment("Untimed", None, None),),
            words=(Word("Too late", 1.0, 4.0),),
        ),
    ],
)
def test_semantic_units_reject_inconsistent_observed_timing(
    transcript: Transcript,
) -> None:
    with pytest.raises(ValueError):
        build_semantic_units(transcript)


@pytest.mark.parametrize("pause_threshold", [0.0, -1.0, float("inf")])
def test_semantic_units_reject_invalid_pause_threshold(
    pause_threshold: float,
) -> None:
    with pytest.raises(ValueError):
        build_semantic_units(_transcript(), pause_threshold=pause_threshold)


def test_candidate_windows_are_adjacent_bounded_and_preferred_first() -> None:
    units = (
        SemanticUnit("One.", 0.0, 10.0),
        SemanticUnit("Two.", 10.0, 26.0),
        SemanticUnit("Three.", 26.0, 45.0),
        SemanticUnit("Four.", 45.0, 61.0),
    )

    candidates = generate_candidate_windows(
        units,
        source_fingerprint="sha256-v1:abc",
        min_duration=15.0,
        max_duration=45.0,
    )

    assert candidates
    assert all(
        15.0 <= candidate.end - candidate.start <= 45.0 for candidate in candidates
    )
    assert candidates[0].start == 10.0
    assert candidates[0].end == 45.0
    assert candidates[0].unit_indexes == (1, 2)
    assert candidates[0].text == "Two. Three."
    assert [candidate.candidate_id for candidate in candidates] == [
        candidate.candidate_id
        for candidate in generate_candidate_windows(
            units,
            source_fingerprint="sha256-v1:abc",
            min_duration=15.0,
            max_duration=45.0,
        )
    ]


def test_candidate_windows_include_exact_minimum_and_maximum() -> None:
    candidates = generate_candidate_windows(
        (
            SemanticUnit("Minimum.", 0.0, 15.0),
            SemanticUnit("Rest.", 15.0, 60.0),
        ),
        source_fingerprint="sha256-v1:abc",
        min_duration=15.0,
        max_duration=60.0,
    )

    intervals = {(candidate.start, candidate.end) for candidate in candidates}
    assert (0.0, 15.0) in intervals
    assert (0.0, 60.0) in intervals


def test_repeated_text_at_different_intervals_has_distinct_identity() -> None:
    candidates = generate_candidate_windows(
        (
            SemanticUnit("Repeated.", 0.0, 20.0),
            SemanticUnit("Repeated.", 20.0, 40.0),
        ),
        source_fingerprint="sha256-v1:abc",
        min_duration=15.0,
        max_duration=20.0,
    )

    assert len(candidates) == 2
    assert candidates[0].text == candidates[1].text
    assert candidates[0].candidate_id != candidates[1].candidate_id


@pytest.mark.parametrize(
    ("min_duration", "max_duration"),
    [(0.0, 1.0), (2.0, 1.0), (1.0, float("inf"))],
)
def test_candidate_windows_reject_invalid_duration_limits(
    min_duration: float, max_duration: float
) -> None:
    with pytest.raises(ValueError):
        generate_candidate_windows(
            (),
            source_fingerprint="sha256-v1:abc",
            min_duration=min_duration,
            max_duration=max_duration,
        )


def test_candidate_windows_reject_overlapping_units() -> None:
    with pytest.raises(ValueError, match="ordered and non-overlapping"):
        generate_candidate_windows(
            (
                SemanticUnit("First", 0.0, 10.0),
                SemanticUnit("Second", 9.0, 20.0),
            ),
            source_fingerprint="sha256-v1:abc",
            min_duration=5.0,
            max_duration=20.0,
        )


def test_generate_candidates_returns_empty_for_short_timed_transcript() -> None:
    transcript = _transcript(
        duration=12.0,
        segments=(TranscriptSegment("Short complete thought.", 0.0, 12.0),),
    )

    assert (
        generate_candidates(
            transcript,
            source_fingerprint="sha256-v1:abc",
            min_duration=15.0,
            max_duration=60.0,
        )
        == ()
    )


def test_models_reject_invalid_candidate_relationships() -> None:
    valid = Candidate(
        candidate_id="candidate-v1:abc",
        start=0.0,
        end=30.0,
        text="Valid text",
        unit_indexes=(0, 1),
        generator_version="1",
    )
    assert replace(valid, unit_indexes=(4, 5)).unit_indexes == (4, 5)

    with pytest.raises(ValueError, match="contiguous"):
        replace(valid, unit_indexes=(0, 2))
    with pytest.raises(ValueError, match="nonempty tuple"):
        replace(valid, unit_indexes=())
    with pytest.raises(ValueError, match="candidate ID"):
        replace(valid, candidate_id="")
    with pytest.raises(ValueError, match="candidate text"):
        replace(valid, text=" ")
    with pytest.raises(ValueError, match="generator version"):
        replace(valid, generator_version="")
    with pytest.raises(ValueError, match="finite, ordered"):
        replace(valid, start=30.0)


def test_semantic_unit_model_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="text"):
        SemanticUnit(" ", 0.0, 1.0)
    with pytest.raises(ValueError, match="finite, ordered"):
        SemanticUnit("Text", 1.0, 1.0)


def test_pause_threshold_is_an_explicit_versioned_heuristic() -> None:
    assert SEMANTIC_PAUSE_THRESHOLD_SECONDS == 0.75
    assert CANDIDATE_GENERATOR_VERSION == "1"

"""Pure derivation of clip-local transcript timelines."""

from __future__ import annotations

from math import isfinite

from multicuts.models import (
    ClipTranscript,
    ClipTranscriptSegment,
    ClipTranscriptWord,
    RefinedSelection,
    Transcript,
)

CLIP_TRANSCRIPT_VERSION = "clip-transcript-v1"
_DEFAULT_BOUNDARY_TOLERANCE = 1e-9


def _validate_tolerance(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
    ):
        raise ValueError(
            "clip transcript boundary tolerance must be finite and non-negative"
        )
    return float(value)


def _intersects(
    start: float, end: float, window_start: float, window_end: float, tolerance: float
) -> bool:
    """Use a half-open interval with tolerance at both exact boundaries."""
    return start < window_end - tolerance and end > window_start + tolerance


def _local_interval(
    start: float,
    end: float,
    *,
    source_start: float,
    duration: float,
    tolerance: float,
) -> tuple[float, float] | None:
    local_start = max(0.0, min(duration, start - source_start))
    local_end = max(0.0, min(duration, end - source_start))
    if local_end <= local_start + tolerance:
        return None
    return local_start, local_end


def _parent_segment_index(
    word_start: float,
    word_end: float,
    segments: tuple[tuple[int, float, float], ...],
    tolerance: float,
) -> int | None:
    candidates = [
        (source_index, min(word_end, end) - max(word_start, start))
        for source_index, start, end in segments
        if _intersects(word_start, word_end, start, end, tolerance)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[1], -candidate[0]))[0]


def derive_clip_transcript(
    transcript: Transcript,
    refined: RefinedSelection,
    *,
    tolerance: float = _DEFAULT_BOUNDARY_TOLERANCE,
) -> ClipTranscript:
    """Derive one clip timeline from observed source transcript timestamps.

    Timed source elements use a half-open intersection policy: an element
    ending at the clip start or beginning at the clip end is excluded. Values
    that straddle a boundary are retained and clamped after shifting. Untimed
    source elements are omitted because their membership in a partial clip
    cannot be established without inventing timing. The source and provider
    metadata remain attached to the returned value.
    """
    if not isinstance(transcript, Transcript):
        raise ValueError("clip transcript source must be a Transcript")
    if not isinstance(refined, RefinedSelection):
        raise ValueError("clip transcript interval must be a RefinedSelection")
    boundary_tolerance = _validate_tolerance(tolerance)

    source_start = float(refined.render_start)
    source_end = float(refined.render_end)
    duration = source_end - source_start
    if duration <= boundary_tolerance:
        raise ValueError("refined interval is too short for a clip transcript")

    source_segments = tuple(
        (index, segment.start, segment.end)
        for index, segment in enumerate(transcript.segments)
        if segment.start is not None and segment.end is not None
    )
    selected_segment_ranges = tuple(
        (index, start, end)
        for index, start, end in source_segments
        if _intersects(start, end, source_start, source_end, boundary_tolerance)
    )

    segments: list[ClipTranscriptSegment] = []
    for index, segment in enumerate(transcript.segments):
        if segment.start is None or segment.end is None:
            continue
        if not _intersects(
            segment.start,
            segment.end,
            source_start,
            source_end,
            boundary_tolerance,
        ):
            continue
        local = _local_interval(
            segment.start,
            segment.end,
            source_start=source_start,
            duration=duration,
            tolerance=boundary_tolerance,
        )
        if local is None:
            continue
        segments.append(
            ClipTranscriptSegment(
                text=segment.text,
                start=local[0],
                end=local[1],
                source_index=index,
            )
        )

    words: list[ClipTranscriptWord] = []
    for index, word in enumerate(transcript.words):
        if word.start is None or word.end is None:
            continue
        if not _intersects(
            word.start,
            word.end,
            source_start,
            source_end,
            boundary_tolerance,
        ):
            continue
        local = _local_interval(
            word.start,
            word.end,
            source_start=source_start,
            duration=duration,
            tolerance=boundary_tolerance,
        )
        if local is None:
            continue
        words.append(
            ClipTranscriptWord(
                text=word.text,
                start=local[0],
                end=local[1],
                confidence=word.confidence,
                source_index=index,
                source_segment_index=_parent_segment_index(
                    word.start,
                    word.end,
                    selected_segment_ranges,
                    boundary_tolerance,
                ),
            )
        )

    if segments:
        text = " ".join(segment.text.strip() for segment in segments)
    else:
        text = " ".join(word.text.strip() for word in words)
    return ClipTranscript(
        language_requested=transcript.language_requested,
        language_detected=transcript.language_detected,
        duration=duration,
        source_start=source_start,
        source_end=source_end,
        source_duration=refined.source_duration,
        text=text,
        segments=tuple(segments),
        words=tuple(words),
        provider=transcript.provider,
        provider_version=transcript.provider_version,
        word_timing_complete=bool(transcript.words)
        and all(
            word.start is not None and word.end is not None for word in transcript.words
        ),
    )


# Keep the operation discoverable under the wording used by the rendering
# architecture while retaining one implementation and one validation contract.
derive_clip_local_transcript = derive_clip_transcript
build_clip_transcript = derive_clip_transcript

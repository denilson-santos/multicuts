"""Build semantic transcript units and bounded candidate windows."""

from __future__ import annotations

import hashlib
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from multicuts.models import Candidate, SemanticUnit, Transcript

CANDIDATE_GENERATOR_VERSION = "1"
SEMANTIC_PAUSE_THRESHOLD_SECONDS = 0.75
PREFERRED_DURATION_MIN_SECONDS = 25.0
PREFERRED_DURATION_MAX_SECONDS = 45.0
_PREFERRED_DURATION_MIDPOINT_SECONDS = 35.0
_SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？", "…")


@dataclass(frozen=True, slots=True)
class _TimedText:
    text: str
    start: float
    end: float


def _validate_pause_threshold(pause_threshold: float) -> None:
    if not isfinite(pause_threshold) or pause_threshold <= 0:
        raise ValueError("pause threshold must be finite and positive")


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


def _join_text(parts: Sequence[str]) -> str:
    return " ".join(part.strip() for part in parts if part.strip())


def _timed_segment_items(transcript: Transcript) -> tuple[_TimedText, ...]:
    items: list[_TimedText] = []
    previous_start = -1.0
    for segment in transcript.segments:
        if segment.start is None or segment.end is None:
            continue
        if segment.start < previous_start:
            raise ValueError("timed transcript segments must be in source order")
        if segment.end > transcript.duration:
            raise ValueError("timed transcript segment exceeds transcript duration")
        items.append(_TimedText(segment.text.strip(), segment.start, segment.end))
        previous_start = segment.start
    return tuple(items)


def _timed_word_items(transcript: Transcript) -> tuple[_TimedText, ...]:
    items: list[_TimedText] = []
    previous_start = -1.0
    for word in transcript.words:
        if word.start is None or word.end is None:
            continue
        if word.start < previous_start:
            raise ValueError("timed transcript words must be in source order")
        if word.end > transcript.duration:
            raise ValueError("timed transcript word exceeds transcript duration")
        items.append(_TimedText(word.text.strip(), word.start, word.end))
        previous_start = word.start
    return tuple(items)


def _semantic_units_from_items(
    items: Sequence[_TimedText], *, pause_threshold: float
) -> tuple[SemanticUnit, ...]:
    if not items:
        return ()

    units: list[SemanticUnit] = []
    start = items[0].start
    end = items[0].end
    texts = [items[0].text]

    for item in items[1:]:
        gap = item.start - end
        overlaps = gap < 0
        follows_boundary = texts[-1].rstrip().endswith(_SENTENCE_ENDINGS)
        if not overlaps and (follows_boundary or gap >= pause_threshold):
            units.append(SemanticUnit(_join_text(texts), start, end))
            start = item.start
            end = item.end
            texts = [item.text]
            continue

        texts.append(item.text)
        end = max(end, item.end)

    units.append(SemanticUnit(_join_text(texts), start, end))
    return tuple(units)


def build_semantic_units(
    transcript: Transcript,
    *,
    pause_threshold: float = SEMANTIC_PAUSE_THRESHOLD_SECONDS,
) -> tuple[SemanticUnit, ...]:
    """Group observed timed text at sentence or measured-pause boundaries.

    Provider-normalized segments are authoritative when at least one is timed.
    Timed words are a fallback only when no segment has usable timing. Untimed
    content remains untimed and is therefore excluded instead of being assigned
    invented boundaries.
    """
    _validate_pause_threshold(pause_threshold)
    items = _timed_segment_items(transcript)
    if not items:
        items = _timed_word_items(transcript)
    return _semantic_units_from_items(items, pause_threshold=pause_threshold)


def candidate_id(
    source_fingerprint: str,
    start: float,
    end: float,
    *,
    generator_version: str = CANDIDATE_GENERATOR_VERSION,
) -> str:
    """Return an exact, platform-independent identity for a source interval."""
    if not source_fingerprint.strip():
        raise ValueError("source fingerprint must not be empty")
    if not generator_version.strip():
        raise ValueError("candidate generator version must not be empty")
    if not isfinite(start) or not isfinite(end) or start < 0 or end <= start:
        raise ValueError("candidate interval must have finite, ordered seconds")
    canonical_start = 0.0 if start == 0 else float(start)
    canonical_end = float(end)
    identity = "\0".join(
        (
            source_fingerprint,
            canonical_start.hex(),
            canonical_end.hex(),
            generator_version,
        )
    ).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    return f"candidate-v{generator_version}:{digest}"


def _validate_unit_order(units: Sequence[SemanticUnit]) -> None:
    previous_end = -1.0
    for unit in units:
        if unit.start < previous_end:
            raise ValueError("semantic units must be ordered and non-overlapping")
        previous_end = unit.end


def _candidate_preference(
    candidate: Candidate,
) -> tuple[bool, float, float, float, str]:
    duration = candidate.end - candidate.start
    outside_preferred = not (
        PREFERRED_DURATION_MIN_SECONDS <= duration <= PREFERRED_DURATION_MAX_SECONDS
    )
    return (
        outside_preferred,
        abs(duration - _PREFERRED_DURATION_MIDPOINT_SECONDS),
        candidate.start,
        candidate.end,
        candidate.candidate_id,
    )


def _candidate_end_indexes(
    unit_ends: Sequence[float],
    *,
    start_index: int,
    start: float,
    min_duration: float,
    max_duration: float,
) -> tuple[int, ...]:
    preferred_targets = (
        min_duration,
        PREFERRED_DURATION_MIN_SECONDS,
        _PREFERRED_DURATION_MIDPOINT_SECONDS,
        PREFERRED_DURATION_MAX_SECONDS,
        max_duration,
    )
    targets = {
        min(max_duration, max(min_duration, target)) for target in preferred_targets
    }
    selected: set[int] = set()
    for target in sorted(targets):
        insertion_index = bisect_left(unit_ends, start + target, lo=start_index)
        possible_indexes = (
            insertion_index - 1,
            insertion_index,
        )
        valid_indexes = [
            index
            for index in possible_indexes
            if start_index <= index < len(unit_ends)
            and min_duration <= unit_ends[index] - start <= max_duration
        ]
        if valid_indexes:
            selected.add(
                min(
                    valid_indexes,
                    key=lambda index: (
                        abs((unit_ends[index] - start) - target),
                        unit_ends[index],
                    ),
                )
            )
    return tuple(sorted(selected))


def generate_candidate_windows(
    units: Sequence[SemanticUnit],
    *,
    source_fingerprint: str,
    min_duration: float,
    max_duration: float,
    generator_version: str = CANDIDATE_GENERATOR_VERSION,
) -> tuple[Candidate, ...]:
    """Combine adjacent semantic units into valid candidate windows."""
    _validate_duration_limits(min_duration, max_duration)
    if not source_fingerprint.strip():
        raise ValueError("source fingerprint must not be empty")
    if not generator_version.strip():
        raise ValueError("candidate generator version must not be empty")
    _validate_unit_order(units)

    candidates: list[Candidate] = []
    seen_intervals: set[tuple[str, str]] = set()
    unit_ends = tuple(unit.end for unit in units)
    for start_index, first in enumerate(units):
        end_indexes = _candidate_end_indexes(
            unit_ends,
            start_index=start_index,
            start=first.start,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        for end_index in end_indexes:
            last = units[end_index]
            interval_key = (first.start.hex(), last.end.hex())
            if interval_key in seen_intervals:
                continue
            seen_intervals.add(interval_key)
            window_units = units[start_index : end_index + 1]
            candidates.append(
                Candidate(
                    candidate_id=candidate_id(
                        source_fingerprint,
                        first.start,
                        last.end,
                        generator_version=generator_version,
                    ),
                    start=first.start,
                    end=last.end,
                    text=_join_text(tuple(unit.text for unit in window_units)),
                    unit_indexes=tuple(range(start_index, end_index + 1)),
                    generator_version=generator_version,
                )
            )

    return tuple(sorted(candidates, key=_candidate_preference))


def generate_candidates(
    transcript: Transcript,
    *,
    source_fingerprint: str,
    min_duration: float,
    max_duration: float,
) -> tuple[Candidate, ...]:
    """Build semantic units and return bounded candidates for one source."""
    segment_items = _timed_segment_items(transcript)
    if segment_items:
        units = _semantic_units_from_items(
            segment_items, pause_threshold=SEMANTIC_PAUSE_THRESHOLD_SECONDS
        )
        candidates = generate_candidate_windows(
            units,
            source_fingerprint=source_fingerprint,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        if not candidates:
            word_items = _timed_word_items(transcript)
            if word_items:
                word_units = _semantic_units_from_items(
                    word_items, pause_threshold=SEMANTIC_PAUSE_THRESHOLD_SECONDS
                )
                candidates = generate_candidate_windows(
                    word_units,
                    source_fingerprint=source_fingerprint,
                    min_duration=min_duration,
                    max_duration=max_duration,
                )
    else:
        units = _semantic_units_from_items(
            _timed_word_items(transcript),
            pause_threshold=SEMANTIC_PAUSE_THRESHOLD_SECONDS,
        )
        candidates = generate_candidate_windows(
            units,
            source_fingerprint=source_fingerprint,
            min_duration=min_duration,
            max_duration=max_duration,
        )
    if any(candidate.end > transcript.duration for candidate in candidates):
        raise ValueError("candidate interval exceeds transcript duration")
    return candidates

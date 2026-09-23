"""Pure, bounded refinement of selected transcript boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite

from multicuts.models import (
    RefinedSelection,
    RefinementReason,
    SelectedCandidate,
    SelectionResult,
    Transcript,
)

REFINE_VERSION = "boundary-refinement-v1"
_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class _TimedUnit:
    """One observed transcript interval used as a refinement boundary."""

    index: int
    start: float
    end: float
    reason: RefinementReason


@dataclass(frozen=True, slots=True)
class _Boundary:
    """One deterministic candidate for a semantic boundary."""

    value: float
    reason: RefinementReason


def _validate_non_negative(value: float, name: str, *, positive: bool = False) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {qualifier}")


def _unit_intersects_window(
    unit: _TimedUnit, window_start: float, window_end: float
) -> bool:
    return unit.start < window_end and unit.end > window_start


def _timed_words(
    transcript: Transcript, source_duration: float
) -> tuple[_TimedUnit, ...]:
    units: list[_TimedUnit] = []
    for index, word in enumerate(transcript.words):
        if word.start is None or word.end is None:
            continue
        start = max(0.0, word.start)
        end = min(source_duration, word.end)
        if end > start:
            units.append(_TimedUnit(index, start, end, RefinementReason.WORD_ALIGNED))
    return tuple(sorted(units, key=lambda unit: (unit.start, unit.end, unit.index)))


def _timed_segments(
    transcript: Transcript, source_duration: float
) -> tuple[_TimedUnit, ...]:
    units: list[_TimedUnit] = []
    for index, segment in enumerate(transcript.segments):
        if segment.start is None or segment.end is None:
            continue
        start = max(0.0, segment.start)
        end = min(source_duration, segment.end)
        if end > start:
            units.append(
                _TimedUnit(index, start, end, RefinementReason.SEGMENT_ALIGNED)
            )
    return tuple(sorted(units, key=lambda unit: (unit.start, unit.end, unit.index)))


def _membership(
    units: Iterable[_TimedUnit], start: float, end: float
) -> frozenset[int]:
    """Return observed transcript indexes inside a half-open interval."""
    return frozenset(
        unit.index for unit in units if unit.start < end and unit.end > start
    )


def _pause_boundaries(
    units: tuple[_TimedUnit, ...], pause_threshold: float
) -> tuple[tuple[float, float], ...]:
    """Return (start, end) pause boundaries for each observed gap."""
    if len(units) < 2:
        return ()
    pauses: list[tuple[float, float]] = []
    previous_end = units[0].end
    for unit in units[1:]:
        gap = unit.start - previous_end
        if gap >= pause_threshold and gap >= 0:
            pauses.append((unit.start, previous_end))
        previous_end = max(previous_end, unit.end)
    return tuple(pauses)


def _near(value: float, origin: float, radius: float) -> bool:
    return origin - radius - _EPSILON <= value <= origin + radius + _EPSILON


def _boundary_candidates(
    units: tuple[_TimedUnit, ...],
    origin: float,
    *,
    start: bool,
    radius: float,
    pause_threshold: float,
    source_duration: float,
) -> tuple[_Boundary, ...]:
    candidates: list[_Boundary] = [_Boundary(origin, RefinementReason.UNCHANGED)]
    for unit in units:
        value = unit.start if start else unit.end
        if _near(value, origin, radius) and 0 <= value <= source_duration:
            candidates.append(_Boundary(value, unit.reason))
    for pause_start, pause_end in _pause_boundaries(units, pause_threshold):
        value = pause_start if start else pause_end
        if _near(value, origin, radius) and 0 <= value <= source_duration:
            candidates.append(_Boundary(value, RefinementReason.PAUSE_ALIGNED))
    return tuple(candidates)


def _choose_boundary(
    candidates: tuple[_Boundary, ...],
    units: tuple[_TimedUnit, ...],
    *,
    origin: float,
    other_boundary: float,
    start: bool,
) -> tuple[float, RefinementReason]:
    original_membership = (
        _membership(units, origin, other_boundary)
        if start
        else _membership(units, other_boundary, origin)
    )
    valid: list[tuple[tuple[object, ...], _Boundary]] = []
    for candidate in candidates:
        if start and candidate.value >= other_boundary:
            continue
        if not start and candidate.value <= other_boundary:
            continue
        candidate_membership = (
            _membership(units, candidate.value, other_boundary)
            if start
            else _membership(units, other_boundary, candidate.value)
        )
        changed = candidate_membership != original_membership
        if candidate.reason is RefinementReason.PAUSE_ALIGNED:
            direction = (
                0
                if (candidate.value > origin if start else candidate.value < origin)
                else 1
            )
        else:
            direction = (
                0
                if (candidate.value < origin if start else candidate.value > origin)
                else 1
            )
        priority = {
            RefinementReason.UNCHANGED: 0,
            RefinementReason.PAUSE_ALIGNED: 1,
            RefinementReason.WORD_ALIGNED: 2,
            RefinementReason.SEGMENT_ALIGNED: 3,
        }.get(candidate.reason, 4)
        key: tuple[object, ...] = (
            changed,
            candidate.reason is RefinementReason.UNCHANGED,
            abs(candidate.value - origin),
            direction,
            priority,
            candidate.value,
        )
        valid.append((key, candidate))
    if not valid:
        return origin, RefinementReason.UNCHANGED
    _, chosen = min(valid, key=lambda item: item[0])
    if abs(chosen.value - origin) <= _EPSILON:
        return origin, RefinementReason.UNCHANGED
    return chosen.value, chosen.reason


def _candidate_units(
    selected: SelectedCandidate,
    transcript: Transcript,
    source_duration: float,
    search_radius: float,
) -> tuple[
    tuple[_TimedUnit, ...],
    tuple[_TimedUnit, ...],
    tuple[_TimedUnit, ...],
]:
    candidate = selected.evaluation.candidate
    window_start = max(0.0, candidate.start - search_radius)
    window_end = min(source_duration, candidate.end + search_radius)
    all_words = _timed_words(transcript, source_duration)
    words = tuple(
        unit
        for unit in all_words
        if _unit_intersects_window(unit, window_start, window_end)
    )
    if words:
        return words, all_words, _timed_segments(transcript, source_duration)
    all_segments = _timed_segments(transcript, source_duration)
    segments = tuple(
        unit
        for unit in all_segments
        if _unit_intersects_window(unit, window_start, window_end)
    )
    if segments:
        return segments, all_segments, all_words
    if all_words:
        return (), all_words, _timed_segments(transcript, source_duration)
    return (), all_segments, ()


def _refine_one(
    selected: SelectedCandidate,
    transcript: Transcript,
    source_duration: float,
    *,
    pre_roll: float,
    post_roll: float,
    search_radius: float,
    pause_threshold: float,
) -> RefinedSelection:
    candidate = selected.evaluation.candidate
    if candidate.end > source_duration:
        raise ValueError("selected candidate must fit within source duration")
    units, membership_units, secondary_membership_units = _candidate_units(
        selected, transcript, source_duration, search_radius
    )
    semantic_start, start_reason = _choose_boundary(
        _boundary_candidates(
            units,
            candidate.start,
            start=True,
            radius=search_radius,
            pause_threshold=pause_threshold,
            source_duration=source_duration,
        ),
        units,
        origin=candidate.start,
        other_boundary=candidate.end,
        start=True,
    )
    semantic_end, end_reason = _choose_boundary(
        _boundary_candidates(
            units,
            candidate.end,
            start=False,
            radius=search_radius,
            pause_threshold=pause_threshold,
            source_duration=source_duration,
        ),
        units,
        origin=candidate.end,
        other_boundary=candidate.start,
        start=False,
    )
    if semantic_end <= semantic_start:
        semantic_start = candidate.start
        semantic_end = candidate.end
        start_reason = RefinementReason.UNCHANGED
        end_reason = RefinementReason.UNCHANGED

    has_membership_evidence = bool(membership_units)
    desired_render_start = (
        semantic_start - pre_roll if has_membership_evidence else semantic_start
    )
    desired_render_end = (
        semantic_end + post_roll if has_membership_evidence else semantic_end
    )
    render_start = max(0.0, desired_render_start)
    render_end = min(source_duration, desired_render_end)
    if render_end <= render_start:
        render_start = candidate.start
        render_end = candidate.end
        semantic_start = candidate.start
        semantic_end = candidate.end
        start_reason = RefinementReason.UNCHANGED
        end_reason = RefinementReason.UNCHANGED
    actual_pre_roll = semantic_start - render_start
    actual_post_roll = render_end - semantic_end
    original_membership = _membership(membership_units, candidate.start, candidate.end)
    render_membership = _membership(membership_units, render_start, render_end)
    secondary_original_membership = _membership(
        secondary_membership_units, candidate.start, candidate.end
    )
    secondary_render_membership = _membership(
        secondary_membership_units, render_start, render_end
    )
    requires_rescore = (
        original_membership != render_membership
        or secondary_original_membership != secondary_render_membership
    )

    reasons: list[RefinementReason] = []
    for reason in (start_reason, end_reason):
        if reason is not RefinementReason.UNCHANGED and reason not in reasons:
            reasons.append(reason)
    if actual_pre_roll > _EPSILON or actual_post_roll > _EPSILON:
        reasons.append(RefinementReason.PADDED)
    if (
        desired_render_start < -_EPSILON
        or desired_render_end > source_duration + _EPSILON
    ):
        reasons.append(RefinementReason.CLAMPED)
    if requires_rescore:
        reasons.append(RefinementReason.REQUIRES_RESCORE)
    if not reasons:
        reasons.append(RefinementReason.UNCHANGED)
    return RefinedSelection(
        selected=selected,
        render_start=render_start,
        render_end=render_end,
        pre_roll=actual_pre_roll,
        post_roll=actual_post_roll,
        reasons=tuple(reasons),
        version=REFINE_VERSION,
        source_duration=source_duration,
        requires_rescore=requires_rescore,
    )


def refine_selection(
    selection: SelectionResult,
    transcript: Transcript,
    source_duration: float,
    *,
    pre_roll: float = 0.15,
    post_roll: float = 0.25,
    search_radius: float = 0.5,
    pause_threshold: float = 0.4,
) -> tuple[RefinedSelection, ...]:
    """Refine every selected interval using only observed transcript timing."""
    if not isinstance(selection, SelectionResult):
        raise ValueError("selection must be a SelectionResult")
    if not isinstance(transcript, Transcript):
        raise ValueError("transcript must be a Transcript")
    if (
        isinstance(source_duration, bool)
        or not isinstance(source_duration, (int, float))
        or not isfinite(source_duration)
        or source_duration <= 0
    ):
        raise ValueError("source duration must be finite and positive")
    for value, name in (
        (pre_roll, "pre_roll"),
        (post_roll, "post_roll"),
        (search_radius, "search_radius"),
        (pause_threshold, "pause_threshold"),
    ):
        _validate_non_negative(
            value,
            name,
            positive=name in {"search_radius", "pause_threshold"},
        )
    return tuple(
        _refine_one(
            selected,
            transcript,
            source_duration,
            pre_roll=pre_roll,
            post_roll=post_roll,
            search_radius=search_radius,
            pause_threshold=pause_threshold,
        )
        for selected in selection.selected
    )

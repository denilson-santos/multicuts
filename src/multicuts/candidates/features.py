"""Pure deterministic features used by candidate evaluation and scoring."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple

from multicuts.models import Candidate, CandidateFeatures, Transcript

FEATURE_VERSION = "1"
FEATURE_EPSILON_SECONDS = 1e-6
_SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？", "…")
_TOKEN_PATTERN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)

# These are intentionally small, explainable lexical signals. They are not
# presented as language understanding and only feed soft deterministic rules.
_FILLER_TOKENS = frozenset(
    {
        "ah",
        "assim",
        "eh",
        "er",
        "hã",
        "like",
        "né",
        "tipo",
        "uh",
        "um",
        "youknow",
    }
)
_CONTEXT_DEPENDENT_OPENINGS = frozenset(
    {
        "and",
        "because",
        "but",
        "como",
        "dessa",
        "esse",
        "isso",
        "it",
        "mas",
        "porque",
        "that",
        "this",
        "these",
        "those",
        "então",
    }
)
_PAYOFF_MARKERS = (
    "as a result",
    "that's why",
    "the lesson",
    "the point is",
    "therefore",
    "por isso",
    "o ponto é",
    "a lição",
    "resultado",
)


class _TimedWord(NamedTuple):
    """A word clipped to the candidate interval for local calculations."""

    text: str
    start: float
    end: float
    confidence: float | None


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match.casefold() for match in _TOKEN_PATTERN.findall(text))


def _overlaps(
    start: float, end: float, interval_start: float, interval_end: float
) -> bool:
    """Use half-open overlap so touching boundaries do not duplicate words."""
    return start < interval_end and end > interval_start


def _timed_words(
    candidate: Candidate, transcript: Transcript
) -> tuple[_TimedWord, ...]:
    words: list[_TimedWord] = []
    for word in transcript.words:
        if word.start is None or word.end is None:
            continue
        if not _overlaps(word.start, word.end, candidate.start, candidate.end):
            continue
        words.append(
            _TimedWord(
                text=word.text,
                start=max(candidate.start, word.start),
                end=min(candidate.end, word.end),
                confidence=word.confidence,
            )
        )
    return tuple(sorted(words, key=lambda item: (item.start, item.end, item.text)))


def _timed_boundaries(transcript: Transcript) -> tuple[tuple[float, float], ...]:
    boundaries: list[tuple[float, float]] = []
    for segment in transcript.segments:
        if segment.start is not None and segment.end is not None:
            boundaries.append((segment.start, segment.end))
    if not boundaries:
        for word in transcript.words:
            if word.start is not None and word.end is not None:
                boundaries.append((word.start, word.end))
    return tuple(boundaries)


def _is_aligned(
    value: float, boundaries: Iterable[tuple[float, float]], index: int
) -> bool:
    return any(
        abs(interval[index] - value) <= FEATURE_EPSILON_SECONDS
        for interval in boundaries
    )


def _union_duration(intervals: Iterable[tuple[float, float]]) -> float:
    ordered = sorted(intervals)
    if not ordered:
        return 0.0
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += current_end - current_start
        current_start, current_end = start, end
    return total + current_end - current_start


def _pause_evidence(words: tuple[_TimedWord, ...]) -> tuple[float, float]:
    if not words:
        return 0.0, 0.0
    pause_duration = 0.0
    max_pause = 0.0
    previous_end = words[0].end
    for word in words[1:]:
        gap = max(0.0, word.start - previous_end)
        pause_duration += gap
        max_pause = max(max_pause, gap)
        previous_end = max(previous_end, word.end)
    return pause_duration, max_pause


def _boundary_quality(
    text: str,
    *,
    aligned: bool,
    opening: bool,
) -> float:
    tokens = _tokens(text)
    if not tokens:
        return 0.0
    if opening:
        first_character = next(
            (character for character in text.strip() if character.isalpha()), ""
        )
        capitalized = not first_character or first_character.upper() == first_character
        context_dependent = tokens[0] in _CONTEXT_DEPENDENT_OPENINGS
        if aligned and capitalized and not context_dependent:
            return 1.0
        if aligned and not context_dependent:
            return 0.75
        if capitalized and not context_dependent:
            return 0.6
        return 0.25

    stripped = text.rstrip()
    punctuated = stripped.endswith(_SENTENCE_ENDINGS)
    if aligned and punctuated:
        return 1.0
    if punctuated:
        return 0.75
    if aligned:
        return 0.55
    return 0.3


def _standalone_context(tokens: tuple[str, ...]) -> float | None:
    if not tokens:
        return None
    if tokens[0] in _CONTEXT_DEPENDENT_OPENINGS:
        return 0.25
    if tokens[0] in {"he", "she", "they", "ele", "ela", "eles", "elas"}:
        return 0.45
    return 0.9


def _payoff_signal(text: str, tokens: tuple[str, ...]) -> float | None:
    if not tokens:
        return None
    normalized = " ".join(tokens)
    if any(marker in normalized for marker in _PAYOFF_MARKERS):
        return 0.9
    if text.rstrip().endswith(_SENTENCE_ENDINGS):
        return 0.7
    if text.rstrip().endswith((":", ";", ",")):
        return 0.25
    return 0.4


def _filler_ratio(tokens: tuple[str, ...]) -> float | None:
    if not tokens:
        return None
    filler_count = sum(token in _FILLER_TOKENS for token in tokens)
    return filler_count / len(tokens)


def _confidence(words: tuple[_TimedWord, ...]) -> float | None:
    if not words or any(word.confidence is None for word in words):
        return None
    values = tuple(word.confidence for word in words)
    if any(value is None or not 0.0 <= value <= 1.0 for value in values):
        return None
    return sum(value for value in values if value is not None) / len(values)


def compute_candidate_features(
    candidate: Candidate,
    transcript: Transcript,
    *,
    feature_version: str = FEATURE_VERSION,
) -> CandidateFeatures:
    """Compute only evidence supported by the normalized transcript.

    Timed word gaps are treated as pause proxies. They are never described as
    measured audio silence because the feature stage has no audio analysis.
    """
    if not feature_version.strip():
        raise ValueError("feature version must not be empty")
    if candidate.end > transcript.duration:
        raise ValueError("candidate interval exceeds transcript duration")

    duration = candidate.end - candidate.start
    tokens = _tokens(candidate.text)
    timed_words = _timed_words(candidate, transcript)
    timed_intervals = tuple((word.start, word.end) for word in timed_words)
    speech_duration: float | None
    pause_duration: float | None
    pause_ratio: float | None
    max_pause: float | None
    if timed_words:
        speech_duration = min(duration, _union_duration(timed_intervals))
        pause_duration_value, max_pause_value = _pause_evidence(timed_words)
        pause_duration = min(duration, pause_duration_value)
        pause_ratio = pause_duration / duration
        max_pause = max_pause_value
    else:
        speech_duration = None
        pause_duration = None
        pause_ratio = None
        max_pause = None

    timing_coverage = None
    if transcript.words and tokens:
        timing_coverage = min(1.0, len(timed_words) / len(tokens))
    boundaries = _timed_boundaries(transcript)
    return CandidateFeatures(
        duration=duration,
        word_count=len(tokens),
        timed_word_count=len(timed_words),
        speech_duration=speech_duration,
        words_per_second=len(tokens) / duration,
        speech_ratio=(
            speech_duration / duration if speech_duration is not None else None
        ),
        pause_duration=pause_duration,
        pause_ratio=pause_ratio,
        max_pause=max_pause,
        opening_quality=_boundary_quality(
            candidate.text,
            aligned=_is_aligned(candidate.start, boundaries, 0),
            opening=True,
        ),
        ending_quality=_boundary_quality(
            candidate.text,
            aligned=_is_aligned(candidate.end, boundaries, 1),
            opening=False,
        ),
        standalone_context=_standalone_context(tokens),
        payoff=_payoff_signal(candidate.text, tokens),
        filler_ratio=_filler_ratio(tokens),
        transcript_confidence=_confidence(timed_words),
        timing_coverage=timing_coverage,
        feature_version=feature_version,
    )


extract_candidate_features = compute_candidate_features
compute_features = compute_candidate_features

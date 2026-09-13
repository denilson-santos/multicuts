"""Project-owned values shared across the synchronous pipeline."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path


def _validate_interval(start: float | None, end: float | None) -> None:
    if (start is None) != (end is None):
        raise ValueError("start and end must both be present or absent")
    if start is not None and end is not None:
        if not isfinite(start) or not isfinite(end) or start < 0 or end <= start:
            raise ValueError("timed intervals must have finite, ordered seconds")


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    """A source available locally with a stable identity for stage caches."""

    local_path: Path
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raise ValueError("source fingerprint must not be empty")


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Usable streams and geometry after rotation and aspect-ratio correction."""

    duration: float
    coded_width: int
    coded_height: int
    presentation_width: int
    presentation_height: int
    video_stream_index: int
    audio_stream_index: int | None
    rotation_degrees: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.duration) or self.duration <= 0:
            raise ValueError("media duration must be finite and positive")
        if (
            min(
                self.coded_width,
                self.coded_height,
                self.presentation_width,
                self.presentation_height,
            )
            <= 0
        ):
            raise ValueError("media dimensions must be positive")
        if self.video_stream_index < 0 or (
            self.audio_stream_index is not None and self.audio_stream_index < 0
        ):
            raise ValueError("stream indexes must be non-negative")
        if not isfinite(self.rotation_degrees):
            raise ValueError("media rotation must be finite")

    @property
    def has_audio(self) -> bool:
        """Whether probing selected a usable audio stream."""
        return self.audio_stream_index is not None


@dataclass(frozen=True, slots=True)
class Word:
    """A transcript word, with missing timing represented explicitly."""

    text: str
    start: float | None
    end: float | None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("word text must not be empty")
        _validate_interval(self.start, self.end)
        if self.confidence is not None and not isfinite(self.confidence):
            raise ValueError("word confidence must be finite")


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A text segment with provider-supplied timing when available."""

    text: str
    start: float | None
    end: float | None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("segment text must not be empty")
        _validate_interval(self.start, self.end)


@dataclass(frozen=True, slots=True)
class Transcript:
    """A normalized transcript independent of the provider's JSON schema."""

    language_requested: str | None
    language_detected: str | None
    duration: float
    text: str
    segments: tuple[TranscriptSegment, ...]
    words: tuple[Word, ...]
    provider: str
    provider_version: str

    def __post_init__(self) -> None:
        if not isfinite(self.duration) or self.duration <= 0:
            raise ValueError("transcript duration must be finite and positive")
        if not self.text.strip():
            raise ValueError("transcript text must not be empty")
        if not self.provider or not self.provider_version:
            raise ValueError("transcript provider and version must not be empty")
        if not isinstance(self.segments, tuple) or not isinstance(self.words, tuple):
            raise ValueError("transcript segments and words must be tuples")


@dataclass(frozen=True, slots=True)
class SemanticUnit:
    """One timed transcript unit bounded by observed source timestamps."""

    text: str
    start: float
    end: float

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("semantic unit text must not be empty")
        _validate_interval(self.start, self.end)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A contiguous semantic-unit window proposed for later evaluation."""

    candidate_id: str
    start: float
    end: float
    text: str
    unit_indexes: tuple[int, ...]
    generator_version: str

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate ID must not be empty")
        if not self.text.strip():
            raise ValueError("candidate text must not be empty")
        if not self.generator_version.strip():
            raise ValueError("candidate generator version must not be empty")
        _validate_interval(self.start, self.end)
        if not isinstance(self.unit_indexes, tuple) or not self.unit_indexes:
            raise ValueError("candidate unit indexes must be a nonempty tuple")
        if any(type(index) is not int or index < 0 for index in self.unit_indexes):
            raise ValueError("candidate unit indexes must be non-negative integers")
        expected = tuple(
            range(self.unit_indexes[0], self.unit_indexes[0] + len(self.unit_indexes))
        )
        if self.unit_indexes != expected:
            raise ValueError("candidate unit indexes must be contiguous")

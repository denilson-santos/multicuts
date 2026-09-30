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


def _approximately_equal(left: float, right: float, *, tolerance: float = 1e-9) -> bool:
    return abs(left - right) <= tolerance


def _validate_clip_local_interval(
    start: float | None, end: float | None, duration: float
) -> None:
    _validate_interval(start, end)
    if start is not None and end is not None and (start < 0 or end > duration):
        raise ValueError("clip-local timestamps must stay within clip duration")


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    """A source available locally with identity and safe origin metadata.

    ``provider_id``, ``title``, and ``original_url`` are populated only for
    remote providers.  Keeping these values optional lets local acquisition
    retain its existing semantics without fabricating remote metadata.
    """

    local_path: Path
    fingerprint: str
    source_kind: str = "local"
    provider_id: str | None = None
    title: str | None = None
    original_url: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.local_path, Path):
            raise ValueError("source local path must be a Path")
        if not isinstance(self.fingerprint, str) or not self.fingerprint.strip():
            raise ValueError("source fingerprint must not be empty")
        if self.source_kind not in ("local", "youtube"):
            raise ValueError("source kind must be 'local' or 'youtube'")
        for field_name in ("provider_id", "title", "original_url"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"source {field_name} must be non-empty when present")
        if self.source_kind == "local" and (
            self.provider_id is not None
            or self.title is not None
            or self.original_url is not None
        ):
            raise ValueError("local sources must not carry remote metadata")
        if self.source_kind == "youtube" and (
            self.provider_id is None or self.title is None or self.original_url is None
        ):
            raise ValueError("YouTube sources require ID, title, and original URL")


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
class ClipTranscriptSegment:
    """One source segment represented on a refined clip timeline.

    source_index identifies the segment in the normalized source transcript.
    The local timestamps are optional because a source segment can be retained
    without usable timing; subtitle generation must handle that case explicitly
    instead of inventing timestamps.
    """

    text: str
    start: float | None
    end: float | None
    source_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("clip transcript segment text must not be empty")
        if type(self.source_index) is not int or self.source_index < 0:
            raise ValueError(
                "clip transcript segment source index must be non-negative"
            )
        _validate_interval(self.start, self.end)


@dataclass(frozen=True, slots=True)
class ClipTranscriptWord:
    """One source word represented on a refined clip timeline.

    source_segment_index is optional because the normalized source transcript
    does not always expose a reliable word-to-segment relationship. When
    present, it points to the source segment index rather than a local
    position that could change when the clip is filtered.
    """

    text: str
    start: float | None
    end: float | None
    confidence: float | None
    source_index: int
    source_segment_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("clip transcript word text must not be empty")
        if type(self.source_index) is not int or self.source_index < 0:
            raise ValueError("clip transcript word source index must be non-negative")
        if self.source_segment_index is not None and (
            type(self.source_segment_index) is not int or self.source_segment_index < 0
        ):
            raise ValueError(
                "clip transcript word source segment index must be non-negative"
            )
        _validate_interval(self.start, self.end)
        if self.confidence is not None and not isfinite(self.confidence):
            raise ValueError("clip transcript word confidence must be finite")

    @property
    def is_timed(self) -> bool:
        """Whether this word retained an observed source interval."""
        return self.start is not None and self.end is not None


@dataclass(frozen=True, slots=True)
class ClipTranscript:
    """A source-derived transcript shifted onto one rendered clip.

    The source interval and source transcript provenance are retained so the
    subtitle artifact can be audited without re-running transcription. An
    empty text, segments, or words value is valid: downstream subtitle policy
    decides what to do when the selected interval has no usable timed
    transcript content.
    """

    language_requested: str | None
    language_detected: str | None
    duration: float
    source_start: float
    source_end: float
    source_duration: float
    text: str
    segments: tuple[ClipTranscriptSegment, ...]
    words: tuple[ClipTranscriptWord, ...]
    provider: str
    provider_version: str
    word_timing_complete: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "duration",
            "source_start",
            "source_end",
            "source_duration",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
                raise ValueError(f"clip transcript {field_name} must be finite")
        if self.duration <= 0:
            raise ValueError("clip transcript duration must be positive")
        if self.source_duration <= 0:
            raise ValueError("clip transcript source duration must be positive")
        if self.source_start < 0 or self.source_end <= self.source_start:
            raise ValueError("clip transcript source interval is invalid")
        if self.source_end > self.source_duration:
            raise ValueError("clip transcript source interval exceeds source duration")
        if not _approximately_equal(self.duration, self.source_end - self.source_start):
            raise ValueError("clip transcript duration does not match source interval")
        if not isinstance(self.text, str):
            raise ValueError("clip transcript text must be a string")
        if not isinstance(self.segments, tuple) or not isinstance(self.words, tuple):
            raise ValueError("clip transcript segments and words must be tuples")
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("clip transcript provider must not be empty")
        if (
            not isinstance(self.provider_version, str)
            or not self.provider_version.strip()
        ):
            raise ValueError("clip transcript provider version must not be empty")
        if type(self.word_timing_complete) is not bool:
            raise ValueError("clip transcript word timing flag must be boolean")
        for field_name in ("language_requested", "language_detected"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(
                    f"clip transcript {field_name} must be non-empty when present"
                )

        segment_indexes: list[int] = []
        for segment in self.segments:
            if not isinstance(segment, ClipTranscriptSegment):
                raise ValueError("clip transcript segments must be structured values")
            _validate_clip_local_interval(segment.start, segment.end, self.duration)
            segment_indexes.append(segment.source_index)
        if segment_indexes != sorted(set(segment_indexes)):
            raise ValueError("clip transcript segment indexes must be ordered uniquely")

        word_indexes: list[int] = []
        for word in self.words:
            if not isinstance(word, ClipTranscriptWord):
                raise ValueError("clip transcript words must be structured values")
            _validate_clip_local_interval(word.start, word.end, self.duration)
            if (
                word.source_segment_index is not None
                and word.source_segment_index not in segment_indexes
            ):
                raise ValueError(
                    "clip transcript word parent must refer to a retained segment"
                )
            word_indexes.append(word.source_index)
        if word_indexes != sorted(set(word_indexes)):
            raise ValueError("clip transcript word indexes must be ordered uniquely")

    @property
    def word_animation_safe(self) -> bool:
        """Whether downstream word animation can rely on complete timing."""
        return (
            self.word_timing_complete
            and bool(self.words)
            and all(word.is_timed for word in self.words)
        )


@dataclass(frozen=True, slots=True)
class SubtitleArtifacts:
    """Normalized paths and provenance for one rendered clip subtitle set."""

    cues_json_path: Path
    srt_path: Path
    ass_path: Path
    video_path: Path
    provider_version: str
    template_requested: str | None
    template_resolved: str

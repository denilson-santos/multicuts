import json
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from multicuts.models import (
    AcquiredSource,
    MediaInfo,
    Transcript,
    TranscriptSegment,
    Word,
)


def test_acquired_source_model_keeps_identity_without_file_access() -> None:
    source = AcquiredSource(Path("/missing/source.mp4"), "sha256:abc123")

    assert source.local_path == Path("/missing/source.mp4")
    assert source.fingerprint == "sha256:abc123"
    assert source == AcquiredSource(Path("/missing/source.mp4"), "sha256:abc123")
    with pytest.raises(FrozenInstanceError):
        source.fingerprint = "other"  # type: ignore[misc]


def test_media_info_model_distinguishes_coded_and_presentation_geometry() -> None:
    media = MediaInfo(
        duration=93.5,
        coded_width=1920,
        coded_height=1080,
        presentation_width=1080,
        presentation_height=1920,
        video_stream_index=0,
        audio_stream_index=1,
        rotation_degrees=90.0,
    )

    assert (media.coded_width, media.coded_height) == (1920, 1080)
    assert (media.presentation_width, media.presentation_height) == (1080, 1920)
    assert media.has_audio
    assert media.rotation_degrees == 90.0


def test_media_info_model_can_represent_missing_audio() -> None:
    media = MediaInfo(10.0, 640, 480, 640, 480, 0, None)

    assert not media.has_audio


def test_transcript_model_serializes_project_owned_values_as_json() -> None:
    word = Word("Olá", 0.125, 0.475, 0.97)
    segment = TranscriptSegment("Olá mundo", 0.125, 1.25)
    transcript = Transcript(
        language_requested=None,
        language_detected="pt",
        duration=2.5,
        text="Olá mundo",
        segments=(segment,),
        words=(word, Word("mundo", None, None)),
        provider="multisubs",
        provider_version="4.1.0",
    )

    payload = json.loads(json.dumps(asdict(transcript), ensure_ascii=False))

    assert payload["language_requested"] is None
    assert payload["language_detected"] == "pt"
    assert payload["segments"] == [{"text": "Olá mundo", "start": 0.125, "end": 1.25}]
    assert payload["words"] == [
        {"text": "Olá", "start": 0.125, "end": 0.475, "confidence": 0.97},
        {"text": "mundo", "start": None, "end": None, "confidence": None},
    ]
    assert payload["provider_version"] == "4.1.0"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (None, 1.0),
        (0.0, None),
        (-1.0, 1.0),
        (1.0, 1.0),
        (2.0, 1.0),
        (0.0, float("nan")),
    ],
)
def test_timed_text_models_reject_impossible_intervals(
    start: float | None, end: float | None
) -> None:
    with pytest.raises(ValueError):
        Word("word", start, end)
    with pytest.raises(ValueError):
        TranscriptSegment("segment", start, end)


@pytest.mark.parametrize("duration", [0.0, -1.0, float("inf"), float("nan")])
def test_media_and_transcript_models_reject_invalid_duration(duration: float) -> None:
    with pytest.raises(ValueError):
        MediaInfo(duration, 640, 480, 640, 480, 0, 1)
    with pytest.raises(ValueError):
        Transcript(None, "pt", duration, "Olá", (), (), "multisubs", "4.1.0")


def test_transcript_model_requires_immutable_collections() -> None:
    with pytest.raises(ValueError, match="must be tuples"):
        Transcript(None, "pt", 1.0, "Olá", [], (), "multisubs", "4.1.0")  # type: ignore[arg-type]

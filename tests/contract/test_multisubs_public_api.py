"""Checks for the public multisubs operations consumed by the adapter."""

import importlib
import inspect
from importlib import metadata
from pathlib import Path
from types import ModuleType

import pytest


def _installed_provider() -> ModuleType:
    try:
        return importlib.import_module("multisubs")
    except ModuleNotFoundError as exc:
        if exc.name == "multisubs":
            pytest.skip("multisubs is not installed in this environment")
        raise


def _assert_supported_provider_version() -> None:
    version = metadata.version("multisubs")
    parts = version.split(".")
    assert len(parts) >= 2 and all(part.isdigit() for part in parts[:2]), (
        "multisubs distribution lacks a numeric major/minor version"
    )
    assert parts[0] == "5", "multisubs 5.x is required by the consumed public contract"


@pytest.mark.parametrize("language", [None, "pt"])
@pytest.mark.parametrize(
    ("backend", "model"),
    [
        ("whisperx", "turbo"),
        ("faster-whisper", "large-v3"),
        ("parakeet", "nvidia/parakeet-tdt-0.6b-v3"),
        ("qwen", "Qwen/Qwen3-ASR-1.7B-hf"),
    ],
)
def test_public_transcription_signature_and_version(
    language: str | None, backend: str, model: str
) -> None:
    provider = _installed_provider()
    generate = getattr(provider, "transcribe_speech", None)
    assert callable(generate), "multisubs.transcribe_speech is unavailable"
    _assert_supported_provider_version()

    try:
        inspect.signature(generate).bind(
            Path("source.mp4"),
            lang=language,
            task="transcribe",
            model_name=model,
            asr_backend=backend,
        )
    except (TypeError, ValueError) as exc:
        pytest.fail(f"multisubs public transcription signature changed: {exc}")
    document = getattr(provider, "SpeechTranscript", None)
    assert document is not None
    assert {"language", "task", "full_text", "segments"}.issubset(
        getattr(document, "__dataclass_fields__", {})
    )
    assert hasattr(document, "duration")


def test_multisubs_public_speech_renderer_signature_and_artifacts() -> None:
    provider = _installed_provider()
    _assert_supported_provider_version()
    render = getattr(provider, "render_transcript", None)
    assert callable(render), "multisubs.render_transcript is unavailable"
    inspect.signature(render).bind(
        {},
        Path("clip.mp4"),
        Path("output"),
        template="yellow-pop",
        template_dir=None,
        progress=None,
    )
    artifacts = getattr(provider, "GeneratedSubtitleArtifacts", None)
    assert artifacts is not None
    assert {"srt_path", "ass_path", "video_path"}.issubset(
        artifacts.__dataclass_fields__
    )


def test_public_speech_interchange_preserves_optional_alignment_and_language() -> None:
    provider = _installed_provider()
    document = provider.SpeechTranscript.from_dict(
        {
            "schema_version": 1,
            "language": None,
            "task": "transcribe",
            "asr_backend": "parakeet",
            "model_name": "source-model",
            "full_text": " Olá mundo.",
            "segments": [
                {
                    "text": " Olá mundo.",
                    "start": 0.0,
                    "end": 2.0,
                    "words": [
                        {"word": " Olá", "start": 0.2, "end": 0.2},
                        {"word": " mundo.", "start": None},
                    ],
                }
            ],
        }
    )
    payload = document.to_dict()
    assert payload["segments"][0]["words"][1] == {"word": " mundo.", "start": None}
    assert payload["language"] is None
    payload["segments"][0]["words"][0]["start"] = 0.1
    assert document.segments[0]["words"][0]["start"] == 0.2

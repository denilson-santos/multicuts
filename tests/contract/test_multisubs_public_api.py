"""Checks for the public multisubs operations consumed by the adapter."""

import importlib
import inspect
from dataclasses import fields
from importlib import metadata
from pathlib import Path
from types import ModuleType

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.subtitles import SubtitleOptions


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
    assert parts[0] == "6" and int(parts[1]) >= 1, (
        "multisubs >=6.1,<7 is required by the consumed public contract"
    )


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920), (1080, 1080)])
def test_public_preparation_preserves_geometry_and_resource_lifetime(
    size: tuple[int, int], tmp_path: Path
) -> None:
    provider = _installed_provider()
    speech = {
        "schema_version": 1,
        "language": None,
        "task": "transcribe",
        "asr_backend": "faster-whisper",
        "model_name": "turbo",
        "full_text": " Hello.",
        "segments": [{"text": " Hello.", "start": 0.0, "end": 1.0}],
    }
    with provider.prepare_subtitles(
        speech,
        output_dir=tmp_path,
        frame_width=size[0],
        frame_height=size[1],
        template="yellow-pop",
        progress=lambda message: None,
    ) as prepared:
        assert isinstance(prepared, provider.PreparedSubtitleArtifacts)
        ass = prepared.ass_path.read_text(encoding="utf-8")
        assert f"PlayResX: {size[0]}" in ass
        assert f"PlayResY: {size[1]}" in ass
        assert prepared.fonts_dir is None or prepared.fonts_dir.is_dir()
        assert prepared.template_resolved == "yellow-pop"
    assert prepared.ass_path.is_file() and prepared.srt_path.is_file()
    with pytest.raises(provider.CancelledError):
        with provider.prepare_subtitles(
            speech,
            output_dir=tmp_path / "cancelled",
            frame_width=size[0],
            frame_height=size[1],
            should_cancel=lambda: True,
        ):
            pytest.fail("Cancelled preparation must not yield resources")


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


def test_public_subtitle_builder_preserves_sparse_overrides() -> None:
    provider = _installed_provider()
    builder = getattr(provider, "build_subtitle_config", None)
    assert callable(builder), "multisubs.build_subtitle_config is unavailable"
    inspect.signature(builder).bind(
        template="yellow-pop", template_dir=None, overrides={}
    )
    baseline = provider.build_subtitle_config(template="yellow-pop")
    overrides = {"font_size": "4.5%", "margin_bottom": "8%", "italic": False}
    configured = provider.build_subtitle_config(
        template="yellow-pop", overrides=overrides
    )
    assert type(configured) is provider.SubtitleConfig
    assert configured.style.typography.font_size.original == "4.5%"
    assert configured.layout.margin_bottom.original == "8%"
    assert configured.style.typography.italic is False
    assert configured.style.typography.font == baseline.style.typography.font
    assert configured.animation == baseline.animation
    assert builder(template="yellow-pop") == baseline
    assert overrides == {"font_size": "4.5%", "margin_bottom": "8%", "italic": False}


@pytest.mark.parametrize(
    "overrides",
    [
        {"unknown_option": None},
        {"font_weight": "bold", "bold": False},
        {"position": "middle-center", "margin_bottom": "0%"},
    ],
)
def test_public_subtitle_builder_rejects_invalid_settings(overrides) -> None:
    provider = _installed_provider()
    with pytest.raises(provider.ValidationError):
        provider.build_subtitle_config(template="yellow-pop", overrides=overrides)


def test_public_subtitle_builder_supports_every_owned_presentation_field() -> None:
    provider = _installed_provider()
    overrides = {field.name: None for field in fields(SubtitleOptions)}
    overrides["disable_cue_animations"] = overrides.pop("cue_animations")
    overrides["disable_word_animations"] = overrides.pop("word_animations")
    assert len(overrides) == 57
    assert provider.build_subtitle_config(
        template="yellow-pop", overrides=overrides
    ) == provider.build_subtitle_config(template="yellow-pop")


@pytest.mark.parametrize("enabled", [None, False, True])
def test_affirmative_animation_switches_use_the_public_provider_contract(
    enabled,
) -> None:
    _installed_provider()
    MultisubsAdapter().validate_subtitle_options(
        template="yellow-pop",
        template_dir=None,
        options=SubtitleOptions(cue_animations=enabled, word_animations=enabled),
    )


def test_public_builder_preserves_custom_template_fields(tmp_path: Path) -> None:
    provider = _installed_provider()
    (tmp_path / "custom.json").write_text(
        '{"schema_version":1,"name":"custom","base":"yellow-pop",'
        '"layout":{"margins":{"bottom":"15%"}}}',
        encoding="utf-8",
    )
    configured = provider.build_subtitle_config(
        template="custom", template_dir=tmp_path, overrides={"font_size": "4.5%"}
    )
    assert configured.layout.margin_bottom.original == "15%"
    assert configured.style.typography.font_size.original == "4.5%"


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

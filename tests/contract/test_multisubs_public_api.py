"""Checks for the public multisubs operations consumed by the adapter."""

import importlib
import inspect
from dataclasses import fields
from importlib import metadata
from pathlib import Path
from types import ModuleType

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.cli import main
from multicuts.models import Transcript, TranscriptSegment
from multicuts.render import clip_transcript
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
    assert parts[0] == "7" and int(parts[1]) >= 0, (
        "multisubs >=7.0,<8 is required by the consumed public contract"
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


@pytest.mark.parametrize(
    "overrides",
    [{"position_x": "50%"}, {"position_y": "80%"}, {"anchor": "center"}],
)
def test_partial_coordinates_inherit_template_dimensions(overrides) -> None:
    provider = _installed_provider()
    native = provider.build_subtitle_config(template="yellow-pop")
    custom = provider.build_subtitle_config(template="yellow-pop", overrides=overrides)
    assert custom.layout.has_custom_coordinates
    assert custom.layout.max_width_inherited
    assert custom.layout.max_width == native.layout.max_width
    assert custom.layout.max_height == native.layout.max_height


@pytest.mark.parametrize(
    "template",
    [
        "anton-impact",
        "bangers-comic",
        "press-start-arcade",
        "quantico-tech",
        "russo-punch",
    ],
)
def test_display_font_templates_are_available_through_the_public_builder(
    template,
) -> None:
    provider = _installed_provider()
    assert provider.build_subtitle_config(template=template).style.typography.font


def test_vertical_margins_preserve_line_breaks_with_inherited_height(tmp_path) -> None:
    provider = _installed_provider()
    text = "Subtitles keep their line capacity when the bottom margin changes."
    speech = {
        "schema_version": 1,
        "language": "en",
        "task": "transcribe",
        "asr_backend": "faster-whisper",
        "model_name": "turbo",
        "full_text": text,
        "segments": [
            {
                "text": text,
                "start": 0.0,
                "end": 4.0,
            }
        ],
    }
    subtitles = []
    for margin in ("3%", "20%"):
        config = provider.build_subtitle_config(
            template="yellow-pop", overrides={"margin_bottom": margin}
        )
        with provider.prepare_subtitles(
            speech,
            output_dir=tmp_path / margin,
            frame_width=1080,
            frame_height=1920,
            subtitle_config=config,
            progress=lambda message: None,
        ) as prepared:
            subtitles.append(prepared.srt_path.read_text(encoding="utf-8"))
    assert subtitles[0] == subtitles[1]
    assert any(
        len(block.splitlines()) > 3 for block in subtitles[0].strip().split("\n\n")
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


def test_invalid_coordinates_report_provider_geometry_details_through_cli(
    tmp_path, monkeypatch, capsys
) -> None:
    _installed_provider()
    monkeypatch.chdir(tmp_path)
    local = clip_transcript(
        Transcript(
            None,
            "en",
            1.0,
            "Hello.",
            (TranscriptSegment("Hello.", 0.0, 1.0),),
            (),
            "multisubs",
            "7.0.0",
        ),
        0.0,
        1.0,
    )

    def pipeline(config):
        output = config.for_output("short", "vertical")
        with MultisubsAdapter().prepare_clip_subtitles(
            local,
            frame_width=1080,
            frame_height=1920,
            template=output.subtitle_template,
            template_dir=output.subtitle_template_dir,
            options=output.subtitle_options,
            workspace=tmp_path / "subtitles",
        ):
            pytest.fail("Invalid coordinates must not reach rendering")

    code = main(
        [
            "source.mp4",
            "--output-dir",
            str(tmp_path / "out"),
            "--clip-full",
            "--render=short:vertical",
            "--subtitles=short",
            "--subtitle-position-y=all:vertical=20%",
            "--subtitle-position-x=all:vertical=0%",
        ],
        pipeline=pipeline,
    )
    assert code == 2
    error = capsys.readouterr().err
    assert "Invalid configuration" in error
    assert "--subtitle-position-x=0px" in error
    assert "cannot anchor a 692px --subtitle-max-width" in error
    assert "346px to 734px" in error
    assert "Rendering failed" not in error
    assert "Could not prepare native subtitles" not in error
    assert not (tmp_path / "out").exists()


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

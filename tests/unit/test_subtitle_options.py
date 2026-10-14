"""CLI and owned-data contracts for sparse subtitle presentation controls."""

import os
from dataclasses import fields, replace
from pathlib import Path

import pytest

from multicuts.cli import parse_run_config
from multicuts.errors import ConfigurationError
from multicuts.subtitles import SubtitleOptions
from multicuts.variants import VARIANT_RATIOS

CASES = [
    ("position", "bottom-center"),
    ("margin_left", "4.5%"),
    ("margin_right", "4.5%"),
    ("margin_top", "4.5%"),
    ("margin_bottom", "4.5%"),
    ("max_width", "4.5%"),
    ("max_height", "4.5%"),
    ("position_x", "4.5%"),
    ("position_y", "4.5%"),
    ("anchor", "bottom-center"),
    ("font", "Montserrat"),
    ("font_weight", "600"),
    ("bold", False),
    ("italic", False),
    ("text_case", "original"),
    ("fonts_dir", "fonts"),
    ("font_size", "4.5%"),
    ("letter_spacing", "4.5%"),
    ("line_height", "auto"),
    ("text_color", "#FFEE00"),
    ("backdrop", "none"),
    ("backdrop_color", "#FFEE00"),
    ("word_backdrop", "none"),
    ("word_backdrop_color", "#FFEE00"),
    ("opacity", "0%"),
    ("backdrop_size", "4.5%"),
    ("word_backdrop_size", "4.5%"),
    ("shadow_size", "4.5%"),
    ("animation_cue_text_entrance", "none"),
    ("animation_cue_text_entrance_duration", "150ms"),
    ("animation_cue_text_emphasis", "none"),
    ("animation_cue_text_emphasis_duration", "150ms"),
    ("animation_cue_text_exit", "none"),
    ("animation_cue_text_exit_duration", "150ms"),
    ("animation_cue_backdrop_entrance", "none"),
    ("animation_cue_backdrop_entrance_duration", "150ms"),
    ("animation_cue_backdrop_emphasis", "none"),
    ("animation_cue_backdrop_emphasis_duration", "150ms"),
    ("animation_cue_backdrop_exit", "none"),
    ("animation_cue_backdrop_exit_duration", "150ms"),
    ("animation_word_text_entrance", "none"),
    ("animation_word_text_entrance_duration", "150ms"),
    ("animation_word_text_emphasis", "none"),
    ("animation_word_text_emphasis_duration", "150ms"),
    ("animation_word_text_exit", "none"),
    ("animation_word_text_exit_duration", "150ms"),
    ("animation_word_backdrop_entrance", "none"),
    ("animation_word_backdrop_entrance_duration", "150ms"),
    ("animation_word_backdrop_emphasis", "none"),
    ("animation_word_backdrop_emphasis_duration", "150ms"),
    ("animation_word_backdrop_exit", "none"),
    ("animation_word_backdrop_exit_duration", "150ms"),
    ("animation_word_text_mode", "active-word"),
    ("animation_word_backdrop_mode", "active-word"),
    ("animation_word_text_highlight_color", "#FFEE00"),
    ("disable_cue_animations", True),
    ("disable_word_animations", False),
]


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in tuple(os.environ):
        if name.startswith("SUBTITLE_"):
            monkeypatch.delenv(name)


def parse(*flags):
    return parse_run_config(
        ["source.mp4", "--output-dir", "out", "--clip-full", *flags]
    ).subtitle_options


@pytest.mark.parametrize(("key", "value"), CASES)
def test_each_presentation_option_is_available_directly_in_cli(key, value):
    flag = "--subtitle-" + key.replace("_", "-")
    flags = [flag, str(value).lower() if isinstance(value, bool) else value]
    options = parse(*flags)
    expected = Path(str(value)) if key == "fonts_dir" else value
    assert options.overrides() == {key: expected}


@pytest.mark.parametrize(("key", "value"), CASES)
def test_each_presentation_option_accepts_environment_settings(key, value, monkeypatch):
    raw = str(value).lower() if isinstance(value, bool) else value
    monkeypatch.setenv("SUBTITLE_" + key.upper(), raw)
    options = parse()
    expected = Path(str(value)) if key == "fonts_dir" else value
    assert options.overrides() == {key: expected}


def test_precedence_preserves_false_and_zero_and_leaves_other_fields_unset(
    tmp_path, monkeypatch
):
    (tmp_path / ".env").write_text(
        "SUBTITLE_FONT_SIZE=3%\nSUBTITLE_ITALIC=true\nSUBTITLE_TEXT_COLOR='#AABBCC'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "4%")
    monkeypatch.setenv("SUBTITLE_ITALIC", "true")
    assert parse().font_size == "4%"
    options = parse(
        "--subtitle-font-size",
        "5%",
        "--subtitle-italic",
        "false",
        "--subtitle-opacity",
        "0%",
    )
    assert options.overrides() == {
        "font_size": "5%",
        "italic": False,
        "opacity": "0%",
        "text_color": "#AABBCC",
    }
    monkeypatch.delenv("SUBTITLE_FONT_SIZE")
    assert parse().font_size == "3%"


def test_missing_options_inherit():
    options = parse()
    assert isinstance(options, SubtitleOptions)
    assert len(fields(options)) == len(CASES) == 57
    assert options.overrides() == {}


@pytest.mark.parametrize("clip_class", ["short", "long"])
@pytest.mark.parametrize("variant", [None, *VARIANT_RATIOS])
def test_every_subtitle_field_is_available_for_each_class_and_variant(
    clip_class, variant
):
    scope = clip_class if variant is None else f"{clip_class}:{variant}"
    flags = []
    expected = {}
    for key, value in CASES:
        flag = "--subtitle-" + key.replace("_", "-")
        raw = str(value).lower() if isinstance(value, bool) else value
        flags.extend([flag, f"{scope}={raw}"])
        expected[key] = Path(str(value)) if key == "fonts_dir" else value
    config = parse_run_config(
        ["source.mp4", "--output-dir", "out", "--clip-full", *flags]
    )
    options = next(
        item
        for item in config.output_options
        if item.clip_class == clip_class and item.variant == variant
    )
    assert options.subtitle_options.overrides() == expected
    other_class = "long" if clip_class == "short" else "short"
    assert config.for_output(other_class, "vertical").subtitle_options.overrides() == {}


def test_scoped_styles_resolve_source_before_specificity(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "SUBTITLE_SHORT_VERTICAL_FONT_SIZE=9%\nSUBTITLE_SHORT_VERTICAL_ITALIC=true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "4%")
    monkeypatch.setenv("SUBTITLE_SHORT_VERTICAL_ITALIC", "true")
    config = parse_run_config(
        [
            "source.mp4",
            "--output-dir",
            "out",
            "--clip-full",
            "--subtitle-font-size",
            "short=6%",
            "--subtitle-italic",
            "false",
            "--subtitle-font-size",
            "long:horizontal=3%",
        ]
    )
    assert config.for_output("short", "vertical").subtitle_options.overrides() == {
        "font_size": "6%",
        "italic": False,
    }
    assert config.for_output("long", "horizontal").subtitle_options.font_size == "3%"
    config = parse_run_config(["source.mp4", "--output-dir", "out", "--clip-full"])
    assert config.for_output("short", "vertical").subtitle_options.font_size == "4%"


def test_named_caption_precedence_remains_correct_when_primary_changes(
    tmp_path, monkeypatch
):
    (tmp_path / ".env").write_text(
        "SUBTITLE_LONG_VERTICAL_ENABLED=true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUBTITLE_LONG_ENABLED", "false")
    config = parse_run_config(
        [
            "source.mp4",
            "--output-dir",
            "out",
            "--clip-full",
            "--subtitle-enabled",
            "long=false",
        ]
    )
    assert config.for_output("long", "vertical").subtitles_for("long") is False
    config = parse_run_config(["source.mp4", "--output-dir", "out", "--clip-full"])
    assert config.for_output("long", "vertical").subtitles_for("long") is False
    monkeypatch.setenv("SUBTITLE_LONG_VERTICAL_ENABLED", "true")
    config = parse_run_config(["source.mp4", "--output-dir", "out", "--clip-full"])
    # The named output keeps its captions when it changes publication order.
    assert config.for_output("long", "vertical").subtitles_for("long") is True
    config = parse_run_config(
        [
            "source.mp4",
            "--output-dir",
            "out",
            "--clip-full",
            "--aspect-ratio",
            "long=9:16",
        ]
    )
    assert config.for_output("long", "vertical").subtitles_for("long") is True


@pytest.mark.parametrize("clip_class", ["short", "long"])
@pytest.mark.parametrize("variant", list(VARIANT_RATIOS))
def test_each_named_render_and_caption_switch_is_available(
    clip_class, variant, monkeypatch
):
    scope = f"{clip_class}:{variant}"
    env_scope = scope.replace("-", "_").replace(":", "_").upper()
    monkeypatch.setenv("RENDER_" + env_scope, "true")
    monkeypatch.setenv("SUBTITLE_" + env_scope + "_ENABLED", "true")
    config = parse_run_config(
        [
            "source.mp4",
            "--output-dir",
            "out",
            "--clip-full",
            "--render",
            scope + "=false",
            "--subtitle-enabled",
            f"{scope}=false",
        ]
    )
    output = next(
        item
        for item in config.output_options
        if item.clip_class == clip_class and item.variant == variant
    )
    assert output.enabled is False
    assert config.for_output(clip_class, variant).subtitles_for(clip_class) is False
    config = parse_run_config(["source.mp4", "--output-dir", "out", "--clip-full"])
    output = next(
        item
        for item in config.output_options
        if item.clip_class == clip_class and item.variant == variant
    )
    assert output.enabled is True
    assert config.for_output(clip_class, variant).subtitles_for(clip_class) is True


def test_unknown_output_variant_is_a_configuration_error():
    config = parse_run_config(["source.mp4", "--output-dir", "out", "--clip-full"])
    with pytest.raises(ConfigurationError, match="Unknown output variant"):
        replace(config, render_variant="unknown")
    with pytest.raises(ConfigurationError, match="Unknown output variant"):
        config.for_output("short", "unknown")


def test_font_directory_expands_and_is_excluded_from_metadata(monkeypatch):
    monkeypatch.setenv("SUBTITLE_FONTS_DIR", "~/fonts")
    options = parse("--subtitle-font-size", "4%")
    assert options.fonts_dir == Path("~/fonts").expanduser()
    assert options.metadata() == {"font_size": "4%", "custom_fonts": True}
    assert replace(options, fonts_dir=None).metadata() == {"font_size": "4%"}


@pytest.mark.parametrize(
    "name",
    [
        "SUBTITLE_BOLD",
        "SUBTITLE_ITALIC",
        "SUBTITLE_DISABLE_CUE_ANIMATIONS",
        "SUBTITLE_DISABLE_WORD_ANIMATIONS",
    ],
)
def test_invalid_environment_booleans_fail_explicitly(name, monkeypatch):
    monkeypatch.setenv(name, "sometimes")
    with pytest.raises(ConfigurationError, match="must be a boolean"):
        parse()

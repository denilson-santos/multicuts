"""Scoped CLI controls and JSON presets share source and scope precedence."""

import json
import os
from pathlib import Path

import pytest
from typer.main import get_command

from multicuts.cli import app, main, parse_run_config
from multicuts.errors import ConfigurationError
from multicuts.models import MediaInfo


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in tuple(os.environ):
        if (
            name.startswith(("SUBTITLE_", "SHORT_", "LONG_"))
            or name == "RENDER_VARIANTS"
        ):
            monkeypatch.delenv(name)


def parse(*flags):
    return parse_run_config(
        ["source.mp4", "--output-dir", "out", "--clip-full", *flags]
    )


def preset(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("reverse", [False, True])
def test_scoped_settings_have_order_independent_specificity(reverse):
    options = [
        ["--subtitle-font-size", "4%"],
        ["--subtitle-font-size", "short=5%"],
        ["--subtitle-font-size", "short:vertical=6%"],
        ["--subtitle-enabled", "false"],
        ["--subtitle-enabled", "short=true"],
        ["--subtitle-enabled", "short:vertical=false"],
        ["--no-render", "all"],
        ["--render", "short"],
        ["--no-variants"],
        ["--render", "short:horizontal-blur"],
    ]
    config = parse(
        *(
            flag
            for option in (reversed(options) if reverse else options)
            for flag in option
        )
    )
    assert config.short_clips_enabled and not config.long_clips_enabled
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media) == ("vertical", "horizontal-blur")
    vertical = config.for_output("short", "vertical", primary=True)
    assert vertical.subtitle_options.font_size == "6%"
    assert not vertical.subtitles_for("short")
    horizontal = config.for_output("short", "horizontal-blur", primary=False)
    assert horizontal.subtitle_options.font_size == "5%"
    assert horizontal.subtitles_for("short")
    assert (
        config.for_output("long", "horizontal", primary=True).subtitle_options.font_size
        == "4%"
    )


def test_json_scopes_and_variant_switches(tmp_path):
    path = preset(
        tmp_path,
        {
            "render": {"all": False, "short": True, "short:horizontal": False},
            "variants": {"all": False, "short": True},
            "subtitles": {
                "all": {"enabled": False, "font_size": "4%"},
                "short": {"enabled": True, "font_size": "5%"},
                "short:vertical": {
                    "enabled": False,
                    "font_size": "6%",
                    "italic": False,
                },
            },
        },
    )
    config = parse("--config", path)
    assert not config.render_variants and config.variants_for("short")
    assert not config.clips_for("long")
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert len(config.outputs_for("short", media)) == 5
    assert "horizontal" not in config.outputs_for("short", media)
    assert config.subtitle_options.font_size == "4%"
    assert config.for_output("short", "square", primary=False).subtitles_for("short")
    vertical = config.for_output("short", "vertical", primary=True)
    assert not vertical.subtitles_for("short")
    assert vertical.subtitle_options.font_size == "6%"
    assert vertical.subtitle_options.italic is False


def test_cli_and_environment_override_more_specific_file_values(tmp_path, monkeypatch):
    path = preset(
        tmp_path,
        {
            "variants": {"short": False},
            "render": {"long": False, "short:horizontal": False},
            "subtitles": {"short:vertical": {"font_size": "6%", "enabled": True}},
        },
    )
    (tmp_path / ".env").write_text(
        "SUBTITLE_FONT_SIZE=7%\nRENDER_VARIANTS=true\n", encoding="utf-8"
    )
    config = parse("--config", path)
    assert (
        config.for_output("short", "vertical", primary=True).subtitle_options.font_size
        == "7%"
    )
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert "horizontal" in config.outputs_for("short", media)
    assert config.variants_for("short")
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "8%")
    monkeypatch.setenv("LONG_CLIPS_ENABLED", "true")
    assert parse("--config", path).long_clips_enabled
    monkeypatch.setenv("SUBTITLE_SHORT_VERTICAL_FONT_SIZE", "9%")
    config = parse(
        "--config", path, "--subtitle-font-size", "10%", "--subtitle-enabled", "false"
    )
    vertical = config.for_output("short", "vertical", primary=True)
    assert vertical.subtitle_options.font_size == "10%"
    assert not vertical.subtitles_for("short")


def test_config_paths_are_relative_to_preset_and_cli_paths_to_cwd(tmp_path):
    directory = tmp_path / "presets"
    directory.mkdir()
    (directory / "templates").mkdir()
    path = preset(
        directory,
        {
            "subtitles": {
                "all": {"fonts_dir": "fonts", "template_dir": "templates"},
                "short:vertical": {"fonts_dir": "vertical-fonts"},
            }
        },
    )
    config = parse("--config", path)
    assert config.subtitle_template_dir == directory / "templates"
    assert config.subtitle_options.fonts_dir == directory / "fonts"
    assert (
        config.for_output("short", "vertical", primary=True).subtitle_options.fonts_dir
        == directory / "vertical-fonts"
    )
    assert config.for_output(
        "short", "vertical", primary=True
    ).subtitle_options.metadata() == {"custom_fonts": True}
    config = parse("--config", path, "--subtitle-fonts-dir", "local-fonts")
    assert config.for_output(
        "short", "vertical", primary=True
    ).subtitle_options.fonts_dir == Path("local-fonts")


@pytest.mark.parametrize(
    "contents",
    [
        "{",
        "[]",
        "null",
        '{"render":{"short":true,"short":false}}',
        '{"source":"video.mp4"}',
        '{"subtitles":[]}',
        '{"render":{"vertical":true}}',
        '{"render":{"short":"false"}}',
        '{"variants":{"short:vertical":false}}',
        '{"subtitles":{"short:vertical":{"unknown":"4%"}}}',
        '{"subtitles":{"all":{"enabled":"false"}}}',
        '{"subtitles":{"all":{"italic":0}}}',
        '{"subtitles":{"all":{"font_size":4}}}',
        '{"subtitles":{"all":{"font_size":""}}}',
    ],
)
def test_invalid_presets_fail_as_configuration_errors(contents, tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ConfigurationError):
        parse("--config", str(path))


@pytest.mark.parametrize(
    "scope",
    ["vertical", "short:", "short:wide", "short:vertical:extra", "all:vertical"],
)
def test_invalid_scopes_fail_before_media_work(scope):
    with pytest.raises(ConfigurationError, match="scope"):
        parse("--render", scope)
    with pytest.raises(ConfigurationError, match="scope"):
        parse("--subtitle-font-size", scope + "=4%")


@pytest.mark.parametrize(
    "flags",
    [
        ["--render", "short:vertical", "--no-render", "short:vertical"],
        ["--subtitle-font-size", "short=4%", "--subtitle-font-size", "short=5%"],
        ["--subtitle-enabled", "short=true", "--subtitle-enabled", "short=false"],
    ],
)
def test_contradictory_values_for_the_same_scope_are_rejected(flags):
    with pytest.raises(ConfigurationError, match="Conflicting"):
        parse(*flags)


def test_missing_or_unreadable_config_stops_before_pipeline(tmp_path):
    called = False

    def pipeline(_config):
        nonlocal called
        called = True
        raise AssertionError("Pipeline must not run")

    assert (
        main(
            [
                "source.mp4",
                "--output-dir",
                "out",
                "--clip-full",
                "--config",
                "missing.json",
            ],
            pipeline=pipeline,
        )
        == 2
    )
    path = tmp_path / "invalid.json"
    path.write_bytes(b"\xff")
    with pytest.raises(ConfigurationError, match="UTF-8 JSON"):
        parse("--config", str(path))
    assert not called


def test_help_has_one_repeatable_option_per_presentation_field():
    command = get_command(app)
    flags = [
        flag
        for param in command.params
        for flag in (*param.opts, *getattr(param, "secondary_opts", ()))
    ]
    assert len(flags) == len(set(flags)) < 150
    assert flags.count("--subtitle-font-size") == 1
    assert "--subtitle-short-vertical-font-size" not in flags

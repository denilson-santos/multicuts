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
        if name.startswith(
            (
                "SUBTITLE_",
                "RENDER",
                "VARIANTS",
                "PRIMARY",
                "ASPECT_RATIO",
                "WIDTH",
                "HEIGHT",
            )
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
        ["--render", "false"],
        ["--render", "short=primary"],
        ["--primary", "short=vertical"],
        ["--render", "short:horizontal-blur=true"],
    ]
    config = parse(
        *(
            flag
            for option in (reversed(options) if reverse else options)
            for flag in option
        )
    )
    assert config.clips_for("short") and not config.clips_for("long")
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media) == ("vertical", "horizontal-blur")
    vertical = config.for_output("short", "vertical")
    assert vertical.subtitle_options.font_size == "6%"
    assert not vertical.subtitles_for("short")
    horizontal = config.for_output("short", "horizontal-blur")
    assert horizontal.subtitle_options.font_size == "5%"
    assert horizontal.subtitles_for("short")
    assert config.for_output("long", "horizontal").subtitle_options.font_size == "4%"


def test_json_scopes_and_variant_switches(tmp_path):
    path = preset(
        tmp_path,
        {
            "render": {"all": False, "short": True, "short:horizontal": False},
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
    assert config.render_for("short") is True
    assert not config.clips_for("long")
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert len(config.outputs_for("short", media)) == 5
    assert "horizontal" not in config.outputs_for("short", media)
    assert config.subtitle_options.font_size == "4%"
    assert config.for_output("short", "square").subtitles_for("short")
    vertical = config.for_output("short", "vertical")
    assert not vertical.subtitles_for("short")
    assert vertical.subtitle_options.font_size == "6%"
    assert vertical.subtitle_options.italic is False


def test_cli_and_environment_override_more_specific_file_values(tmp_path, monkeypatch):
    path = preset(
        tmp_path,
        {
            "render": {"long": False, "short:horizontal": False},
            "subtitles": {"short:vertical": {"font_size": "6%", "enabled": True}},
        },
    )
    (tmp_path / ".env").write_text(
        "SUBTITLE_FONT_SIZE=7%\nRENDER=true\n", encoding="utf-8"
    )
    config = parse("--config", path)
    assert config.for_output("short", "vertical").subtitle_options.font_size == "7%"
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert "horizontal" in config.outputs_for("short", media)
    assert config.render_for("short") is True
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "8%")
    monkeypatch.setenv("RENDER_LONG", "true")
    assert parse("--config", path).clips_for("long")
    monkeypatch.setenv("SUBTITLE_SHORT_VERTICAL_FONT_SIZE", "9%")
    config = parse(
        "--config", path, "--subtitle-font-size", "10%", "--subtitle-enabled", "false"
    )
    vertical = config.for_output("short", "vertical")
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
        config.for_output("short", "vertical").subtitle_options.fonts_dir
        == directory / "vertical-fonts"
    )
    assert config.for_output("short", "vertical").subtitle_options.metadata() == {
        "custom_fonts": True
    }
    config = parse("--config", path, "--subtitle-fonts-dir", "local-fonts")
    assert config.for_output("short", "vertical").subtitle_options.fonts_dir == Path(
        "local-fonts"
    )


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
        parse("--render", scope + "=true")
    with pytest.raises(ConfigurationError, match="scope"):
        parse("--subtitle-font-size", scope + "=4%")


@pytest.mark.parametrize(
    "flags",
    [
        ["--render", "short:vertical=true", "--render", "short:vertical=false"],
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


@pytest.mark.parametrize("source", ["cli", "process", "dotenv", "json"])
def test_primary_format_and_dimensions_are_scoped(source, tmp_path, monkeypatch):
    settings = {
        "primary": {"short": "square"},
        "width": {"short:square": 720, "long:horizontal-blur": 640},
    }
    flags = []
    if source == "cli":
        flags = [
            "--primary",
            "short=square",
            "--width",
            "short:square=720",
            "--width",
            "long:horizontal-blur=640",
        ]
    elif source == "json":
        flags = ["--config", preset(tmp_path, settings)]
    else:
        values = {
            "PRIMARY_SHORT": "square",
            "WIDTH_SHORT_SQUARE": "720",
            "WIDTH_LONG_HORIZONTAL_BLUR": "640",
        }
        if source == "process":
            for name, raw in values.items():
                monkeypatch.setenv(name, raw)
        else:
            (tmp_path / ".env").write_text(
                "\n".join(f"{name}={raw}" for name, raw in values.items()),
                encoding="utf-8",
            )
    config = parse(*flags)
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media)[0] == "square"
    square = config.for_output("short", "square")
    assert square.dimensions_for("short", "square") == (720, 720)
    blur = config.for_output("long", "horizontal-blur")
    assert blur.dimensions_for("long", "horizontal-blur") == (640, 360)
    assert config.dimensions_for("long", "horizontal") == (1920, 1080)
    assert config.dimensions_for("short", "vertical") == (1080, 1920)


def test_dimension_inheritance_and_source_precedence(tmp_path, monkeypatch):
    path = preset(
        tmp_path, {"width": {"short:vertical": 360}, "primary": {"short": "square"}}
    )
    (tmp_path / ".env").write_text("WIDTH_SHORT_VERTICAL=720\n", encoding="utf-8")
    monkeypatch.setenv("WIDTH", "1080")
    config = parse("--config", path)
    vertical = config.for_output("short", "vertical")
    assert vertical.dimensions_for("short", "vertical") == (1080, 1920)
    config = parse("--config", path, "--width", "short=720", "--primary", "horizontal")
    assert config.short_primary == config.long_primary == "horizontal"
    vertical = config.for_output("short", "vertical")
    assert vertical.dimensions_for("short", "vertical") == (720, 1280)
    horizontal = config.for_output("short", "horizontal")
    assert horizontal.dimensions_for("short", "horizontal") == (720, 406)
    assert config.dimensions_for("short", "square") == (720, 720)
    monkeypatch.delenv("WIDTH")
    config = parse("--height", "long:vertical-blur=1280")
    vertical = config.for_output("long", "vertical-blur")
    assert vertical.dimensions_for("long", "vertical-blur") == (720, 1280)


@pytest.mark.parametrize("field", ["primary"])
def test_primary_controls_reject_named_variant_scopes(field):
    with pytest.raises(ConfigurationError, match="scopes must be all, short, or long"):
        parse("--" + field, "short:vertical=true")


@pytest.mark.parametrize("field", ["width", "height"])
@pytest.mark.parametrize("raw", ["0", "-2", "721", "true", "NaN", "7.2"])
def test_dimensions_require_positive_even_integers(field, raw):
    with pytest.raises(ConfigurationError):
        parse("--" + field, "short:vertical=" + raw)


def test_invalid_enabled_dimensions_fail_during_output_planning():
    config = parse(
        "--render",
        "primary",
        "--primary",
        "short=vertical",
        "--width",
        "short=720",
        "--height",
        "short=720",
    )
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    with pytest.raises(ConfigurationError, match="dimensions must be vertical"):
        config.outputs_for("short", media)


@pytest.mark.parametrize(
    "contents",
    [
        {"width": {"all": True}},
        {"height": {"short": "720"}},
        {"width": {"short:vertical": 721}},
        {"primary": {"short": "2:1"}},
        {"primary": {"short:vertical": "9:16"}},
    ],
)
def test_new_preset_fields_are_strict(contents, tmp_path):
    with pytest.raises(ConfigurationError):
        parse("--config", preset(tmp_path, contents))


def test_rendered_help_and_readme_show_every_scoped_option(monkeypatch):
    import re

    from typer.testing import CliRunner

    monkeypatch.setenv("COLUMNS", "300")
    result = CliRunner().invoke(app, ["--help"], color=False)
    assert result.exit_code == 0
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(
        encoding="utf-8"
    )
    for param in get_command(app).params:
        if getattr(param, "multiple", False):
            assert param.metavar == "[SCOPE=]VALUE"
            flag = param.opts[0]
            assert re.search(re.escape(flag) + r"\s+\[SCOPE=\]VALUE", result.stdout)
            assert f"`{flag} [SCOPE=]VALUE`" in readme
    assert "--no-render" not in result.stdout
    assert "--no-subtitle" not in result.stdout


@pytest.mark.parametrize(
    "flag",
    [
        "--no-render",
        "--no-variants",
        "--variants",
        "--short-clips",
        "--short-aspect-ratio",
        "--aspect-ratio",
        "--square-size",
        "--no-subtitles",
        "--no-subtitle-bold",
    ],
)
def test_removed_flags_are_rejected(flag):
    with pytest.raises(SystemExit) as error:
        parse(flag)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "name",
    [
        "SHORT_CLIPS_ENABLED",
        "LONG_CLIPS_ENABLED",
        "RENDER_VARIANTS",
        "VARIANTS",
        "VARIANTS_SHORT",
        "VARIANTS_LONG",
        "SHORT_VARIANTS_ENABLED",
        "LONG_VARIANTS_ENABLED",
        "SHORT_SUBTITLES_ENABLED",
        "LONG_SUBTITLES_ENABLED",
        "SHORT_VARIANT_SUBTITLES_ENABLED",
        "LONG_VARIANT_SUBTITLES_ENABLED",
        "SHORT_HORIZONTAL_BLUR_ENABLED",
        "SUBTITLES_ENABLED",
        "SHORT_ASPECT_RATIO",
        "ASPECT_RATIO",
        "ASPECT_RATIO_SHORT",
        "ASPECT_RATIO_LONG",
        "LONG_ASPECT_RATIO",
        "VERTICAL_WIDTH",
        "VERTICAL_HEIGHT",
        "HORIZONTAL_WIDTH",
        "HORIZONTAL_HEIGHT",
        "SQUARE_SIZE",
    ],
)
def test_removed_environment_names_do_not_configure_outputs(name, monkeypatch):
    monkeypatch.setenv(name, "obsolete-value")
    config = parse()
    assert config.clips_for("short") and config.clips_for("long")
    assert config.render_for("short") is True and config.render_for("long") is True
    assert config.dimensions_for("short", "vertical") == (1080, 1920)
    assert config.dimensions_for("long", "horizontal") == (1920, 1080)
    assert config.dimensions_for("short", "square") == (1080, 1080)
    assert config.short_primary == "auto"
    assert config.long_primary == "auto"
    assert config.for_output("short", "horizontal-blur").subtitles_for("short")


@pytest.mark.parametrize("kind", ["short", "long"])
@pytest.mark.parametrize(
    ("variant", "width", "height", "ratio"),
    [
        ("horizontal", 2520, 1080, "7:3"),
        ("vertical", 1080, 1350, "4:5"),
        ("square", 720, 720, "1:1"),
        ("horizontal-blur", 2400, 1000, "12:5"),
        ("vertical-blur", 1000, 1600, "5:8"),
        ("square-blur", 640, 640, "1:1"),
    ],
)
def test_dimensions_define_each_variant_ratio_independently(
    kind, variant, width, height, ratio
):
    scope = f"{kind}:{variant}"
    config = parse("--width", f"{scope}={width}", "--height", f"{scope}={height}")
    assert config.dimensions_for(kind, variant) == (width, height)
    assert config.aspect_ratio_for(kind, variant) == ratio
    other = "long" if kind == "short" else "short"
    assert (
        config.dimensions_for(other, variant)
        == {
            "horizontal": (1920, 1080),
            "vertical": (1080, 1920),
            "square": (1080, 1080),
        }[variant.removesuffix("-blur")]
    )
    assert (
        config.primary_for(kind, MediaInfo(60, 640, 360, 640, 360, 0, None))
        == "horizontal"
    )


@pytest.mark.parametrize(
    ("variant", "width", "height"),
    [
        ("horizontal", 1080, 1350),
        ("horizontal-blur", 1000, 1000),
        ("vertical", 1350, 1080),
        ("vertical-blur", 1000, 1000),
        ("square", 1080, 720),
        ("square-blur", 720, 1080),
    ],
)
def test_dimension_pairs_enforce_variant_orientation_before_output(
    variant, width, height
):
    config = parse(
        "--width", f"short:{variant}={width}", "--height", f"short:{variant}={height}"
    )
    media = MediaInfo(60, 2520, 1080, 2520, 1080, 0, None)
    with pytest.raises(ConfigurationError, match="dimensions must be"):
        config.outputs_for("short", media)


def test_invalid_dimensions_on_disabled_output_do_not_block_other_outputs():
    config = parse(
        "--render",
        "short:vertical=false",
        "--width",
        "short:vertical=720",
        "--height",
        "short:vertical=720",
    )
    media = MediaInfo(60, 2520, 1080, 2520, 1080, 0, None)
    assert "vertical" not in config.outputs_for("short", media)
    assert len(config.outputs_for("short", media)) == 5


def test_dimension_fields_resolve_independently_across_sources(tmp_path, monkeypatch):
    path = preset(
        tmp_path,
        {
            "width": {"short:horizontal": 2520},
            "height": {"short:horizontal": 1080},
            "primary": {"short": "horizontal"},
        },
    )
    monkeypatch.setenv("WIDTH_SHORT", "1920")
    config = parse("--config", path)
    assert config.dimensions_for("short", "horizontal") == (1920, 1080)
    config = parse(
        "--config",
        path,
        "--width",
        "short:horizontal=1440",
        "--primary",
        "short=square",
    )
    assert config.dimensions_for("short", "horizontal") == (1440, 1080)
    assert config.aspect_ratio_for("short", "horizontal") == "4:3"
    assert config.short_primary == "square"
    assert config.dimensions_for("short", "square") == (1920, 1920)


@pytest.mark.parametrize(
    "variant",
    [
        "horizontal",
        "vertical",
        "square",
        "horizontal-blur",
        "vertical-blur",
        "square-blur",
    ],
)
def test_primary_selects_named_output_without_changing_dimensions(variant):
    config = parse(
        "--primary",
        f"short={variant}",
        "--render",
        "short=primary",
        "--width",
        "short:horizontal=2520",
        "--height",
        "short:horizontal=1080",
    )
    media = MediaInfo(60, 2520, 1080, 2520, 1080, 0, None)
    assert config.outputs_for("short", media) == (variant,)
    assert config.dimensions_for("short", "horizontal") == (2520, 1080)
    assert config.outputs_for("long", media)[0] == "horizontal"


@pytest.mark.parametrize("value", ["original", "16:9", "9:16", "1:1", "wide"])
def test_primary_rejects_removed_or_unknown_values(value):
    with pytest.raises(ConfigurationError, match="must name an output variant"):
        parse("--primary", "short=" + value)


@pytest.mark.parametrize("kind", ["short", "long"])
@pytest.mark.parametrize("mode", ["true", "primary"])
@pytest.mark.parametrize(
    ("dimensions", "primary", "count"),
    [
        ((2520, 1080), "horizontal", 6),
        ((1080, 1350), "vertical", 4),
        ((1080, 1080), "square", 5),
    ],
)
def test_auto_primary_follows_source_orientation_for_both_classes(
    kind, mode, dimensions, primary, count
):
    width, height = dimensions
    media = MediaInfo(360, width, height, width, height, 0, None)
    config = parse("--render", f"{kind}={mode}")
    assert config.primary_for(kind, media) == primary
    outputs = config.outputs_for(kind, media)
    assert outputs[0] == primary
    assert len(outputs) == (1 if mode == "primary" else count)


def test_auto_primary_uses_presentation_geometry():
    media = MediaInfo(60, 1920, 1080, 1080, 1920, 0, None, rotation_degrees=90)
    config = parse("--render", "primary")
    assert config.outputs_for("short", media) == ("vertical",)
    assert config.outputs_for("long", media) == ("vertical",)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("parent", ["false", "short=false"])
def test_named_render_can_enable_an_output_under_a_disabled_parent(parent, reverse):
    assignments = [parent, "short:square=true"]
    if reverse:
        assignments.reverse()
    config = parse(*(flag for value in assignments for flag in ("--render", value)))
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.clips_for("short")
    assert config.outputs_for("short", media) == ("square",)
    assert config.clips_for("long") is (parent != "false")


def test_primary_only_with_named_addition_and_disabled_primary():
    config = parse("--render", "primary", "--render", "short:square=true")
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media) == ("horizontal", "square")
    assert config.outputs_for("long", media) == ("horizontal",)
    config = parse(
        "--render",
        "primary",
        "--render",
        "short:square=true",
        "--render",
        "short:horizontal=false",
    )
    assert config.outputs_for("short", media) == ("square",)


@pytest.mark.parametrize("source", ["dotenv", "process", "json"])
@pytest.mark.parametrize("value", ["true", "false", "primary"])
def test_cli_render_policy_overrides_lower_priority_named_settings(
    source, value, tmp_path, monkeypatch
):
    flags = []
    if source == "json":
        flags = ["--config", preset(tmp_path, {"render": {"short:square": True}})]
    elif source == "process":
        monkeypatch.setenv("RENDER_SHORT_SQUARE", "true")
    else:
        (tmp_path / ".env").write_text("RENDER_SHORT_SQUARE=true\n", encoding="utf-8")
    config = parse(*flags, "--render", "short=" + value)
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    outputs = config.outputs_for("short", media)
    assert len(outputs) == {"true": 6, "false": 0, "primary": 1}[value]


def test_process_render_policy_overrides_dotenv_and_preset_named_settings(
    tmp_path, monkeypatch
):
    path = preset(tmp_path, {"render": {"short:square": True}})
    (tmp_path / ".env").write_text("RENDER_SHORT_VERTICAL=true\n", encoding="utf-8")
    monkeypatch.setenv("RENDER", "primary")
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert parse("--config", path).outputs_for("short", media) == ("horizontal",)


@pytest.mark.parametrize("source", ["dotenv", "process", "json"])
def test_primary_render_and_auto_primary_are_available_in_all_sources(
    source, tmp_path, monkeypatch
):
    flags = []
    if source == "json":
        flags = [
            "--config",
            preset(
                tmp_path,
                {
                    "render": {"all": "primary", "short:square": True},
                    "primary": {"all": "auto", "long": "square"},
                },
            ),
        ]
    else:
        settings = {
            "RENDER": "primary",
            "RENDER_SHORT_SQUARE": "true",
            "PRIMARY": "auto",
            "PRIMARY_LONG": "square",
        }
        if source == "process":
            for key, value in settings.items():
                monkeypatch.setenv(key, value)
        else:
            (tmp_path / ".env").write_text(
                "\n".join(f"{key}={value}" for key, value in settings.items()) + "\n",
                encoding="utf-8",
            )
    config = parse(*flags)
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media) == ("horizontal", "square")
    assert config.outputs_for("long", media) == ("square",)


@pytest.mark.parametrize("source", ["cli", "dotenv", "process", "json"])
def test_named_render_rejects_primary_value(source, tmp_path, monkeypatch):
    flags = []
    if source == "cli":
        flags = ["--render", "short:vertical=primary"]
    elif source == "json":
        flags = [
            "--config",
            preset(tmp_path, {"render": {"short:vertical": "primary"}}),
        ]
    elif source == "process":
        monkeypatch.setenv("RENDER_SHORT_VERTICAL", "primary")
    else:
        (tmp_path / ".env").write_text(
            "RENDER_SHORT_VERTICAL=primary\n", encoding="utf-8"
        )
    with pytest.raises(ConfigurationError):
        parse(*flags)


@pytest.mark.parametrize("value", [0, 1, None, [], {}, "true", "false", "all"])
def test_render_preset_values_are_strict(value, tmp_path):
    with pytest.raises(ConfigurationError):
        parse("--config", preset(tmp_path, {"render": {"all": value}}))


def test_removed_variants_preset_group_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="accepts only"):
        parse("--config", preset(tmp_path, {"variants": {}}))


@pytest.mark.parametrize("flag", ["--render", "--width", "--subtitle-font-size"])
def test_original_is_not_an_output_scope(flag):
    with pytest.raises(ConfigurationError, match="scope"):
        parse(flag, "short:original=true")


def test_preset_rejects_removed_aspect_ratio_group(tmp_path):
    with pytest.raises(ConfigurationError, match="accepts only"):
        parse("--config", preset(tmp_path, {"aspect_ratio": {"short": "original"}}))

"""Scoped CLI controls and JSON presets share source and scope precedence."""

import json
import os
from pathlib import Path

import pytest
from typer.main import get_command

from multicuts.cli import app, main, parse_run_config
from multicuts.errors import ConfigurationError
from multicuts.models import MediaInfo
from multicuts.subtitles import SUBTITLE_BOOLEAN_FIELDS
from multicuts.variants import VARIANTS


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in tuple(os.environ):
        if name.startswith(
            (
                "SUBTITLE_",
                "SUBTITLES",
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


@pytest.mark.parametrize("field", ["render", "subtitles"])
@pytest.mark.parametrize("source", ["cli", "process", "dotenv", "json"])
@pytest.mark.parametrize(
    ("tokens", "short", "long"),
    [
        ([], VARIANTS, VARIANTS),
        (["all:vertical=true"], ("vertical",), ("vertical",)),
        (
            ["all:vertical=false"],
            set(VARIANTS) - {"vertical"},
            set(VARIANTS) - {"vertical"},
        ),
        (
            ["all:vertical=true", "all:square=true"],
            ("vertical", "square"),
            ("vertical", "square"),
        ),
        (["short=true"], VARIANTS, ()),
        (["short=false"], (), VARIANTS),
        (["long=true"], (), VARIANTS),
        (["short:vertical=true"], ("vertical",), ()),
        (["short:vertical=false"], set(VARIANTS) - {"vertical"}, VARIANTS),
        (["all:vertical=true", "short:vertical=false"], (), ("vertical",)),
        (["all:vertical=true", "all:square=false"], ("vertical",), ("vertical",)),
        (["true", "all:vertical=true"], VARIANTS, VARIANTS),
        (["false", "all:vertical=true"], ("vertical",), ("vertical",)),
        (["short=true", "all:vertical=false"], set(VARIANTS) - {"vertical"}, ()),
    ],
)
def test_render_and_caption_controls_select_or_exclude_outputs(
    field, source, tokens, short, long, tmp_path, monkeypatch
):
    flags = []
    name = field.upper().replace("-", "_")
    if source == "cli" and tokens:
        flags = [f"--{field}={tokens[0]}", *tokens[1:]]
    elif source == "json":
        assignments = {}
        for token in tokens:
            scope, separator, raw = token.partition("=")
            if not separator:
                scope, raw = "all", token
            assignments[scope] = raw == "true"
        data = (
            {"render": assignments}
            if field == "render"
            else {
                "subtitles": {
                    scope: {"enabled": value} for scope, value in assignments.items()
                }
            }
        )
        flags = ["--config", preset(tmp_path, data)]
    elif source == "process":
        monkeypatch.setenv(name, " ".join(tokens))
    elif source == "dotenv":
        (tmp_path / ".env").write_text(
            f'{name}="{" ".join(tokens)}"\n', encoding="utf-8"
        )
    config = parse(*flags)
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    for kind, expected in (("short", short), ("long", long)):
        outputs = config.outputs_for(kind, media)
        captions = tuple(
            variant
            for variant in outputs
            if config.for_output(kind, variant).subtitles_for(kind)
        )
        if field == "render":
            assert set(outputs) == set(expected)
            assert captions == outputs
        else:
            assert set(outputs) == set(VARIANTS)
            assert set(captions) == set(expected)


@pytest.mark.parametrize("field", ["render", "subtitles"])
@pytest.mark.parametrize("source", ["cli", "process", "dotenv"])
@pytest.mark.parametrize(
    "tokens",
    [
        ["all:vertical"],
        ["all:vertical-blur"],
        ["short"],
        ["all:vertical", "all:square"],
        ["short:vertical", "long:square=false"],
        ["all", "all:vertical=false"],
    ],
)
def test_selection_scopes_without_values_mean_true(
    field, source, tokens, tmp_path, monkeypatch
):
    explicit = [token if "=" in token else token + "=true" for token in tokens]
    expected = parse(f"--{field}", *explicit)
    if source == "cli":
        actual = parse(f"--{field}={tokens[0]}", *tokens[1:])
    else:
        name = field.upper()
        if source == "process":
            monkeypatch.setenv(name, " ".join(tokens))
        else:
            (tmp_path / ".env").write_text(
                f'{name}="{" ".join(tokens)}"\n', encoding="utf-8"
            )
        actual = parse()
    assert actual == expected


@pytest.mark.parametrize(
    "field",
    [
        "render",
        "subtitles",
        *(
            "subtitle-" + name.replace("_", "-")
            for name in sorted(SUBTITLE_BOOLEAN_FIELDS)
        ),
    ],
)
@pytest.mark.parametrize("trailing_source", ["source.mp4", "https://example.com/video"])
def test_grouped_selection_scopes_before_source_preserve_the_source(
    field, trailing_source
):
    config = parse_run_config(
        [
            "--output-dir",
            "out",
            "--clip-full",
            f"--{field}=all:vertical",
            "all:square",
            trailing_source,
        ]
    )
    assert config.source == trailing_source
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    for kind in ("short", "long"):
        outputs = config.outputs_for(kind, media)
        if field in ("render", "subtitles"):
            selected = {
                variant
                for variant in outputs
                if field == "render"
                or config.for_output(kind, variant).subtitles_for(kind)
            }
            assert selected == {"vertical", "square"}
        else:
            assert set(outputs) == set(VARIANTS)
            option = field.removeprefix("subtitle-").replace("-", "_")
            assert {
                variant
                for variant in outputs
                if getattr(config.for_output(kind, variant).subtitle_options, option)
            } == {"vertical", "square"}


@pytest.mark.parametrize("field", sorted(SUBTITLE_BOOLEAN_FIELDS))
@pytest.mark.parametrize("source", ["cli", "process", "dotenv"])
def test_visual_boolean_shorthand_does_not_select_outputs(
    field, source, tmp_path, monkeypatch
):
    flag = "--subtitle-" + field.replace("_", "-")
    expected = parse(flag, "all:vertical=true")
    if source == "cli":
        actual = parse(flag, "all:vertical")
    else:
        name = "SUBTITLE_" + field.upper()
        if source == "process":
            monkeypatch.setenv(name, "all:vertical")
        else:
            (tmp_path / ".env").write_text(f"{name}=all:vertical\n", encoding="utf-8")
        actual = parse()
    assert actual == expected
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    for kind in ("short", "long"):
        assert set(actual.outputs_for(kind, media)) == set(VARIANTS)
        for variant in VARIANTS:
            output = actual.for_output(kind, variant)
            assert output.subtitles_for(kind)
            assert getattr(output.subtitle_options, field) is (
                True if variant == "vertical" else None
            )


@pytest.mark.parametrize("field", ["render", "subtitles"])
def test_selection_source_replaces_lower_selections_without_changing_style_inheritance(
    field, tmp_path, monkeypatch
):
    name = field.upper().replace("-", "_")
    data = (
        {"render": {"all": True}, "subtitles": {"all": {"font_size": "4%"}}}
        if field == "render"
        else {"subtitles": {"all": {"font_size": "4%", "enabled": True}}}
    )
    path = preset(tmp_path, data)
    (tmp_path / ".env").write_text(f'{name}="long:horizontal=true"\n', encoding="utf-8")
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)

    def selected(flags=()):
        config = parse("--config", path, *flags)
        assert config.for_output("long", "square").subtitle_options.font_size == "4%"
        return tuple(
            {
                variant
                for variant in config.outputs_for(kind, media)
                if field == "render"
                or config.for_output(kind, variant).subtitles_for(kind)
            }
            for kind in ("short", "long")
        )

    assert selected() == (set(), {"horizontal"})
    monkeypatch.setenv(name, "all:vertical=false")
    assert selected() == (set(VARIANTS) - {"vertical"},) * 2
    assert selected([f"--{field}", "short:vertical=true"]) == ({"vertical"}, set())
    assert selected([f"--{field}", "true", "short:vertical=false"]) == (
        set(VARIANTS) - {"vertical"},
        set(VARIANTS),
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    ("base", "short", "long"),
    [
        ("primary", ("horizontal", "square"), ("horizontal", "square")),
        ("short=primary", ("horizontal", "square"), ("square",)),
        ("long=primary", ("square",), ("horizontal", "square")),
    ],
)
def test_explicit_primary_base_and_named_additions_remain_order_independent(
    reverse, base, short, long
):
    tokens = [base, "all:square=true"]
    if reverse:
        tokens.reverse()
    config = parse("--render", *tokens)
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media) == short
    assert config.outputs_for("long", media) == long


def test_visual_options_and_primary_preference_do_not_select_outputs():
    config = parse(
        "--primary",
        "vertical",
        "--width",
        "all:vertical=720",
        "--subtitle-margin-bottom",
        "all:vertical=8%",
        "--subtitle-italic",
        "short:vertical=true",
    )
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    for kind in ("short", "long"):
        outputs = config.outputs_for(kind, media)
        assert outputs[0] == "vertical"
        assert set(outputs) == set(VARIANTS)
        assert all(
            config.for_output(kind, variant).subtitles_for(kind) for variant in outputs
        )
        assert config.dimensions_for(kind, "vertical") == (720, 1280)
        assert (
            config.for_output(kind, "horizontal").subtitle_options.margin_bottom is None
        )
    assert config.for_output("short", "vertical").subtitle_options.italic is True
    assert config.for_output("long", "vertical").subtitle_options.italic is None


@pytest.mark.parametrize("reverse", [False, True])
def test_scoped_settings_have_order_independent_specificity(reverse):
    options = [
        ["--subtitle-font-size", "4%"],
        ["--subtitle-font-size", "short=5%"],
        ["--subtitle-font-size", "short:vertical=6%"],
        ["--subtitles", "false"],
        ["--subtitles", "short=true"],
        ["--subtitles", "short:vertical=false"],
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


@pytest.mark.parametrize("source", ["cli", "process", "dotenv", "json"])
@pytest.mark.parametrize("variant", VARIANTS)
def test_all_variant_scope_configures_both_classes_without_affecting_other_variants(
    source, variant, tmp_path, monkeypatch
):
    (tmp_path / "templates").mkdir()
    (tmp_path / "fonts").mkdir()
    scope = f"all:{variant}"
    width, height = {
        "horizontal": (1280, 720),
        "vertical": (720, 1280),
        "square": (720, 720),
    }[variant.removesuffix("-blur")]
    subtitles = {
        "enabled": False,
        "template": "amber-word",
        "template_dir": "templates",
        "fonts_dir": "fonts",
        "margin_bottom": "8%",
        "font_size": "5%",
        "italic": True,
        "animation_word_text_emphasis": "none",
    }
    values = {
        "render": ["false", f"{scope}=true"],
        "width": [f"{scope}={width}"],
        "height": [f"{scope}={height}"],
        **{
            "subtitles" if field == "enabled" else f"subtitle_{field}": [
                f"{scope}={str(value).lower() if isinstance(value, bool) else value}"
            ]
            for field, value in subtitles.items()
        },
    }
    flags = []
    if source == "cli":
        flags = [
            part
            for field, items in values.items()
            for part in ("--" + field.replace("_", "-"), *items)
        ]
    elif source == "json":
        flags = [
            "--config",
            preset(
                tmp_path,
                {
                    "render": {"all": False, scope: True},
                    "width": {scope: width},
                    "height": {scope: height},
                    "subtitles": {scope: subtitles},
                },
            ),
        ]
    elif source == "process":
        for field, items in values.items():
            monkeypatch.setenv(field.upper(), " ".join(items))
    else:
        (tmp_path / ".env").write_text(
            "\n".join(
                f"{field.upper()}='{' '.join(items)}'"
                for field, items in values.items()
            ),
            encoding="utf-8",
        )
    config = parse(*flags)
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    directory = tmp_path if source == "json" else Path()
    for kind in ("short", "long"):
        assert config.outputs_for(kind, media) == (variant,)
        assert config.dimensions_for(kind, variant) == (width, height)
        output = config.for_output(kind, variant)
        assert not output.subtitles_for(kind)
        assert output.subtitle_template == "amber-word"
        assert output.subtitle_template_dir == directory / "templates"
        assert output.subtitle_options.fonts_dir == directory / "fonts"
        assert output.subtitle_options.margin_bottom == "8%"
        assert output.subtitle_options.font_size == "5%"
        assert output.subtitle_options.italic is True
        assert output.subtitle_options.animation_word_text_emphasis == "none"
        for other in VARIANTS:
            if other != variant:
                assert (
                    config.for_output(kind, other).subtitle_options.margin_bottom
                    is None
                )


@pytest.mark.parametrize("reverse", [False, True])
def test_all_variant_scope_priority_is_independent_of_argument_order(reverse):
    options = [
        ["--subtitle-margin-bottom", "2%"],
        ["--subtitle-margin-bottom", "short=4%"],
        ["--subtitle-margin-bottom", "all:vertical=8%"],
        ["--subtitle-margin-bottom", "short:vertical=10%"],
        ["--subtitle-margin-left", "3%"],
        ["--render", "false"],
        ["--render", "short=false"],
        ["--render", "all:vertical=true"],
        ["--render", "short:vertical=false"],
    ]
    if reverse:
        options.reverse()
    config = parse(*(part for option in options for part in option))
    short = config.for_output("short", "vertical")
    long = config.for_output("long", "vertical")
    assert short.subtitle_options.margin_bottom == "10%"
    assert long.subtitle_options.margin_bottom == "8%"
    assert (
        short.subtitle_options.margin_left == long.subtitle_options.margin_left == "3%"
    )
    assert (
        config.for_output("short", "horizontal").subtitle_options.margin_bottom == "4%"
    )
    assert (
        config.for_output("long", "vertical-blur").subtitle_options.margin_bottom
        == "2%"
    )
    assert not config.clips_for("short")
    assert config.outputs_for("long", MediaInfo(60, 640, 360, 640, 360, 0, None)) == (
        "vertical",
    )


def test_all_variant_scope_respects_source_priority_per_field(tmp_path, monkeypatch):
    path = preset(
        tmp_path,
        {
            "subtitles": {
                "all:vertical": {
                    "margin_bottom": "8%",
                    "margin_left": "2%",
                    "font_size": "5%",
                }
            }
        },
    )
    (tmp_path / ".env").write_text(
        'SUBTITLE_MARGIN_BOTTOM="all:vertical=9%"\n'
        'SUBTITLE_FONT_SIZE="short:vertical=6%"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SUBTITLE_MARGIN_BOTTOM", "long=10%")
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "all:vertical=7%")
    config = parse(
        "--config",
        path,
        "--subtitle-margin-bottom",
        "short=11%",
        "--subtitle-font-size",
        "long:vertical=8%",
    )
    short = config.for_output("short", "vertical").subtitle_options
    long = config.for_output("long", "vertical").subtitle_options
    assert (short.margin_bottom, short.font_size) == ("11%", "7%")
    assert (long.margin_bottom, long.font_size) == ("10%", "8%")
    assert short.margin_left == long.margin_left == "2%"


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
    monkeypatch.setenv("RENDER", "long=true")
    assert parse("--config", path).clips_for("long")
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "short:vertical=9%")
    config = parse(
        "--config", path, "--subtitle-font-size", "10%", "--subtitles", "false"
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
    [
        "vertical",
        "short:",
        "short:wide",
        "short:vertical:extra",
        "all:",
        "all:wide",
        "all:all",
        "all:vertical:extra",
    ],
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
        ["--subtitles", "short=true", "--subtitles", "short=false"],
        ["--render", "all:vertical=true", "--render", "all:vertical=false"],
        ["--subtitle-margin-bottom", "all:vertical=8%", "all:vertical=10%"],
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
            "PRIMARY": "short=square",
            "WIDTH": "short:square=720 long:horizontal-blur=640",
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
    (tmp_path / ".env").write_text("WIDTH=short:vertical=720\n", encoding="utf-8")
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
@pytest.mark.parametrize("scope", ["short:vertical", "all:vertical"])
def test_primary_controls_reject_named_variant_scopes(field, scope):
    with pytest.raises(ConfigurationError, match="scopes must be all, short, or long"):
        parse("--" + field, f"{scope}=vertical")


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
        {"primary": {"all:vertical": "vertical"}},
    ],
)
def test_new_preset_fields_are_strict(contents, tmp_path):
    with pytest.raises(ConfigurationError):
        parse("--config", preset(tmp_path, contents))


@pytest.mark.parametrize("force_color", [False, True])
def test_rendered_help_and_readme_show_every_scoped_option(monkeypatch, force_color):
    import re

    from typer.testing import CliRunner

    monkeypatch.setenv("COLUMNS", "300")
    if force_color:
        monkeypatch.setenv("FORCE_COLOR", "1")
    else:
        monkeypatch.delenv("FORCE_COLOR", raising=False)
    result = CliRunner().invoke(app, ["--help"], color=False)
    assert result.exit_code == 0
    help_text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(
        encoding="utf-8"
    )
    for param in get_command(app).params:
        if getattr(param, "multiple", False):
            assert param.metavar == "[SCOPE=]VALUE..."
            flag = param.opts[0]
            assert re.search(re.escape(flag) + r"\s+\[SCOPE=\]VALUE\.\.\.", help_text)
            assert f"`{flag} [SCOPE=]VALUE...`" in readme
    assert "--no-render" not in help_text
    assert "--no-subtitle" not in help_text
    panels = {
        "Clip selection": ("--clip-range", "--clip-full", "--overlap-threshold"),
        "Outputs": ("--render", "--primary", "--width", "--height"),
        "Execution": ("--jobs",),
        "Video encoding": ("--video-encoder", "--video-preset", "--video-quality"),
    }
    for panel, flags in panels.items():
        assert panel in help_text
        for flag in flags:
            param = next(
                param for param in get_command(app).params if flag in param.opts
            )
            assert getattr(param, "rich_help_panel", None) == panel
    for flag in (
        "--render-jobs",
        "--render-encoder",
        "--render-preset",
        "--render-quality",
    ):
        assert flag not in help_text
    for description in (
        "default: FFmpeg selection, matching multisubs",
        "Default: medium (libx264), p4 (h264_nvenc)",
        "Default: CRF 23 (libx264), CQ 28 (h264_nvenc)",
        "Transcription language code or auto (default: auto)",
        "Same-class overlap suppression ratio (default: 0.60)",
        "Maximum simultaneous renders across cuts and variants (default: 1)",
        "default: horizontal 1920, vertical/square 1080",
        "default: vertical 1920, horizontal/square 1080",
        "Defaults shown apply when CLI, environment, .env, and JSON presets",
        "all:VARIANT",
        "--subtitle-margin-bottom all:vertical=8%",
    ):
        assert description in help_text
    for param in get_command(app).params:
        if param.opts[0].startswith("--subtitle-") and param.opts[0] not in (
            "--subtitles",
            "--subtitle-template",
            "--subtitle-template-dir",
        ):
            assert "Default: inherit selected template." in getattr(param, "help", "")


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
        "--subtitle-enabled",
        "--no-subtitle-bold",
        "--render-jobs",
        "--render-encoder",
        "--render-preset",
        "--render-quality",
    ],
)
def test_removed_flags_are_rejected(flag, capsys):
    with pytest.raises(SystemExit) as error:
        parse(flag)
    assert error.value.code == 2
    assert "No such option" in capsys.readouterr().err


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
        "SUBTITLE_ENABLED",
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
    monkeypatch.setenv("WIDTH", "short=1920")
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
    assert config.outputs_for("long", media) == ()


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


@pytest.mark.parametrize("source", ["cli", "process", "dotenv", "json"])
@pytest.mark.parametrize("kind", ["short", "long"])
@pytest.mark.parametrize("reason", ["disabled", "unavailable"])
def test_explicit_primary_must_be_rendered_and_supported(
    source, kind, reason, tmp_path, monkeypatch
):
    flags = ["--render", "all:vertical"]
    if source == "cli":
        flags += ["--primary", f"{kind}=horizontal"]
    elif source == "process":
        monkeypatch.setenv("PRIMARY", f"{kind}=horizontal")
    elif source == "dotenv":
        (tmp_path / ".env").write_text(f"PRIMARY={kind}=horizontal\n", encoding="utf-8")
    else:
        flags += ["--config", preset(tmp_path, {"primary": {kind: "horizontal"}})]
    config = parse(*flags)
    width, height = (640, 360) if reason == "disabled" else (360, 640)
    media = MediaInfo(60, width, height, width, height, 0, None)
    with pytest.raises(
        ConfigurationError, match=f"Primary output 'horizontal'.*{reason}"
    ):
        config.outputs_for(kind, media)


def test_primary_validation_uses_effective_precedence_and_allows_auto(
    tmp_path, monkeypatch
):
    path = preset(tmp_path, {"primary": {"all": "horizontal"}})
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    monkeypatch.setenv("PRIMARY", "vertical")
    config = parse("--config", path, "--render", "all:vertical")
    assert config.outputs_for("short", media) == ("vertical",)
    monkeypatch.setenv("PRIMARY", "horizontal")
    config = parse("--config", path, "--render", "all:vertical", "--primary", "auto")
    assert config.outputs_for("short", media) == ("vertical",)
    assert config.outputs_for("long", media) == ("vertical",)


def test_explicit_primary_in_disabled_class_is_not_validated():
    config = parse("--render", "short", "--primary", "long=horizontal")
    media = MediaInfo(60, 360, 640, 360, 640, 0, None)
    assert config.outputs_for("long", media) == ()
    assert config.outputs_for("short", media)[0] == "vertical"


@pytest.mark.parametrize("source", ["cli", "process", "dotenv", "json"])
@pytest.mark.parametrize(
    ("render", "captions", "valid"),
    [
        ("all:horizontal", ["all:vertical=true"], False),
        ("all:horizontal", ["false", "all:vertical=true"], False),
        ("long:vertical", ["short:vertical=true"], False),
        ("all:vertical", ["all:vertical=true"], True),
        ("all:vertical", ["short:vertical=true"], True),
        ("all:horizontal", ["false"], True),
        ("all:horizontal", ["all:horizontal=false"], True),
        ("all:horizontal", ["true", "all:horizontal=false"], True),
    ],
)
def test_caption_selection_must_reach_a_rendered_output_unless_intentionally_disabled(
    source, render, captions, valid, tmp_path, monkeypatch
):
    flags = ["--render", render]
    if source == "cli":
        flags += ["--subtitles", *captions]
    elif source == "process":
        monkeypatch.setenv("SUBTITLES", " ".join(captions))
    elif source == "dotenv":
        (tmp_path / ".env").write_text(
            f'SUBTITLES="{" ".join(captions)}"\n', encoding="utf-8"
        )
    else:
        settings = {}
        for token in captions:
            scope, separator, value = token.partition("=")
            if not separator:
                scope, value = "all", token
            settings[scope] = {"enabled": value == "true"}
        flags += ["--config", preset(tmp_path, {"subtitles": settings})]
    config = parse(*flags)
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    outputs = {kind: config.outputs_for(kind, media) for kind in ("short", "long")}
    if valid:
        config.validate_subtitle_selection(outputs)
    else:
        with pytest.raises(
            ConfigurationError, match="Subtitle selection matches no enabled output"
        ):
            config.validate_subtitle_selection(outputs)


def test_caption_validation_uses_precedence_and_ignores_unused_geometry(
    tmp_path, monkeypatch
):
    path = preset(
        tmp_path,
        {"subtitles": {"all:vertical": {"enabled": True}}},
    )
    monkeypatch.setenv("SUBTITLES", "false")
    config = parse("--config", path, "--render", "all:horizontal")
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    config.validate_subtitle_selection({"short": config.outputs_for("short", media)})
    config = parse(
        "--render",
        "all:vertical",
        "--subtitles",
        "all:vertical",
        "--width",
        "all:horizontal=720",
        "--height",
        "all:horizontal=720",
    )
    config.validate_subtitle_selection({"short": config.outputs_for("short", media)})


def test_caption_positive_parent_cancelled_by_negative_children_can_disable_all():
    config = parse(
        "--render",
        "all:horizontal",
        "--subtitles",
        "short",
        *(f"short:{variant}=false" for variant in VARIANTS),
    )
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    config.validate_subtitle_selection({"short": config.outputs_for("short", media)})
    assert not any(config.subtitles_for("short", variant) for variant in VARIANTS)


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
    assert not config.clips_for("long")


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
@pytest.mark.parametrize("scope", ["short:square", "all:square"])
def test_cli_render_policy_overrides_lower_priority_named_settings(
    source, value, scope, tmp_path, monkeypatch
):
    flags = []
    if source == "json":
        flags = ["--config", preset(tmp_path, {"render": {scope: True}})]
    elif source == "process":
        monkeypatch.setenv("RENDER", f"{scope}=true")
    else:
        (tmp_path / ".env").write_text(f"RENDER={scope}=true\n", encoding="utf-8")
    config = parse(*flags, "--render", "short=" + value)
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    outputs = config.outputs_for("short", media)
    assert len(outputs) == {"true": 6, "false": 0, "primary": 1}[value]


def test_process_render_policy_overrides_dotenv_and_preset_named_settings(
    tmp_path, monkeypatch
):
    path = preset(tmp_path, {"render": {"short:square": True}})
    (tmp_path / ".env").write_text("RENDER=short:vertical=true\n", encoding="utf-8")
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
            "RENDER": "primary short:square=true",
            "PRIMARY": "auto long=square",
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
@pytest.mark.parametrize("scope", ["short:vertical", "all:vertical"])
def test_named_render_rejects_primary_value(source, scope, tmp_path, monkeypatch):
    flags = []
    if source == "cli":
        flags = ["--render", f"{scope}=primary"]
    elif source == "json":
        flags = [
            "--config",
            preset(tmp_path, {"render": {scope: "primary"}}),
        ]
    elif source == "process":
        monkeypatch.setenv("RENDER", f"{scope}=primary")
    else:
        (tmp_path / ".env").write_text(f"RENDER={scope}=primary\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        parse(*flags)


@pytest.mark.parametrize("value", [0, 1, None, [], {}, "true", "false", "all"])
def test_render_preset_values_are_strict(value, tmp_path):
    with pytest.raises(ConfigurationError):
        parse("--config", preset(tmp_path, {"render": {"all": value}}))


def test_removed_variants_preset_group_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="accepts only"):
        parse("--config", preset(tmp_path, {"variants": {}}))


@pytest.mark.parametrize("attached", [False, True])
def test_primary_and_render_accept_multiple_values_per_occurrence(attached):
    primary = (
        ["--primary=short=horizontal-blur"]
        if attached
        else ["--primary", "short=horizontal-blur"]
    )
    render = ["--render=long=false"] if attached else ["--render", "long=false"]
    config = parse(*primary, "long=vertical-blur", *render, "short:vertical=false")
    assert config.short_primary == "horizontal-blur"
    assert config.long_primary == "vertical-blur"
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media)[0] == "horizontal-blur"
    assert "vertical" not in config.outputs_for("short", media)
    assert not config.clips_for("long")


@pytest.mark.parametrize("reverse", [False, True])
def test_grouped_values_preserve_scope_priority_and_allow_repeated_flags(reverse):
    sizes = ["4%", "short=5%", "short:vertical=6%"]
    render = ["primary", "long=false", "short:square=true"]
    if reverse:
        sizes.reverse()
        render.reverse()
    config = parse(
        "--subtitle-font-size",
        *sizes,
        "--render",
        *render,
        "--subtitle-font-size",
        "short:horizontal=7%",
    )
    assert config.for_output("long", "horizontal").subtitle_options.font_size == "4%"
    assert config.for_output("short", "square").subtitle_options.font_size == "5%"
    assert config.for_output("short", "vertical").subtitle_options.font_size == "6%"
    assert config.for_output("short", "horizontal").subtitle_options.font_size == "7%"
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media) == ("horizontal", "square")
    assert config.outputs_for("long", media) == ()


def test_grouped_dimensions_and_subtitle_controls_keep_quoted_values_intact(tmp_path):
    import shlex

    short_dir = tmp_path / "Short templates"
    long_dir = tmp_path / "Long templates"
    short_dir.mkdir()
    long_dir.mkdir()
    config = parse(
        "--width",
        "short:horizontal=2520",
        "long:horizontal=1920",
        "--height",
        "short:horizontal=1080",
        "long:horizontal=1080",
        "--subtitles",
        "short=false",
        "long=true",
        "--subtitle-template",
        "short=yellow-pop",
        "long=amber-word",
        "--subtitle-template-dir",
        f"short={short_dir}",
        f"long={long_dir}",
        *shlex.split('--subtitle-font short="Open Sans" long="Montserrat"'),
    )
    assert config.dimensions_for("short", "horizontal") == (2520, 1080)
    assert config.dimensions_for("long", "horizontal") == (1920, 1080)
    short = config.for_output("short", "horizontal")
    long = config.for_output("long", "horizontal")
    assert not short.subtitles_for("short") and long.subtitles_for("long")
    assert short.subtitle_template == "yellow-pop"
    assert long.subtitle_template == "amber-word"
    assert short.subtitle_template_dir == short_dir
    assert long.subtitle_template_dir == long_dir
    assert short.subtitle_options.font == "Open Sans"
    assert long.subtitle_options.font == "Montserrat"


@pytest.mark.parametrize(
    "flags",
    [
        ["--render", "short=true", "short=false"],
        ["--render", "primary", "--render", "primary", "false"],
        ["--subtitle-font-size", "short=4%", "short=5%"],
        ["--subtitles", "short=true", "short=false"],
    ],
)
def test_grouped_contradictory_assignments_are_rejected(flags):
    with pytest.raises(ConfigurationError, match="Conflicting"):
        parse(*flags)


def test_grouped_identical_assignments_are_allowed():
    config = parse("--render", "primary", "short=true", "short=true")
    assert config.render_for("short") is True
    assert config.render_for("long") == "primary"


@pytest.mark.parametrize(
    "flags",
    [
        ["--render", "true", "short:vertical=primary"],
        ["--render", "true", "unknown=false"],
        ["--primary", "auto", "short:vertical=vertical"],
        ["--width", "short=720", "long=721"],
        ["--subtitle-font-size", "4%", "short="],
    ],
)
def test_invalid_grouped_values_fail_before_the_pipeline(flags):
    assert (
        main(
            ["source.mp4", "--output-dir", "out", "--clip-full", *flags],
            pipeline=lambda _: pytest.fail("Pipeline must not run"),
        )
        == 2
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["source.mp4", "--render", "primary", "short:square=true"],
        ["--render", "primary", "short:square=true", "source.mp4"],
        ["--render=primary", "short:square=true", "--", "source.mp4"],
    ],
)
def test_grouped_options_preserve_source_position_and_end_of_options(arguments):
    config = parse_run_config(["--output-dir", "out", "--clip-full", *arguments])
    assert config.source == "source.mp4"
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media) == ("horizontal", "square")


def test_grouped_options_preserve_flag_like_sources_after_end_of_options():
    config = parse_run_config(
        [
            "--output-dir",
            "out",
            "--clip-full",
            "--render",
            "primary",
            "short=true",
            "--",
            "--source=video.mp4",
        ]
    )
    assert config.source == "--source=video.mp4"


def test_grouping_respects_fixed_option_arity_and_literal_text_values():
    config = parse_run_config(
        [
            "--output-dir=out",
            "--search-range",
            "0",
            "180",
            "--context",
            "short=literal long=text",
            "--llm-backend",
            "codex",
            "--llm-model",
            "--render",
            "--render",
            "primary",
            "short:square=true",
            "source.mp4",
        ]
    )
    assert config.source == "source.mp4"
    assert config.search_range is not None
    assert (config.search_range.start, config.search_range.end) == (0, 180)
    assert config.editorial_context == "short=literal long=text"
    assert config.llm_model == "--render"
    assert config.render_for("long") == "primary"


def test_grouped_negative_subtitle_lengths_and_equals_inside_values():
    config = parse(
        "--subtitle-letter-spacing",
        "-1px",
        "short=-2px",
        "--subtitle-font",
        "short=Font=Name",
        "long=Other Font",
    )
    assert config.subtitle_options.letter_spacing == "-1px"
    short = config.for_output("short", "vertical").subtitle_options
    assert short.letter_spacing == "-2px"
    assert short.font == "Font=Name"
    assert config.for_output("long", "horizontal").subtitle_options.font == "Other Font"


def test_grouped_cli_values_override_more_specific_environment_values(monkeypatch):
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "short:vertical=9%")
    monkeypatch.setenv("RENDER", "short:square=true")
    config = parse(
        "--subtitle-font-size",
        "short=5%",
        "long=4%",
        "--render",
        "short=primary",
        "long=false",
    )
    assert config.for_output("short", "vertical").subtitle_options.font_size == "5%"
    assert config.for_output("long", "horizontal").subtitle_options.font_size == "4%"
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert config.outputs_for("short", media) == ("horizontal",)


@pytest.mark.parametrize("flag", ["--render", "--width", "--subtitle-font-size"])
def test_original_is_not_an_output_scope(flag):
    with pytest.raises(ConfigurationError, match="scope"):
        parse(flag, "short:original=true")


def test_preset_rejects_removed_aspect_ratio_group(tmp_path):
    with pytest.raises(ConfigurationError, match="accepts only"):
        parse("--config", preset(tmp_path, {"aspect_ratio": {"short": "original"}}))


@pytest.mark.parametrize("source", ["process", "dotenv"])
@pytest.mark.parametrize("reverse", [False, True])
def test_grouped_environment_options_match_cli_config(
    source, reverse, tmp_path, monkeypatch
):
    values = {
        "primary": ["auto", "short=horizontal-blur", "long=vertical-blur"],
        "render": ["primary", "long=false", "short:square=true"],
        "width": ["short:horizontal-blur=2520", "short:square=720"],
        "height": ["short:horizontal-blur=1080", "short:square=720"],
        "subtitles": ["false", "short:square=true"],
        "subtitle_font_size": ["4%", "short=5%", "short:square=6%"],
        "subtitle_text_color": ["#FFEE00", "short:square=#AABBCC"],
    }
    if reverse:
        values = {field: list(reversed(items)) for field, items in values.items()}
    flags = [
        part
        for field, items in values.items()
        for part in ("--" + field.replace("_", "-"), *items)
    ]
    expected = parse(*flags)
    if source == "process":
        for field, items in values.items():
            monkeypatch.setenv(field.upper(), " ".join(items))
    else:
        (tmp_path / ".env").write_text(
            "\n".join(
                f"{field.upper()}='{' '.join(items)}'"
                for field, items in values.items()
            ),
            encoding="utf-8",
        )
    actual = parse()
    assert actual == expected
    media = MediaInfo(60, 640, 360, 640, 360, 0, None)
    assert actual.outputs_for("short", media) == ("horizontal-blur", "square")
    assert actual.outputs_for("long", media) == ()


@pytest.mark.parametrize("source", ["process", "dotenv"])
def test_grouped_environment_preserves_spaces_and_literal_characters(
    source, tmp_path, monkeypatch
):
    directory = tmp_path / "Subtitle templates"
    directory.mkdir()
    literal_font = "Font $(literal) `text` ${NAME} #tag"
    values = {
        "SUBTITLE_FONT": f'short="Open Sans" long="{literal_font}"',
        "SUBTITLE_TEMPLATE": "short=yellow-pop long=amber-word",
        "SUBTITLE_TEMPLATE_DIR": f'short="{directory}"',
        "SUBTITLE_FONTS_DIR": 'short="~/My Fonts"',
    }
    if source == "process":
        for field, value in values.items():
            monkeypatch.setenv(field, value)
    else:
        (tmp_path / ".env").write_text(
            "\n".join(f"{field}='{value}'" for field, value in values.items()),
            encoding="utf-8",
        )
    config = parse()
    short = config.for_output("short", "vertical")
    long = config.for_output("long", "horizontal")
    assert short.subtitle_options.font == "Open Sans"
    assert long.subtitle_options.font == literal_font
    assert short.subtitle_template == "yellow-pop"
    assert long.subtitle_template == "amber-word"
    assert short.subtitle_template_dir == directory
    assert short.subtitle_options.fonts_dir == Path("~/My Fonts").expanduser()


def test_grouped_environment_inherits_missing_scopes_from_lower_priority_sources(
    tmp_path, monkeypatch
):
    path = preset(
        tmp_path,
        {
            "subtitles": {
                "all": {"font_size": "7%", "text_color": "#AABBCC"},
                "long:vertical": {"font_size": "8%"},
            }
        },
    )
    (tmp_path / ".env").write_text(
        'SUBTITLE_FONT_SIZE="short=5% long=4% long:horizontal=3%"\n', encoding="utf-8"
    )
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "short:vertical=6%")
    config = parse("--config", path, "--subtitle-font-size", "short:horizontal=9%")
    assert config.subtitle_options.font_size == "7%"
    for kind, variant, expected in [
        ("short", "square", "5%"),
        ("short", "vertical", "6%"),
        ("short", "horizontal", "9%"),
        ("long", "horizontal", "3%"),
        ("long", "vertical", "4%"),
    ]:
        options = config.for_output(kind, variant).subtitle_options
        assert options.font_size == expected
        assert options.text_color == "#AABBCC"
    monkeypatch.setenv("SUBTITLE_FONT_SIZE", "4%")
    config = parse("--config", path)
    for kind in ("short", "long"):
        assert config.for_output(kind, "vertical").subtitle_options.font_size == "4%"


@pytest.mark.parametrize("source", ["process", "dotenv"])
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RENDER", "true short=true short=false"),
        ("SUBTITLES", "short=true short=false"),
        ("SUBTITLE_FONT_SIZE", "short=4% short=5%"),
        ("PRIMARY", "short=auto short=vertical"),
        ("WIDTH", "short=720 short=640"),
        ("HEIGHT", "short=720 short=640"),
    ],
)
def test_environment_rejects_conflicting_values_for_one_scope(
    source, name, value, tmp_path, monkeypatch
):
    if source == "process":
        monkeypatch.setenv(name, value)
    else:
        (tmp_path / ".env").write_text(f"{name}='{value}'\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match=f"Conflicting values for {name}"):
        parse()


@pytest.mark.parametrize("source", ["process", "dotenv"])
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RENDER", 'short="true'),
        ("SUBTITLE_FONT", 'short="Open Sans'),
        ("RENDER", "unknown=false"),
        ("RENDER", "primary short:vertical=primary"),
        ("PRIMARY", "short:vertical=vertical"),
        ("SUBTITLE_FONT_SIZE", 'short=""'),
        ("WIDTH", "short=721"),
    ],
)
def test_invalid_grouped_environment_stops_before_pipeline(
    source, name, value, tmp_path, monkeypatch
):
    if source == "process":
        monkeypatch.setenv(name, value)
    else:
        (tmp_path / ".env").write_text(f"{name}='{value}'\n", encoding="utf-8")
    assert (
        main(
            ["source.mp4", "--output-dir", "out", "--clip-full"],
            pipeline=lambda _: pytest.fail("Pipeline must not run"),
        )
        == 2
    )


@pytest.mark.parametrize("empty", ["", " ", "\t"])
def test_empty_environment_values_inherit_from_dotenv(empty, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('RENDER="primary long=false"\n', encoding="utf-8")
    monkeypatch.setenv("RENDER", empty)
    config = parse()
    assert config.render_for("short") == "primary"
    assert not config.clips_for("long")


def test_dotenv_accepts_export_quotes_and_ignores_unrelated_settings(tmp_path):
    (tmp_path / ".env").write_text(
        '# RENDER=false\nexport RENDER = "primary long=false"\n'
        "PRIMARY='short=vertical long=auto'\n"
        'UNRELATED="not output settings\n',
        encoding="utf-8",
    )
    config = parse()
    assert config.render_for("short") == "primary"
    assert not config.clips_for("long")
    assert config.short_primary == "vertical"


def test_dotenv_rejects_duplicate_output_variables(tmp_path):
    (tmp_path / ".env").write_text(
        "RENDER=primary\nRENDER=long=false\n", encoding="utf-8"
    )
    with pytest.raises(ConfigurationError, match="Duplicate output variable"):
        parse()


@pytest.mark.parametrize("source", ["process", "dotenv"])
@pytest.mark.parametrize(
    "name",
    [
        "PRIMARY_SHORT",
        "PRIMARY_LONG",
        "RENDER_SHORT",
        "RENDER_SHORT_VERTICAL",
        "WIDTH_SHORT_VERTICAL",
        "HEIGHT_LONG_HORIZONTAL",
        "SUBTITLE_SHORT_ENABLED",
        "SUBTITLE_LONG_VERTICAL_ENABLED",
        "SUBTITLE_SHORT_FONT_SIZE",
        "SUBTITLE_SHORT_VERTICAL_FONT_SIZE",
        "SUBTITLE_LONG_HORIZONTAL_TEMPLATE",
        "SUBTITLE_SHORT_VERTICAL_TEMPLATE_DIR",
    ],
)
def test_generated_environment_names_are_removed(source, name, tmp_path, monkeypatch):
    if source == "process":
        monkeypatch.setenv(name, "obsolete-value")
    else:
        (tmp_path / ".env").write_text(f"{name}=obsolete-value\n", encoding="utf-8")
    config = parse()
    assert config.short_primary == config.long_primary == "auto"
    assert config.render_for("short") is True
    assert config.for_output("short", "vertical").subtitle_options.font_size is None


@pytest.mark.parametrize("failure", ["encoding", "directory"])
def test_unreadable_dotenv_stops_before_pipeline(failure, tmp_path):
    path = tmp_path / ".env"
    if failure == "encoding":
        path.write_bytes(b"RENDER=\xff")
    else:
        path.mkdir()
    assert (
        main(
            ["source.mp4", "--output-dir", "out", "--clip-full"],
            pipeline=lambda _: pytest.fail("Pipeline must not run"),
        )
        == 2
    )


def test_dotenv_decodes_escaped_quotes_around_grouped_text_values(tmp_path):
    (tmp_path / ".env").write_text(
        'SUBTITLE_FONT="short=\\"Open Sans\\" long=\\"Montserrat\\""\n',
        encoding="utf-8",
    )
    config = parse()
    assert config.for_output("short", "vertical").subtitle_options.font == "Open Sans"
    assert config.for_output("long", "horizontal").subtitle_options.font == "Montserrat"

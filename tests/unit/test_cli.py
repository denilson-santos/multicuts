from pathlib import Path

import pytest

from multicuts.cli import build_parser, main, parse_run_config
from multicuts.config import RunConfig
from multicuts.errors import ConfigurationError
from multicuts.pipeline import PipelineNotReadyError


def test_generate_defaults_are_converted_to_run_config() -> None:
    config = parse_run_config(["generate", "missing-video.mp4"])

    assert config.source == "missing-video.mp4"
    assert config.output_dir == Path("multicuts-output")
    assert config.language is None
    assert config.clips == 5
    assert config.min_score == 0
    assert config.min_duration == 15.0
    assert config.max_duration == 60.0
    assert config.aspect_ratio == "original"
    assert config.subtitle_template == "yellow-pop"
    assert config.scorer == "heuristic"
    assert config.model == "default"


def test_generate_maps_explicit_options_without_accessing_source(
    tmp_path: Path,
) -> None:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    config = parse_run_config(
        [
            "generate",
            "https://example.test/video",
            "--output-dir",
            "~/runs",
            "--lang",
            "pt-BR",
            "--clips",
            "8",
            "--min-score",
            "65",
            "--min-duration",
            "20",
            "--max-duration",
            "45",
            "--aspect-ratio",
            "9:16",
            "--subtitle-template",
            "yellow-pop",
            "--subtitle-template-dir",
            str(template_dir),
            "--scorer",
            "hybrid",
            "--model",
            "large-v3",
            "--keep-intermediates",
            "--force-recompute",
            "--verbose",
        ]
    )

    assert config.source == "https://example.test/video"
    assert config.output_dir == Path("~/runs").expanduser()
    assert config.language == "pt-BR"
    assert (config.clips, config.min_score) == (8, 65)
    assert (config.min_duration, config.max_duration) == (20.0, 45.0)
    assert config.aspect_ratio == "9:16"
    assert config.subtitle_template == "yellow-pop"
    assert config.subtitle_template_dir == template_dir
    assert config.scorer == "hybrid"
    assert config.model == "large-v3"
    assert config.keep_intermediates
    assert config.force_recompute
    assert config.verbose


def test_auto_language_is_normalized_by_run_config() -> None:
    assert (
        parse_run_config(["generate", "source.mp4", "--lang", "auto"]).language is None
    )


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--clips", "0", "clips"),
        ("--min-score", "101", "min_score"),
        ("--aspect-ratio", "square", "aspect_ratio"),
    ],
)
def test_semantic_cli_errors_reach_run_config_validation(
    option: str, value: str, message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        parse_run_config(["generate", "source.mp4", option, value])


def test_custom_template_directory_is_validated_by_run_config(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="subtitle_template_dir"):
        parse_run_config(
            [
                "generate",
                "source.mp4",
                "--subtitle-template-dir",
                str(tmp_path / "missing-templates"),
            ]
        )


def test_help_exposes_the_documented_options_and_score_semantics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["generate", "--help"])

    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    for option in (
        "--output-dir",
        "--lang",
        "--clips",
        "--min-score",
        "--min-duration",
        "--max-duration",
        "--aspect-ratio",
        "--subtitle-template",
        "--subtitle-template-dir",
        "--scorer",
        "--model",
        "--keep-intermediates",
        "--force-recompute",
        "--verbose",
    ):
        assert option in help_text
    assert "ranking heuristic, not a probability" in help_text


def test_main_passes_one_validated_config_to_pipeline() -> None:
    received: list[RunConfig] = []

    def fake_pipeline(config: RunConfig) -> None:
        received.append(config)

    exit_code = main(["generate", "source.mp4", "--clips", "2"], pipeline=fake_pipeline)

    assert exit_code == 0
    assert len(received) == 1
    assert received[0].clips == 2


def test_main_uses_the_default_pipeline_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[RunConfig] = []

    def fake_pipeline(config: RunConfig) -> None:
        called.append(config)

    monkeypatch.setattr("multicuts.cli.run_pipeline", fake_pipeline)

    assert main(["generate", "source.mp4"]) == 0
    assert called[0].source == "source.mp4"


def test_main_surfaces_incomplete_default_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def incomplete_pipeline(_config: RunConfig) -> None:
        raise PipelineNotReadyError("pipeline incomplete")

    monkeypatch.setattr("multicuts.cli.run_pipeline", incomplete_pipeline)

    with pytest.raises(PipelineNotReadyError, match="pipeline incomplete"):
        main(["generate", "source.mp4"])

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from multicuts.cli import app, main, parse_run_config
from multicuts.config import RunConfig
from multicuts.errors import (
    AcquisitionError,
    ArtifactError,
    ConfigurationError,
    MediaError,
    RenderingError,
    ScoringError,
    TranscriptionError,
)
from multicuts.pipeline import PipelineNotReadyError


def test_generate_defaults_are_converted_to_run_config() -> None:
    config = parse_run_config(["missing-video.mp4"])

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
    assert parse_run_config(["source.mp4", "--lang", "auto"]).language is None


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
        parse_run_config(["source.mp4", option, value])


def test_custom_template_directory_is_validated_by_run_config(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="subtitle_template_dir"):
        parse_run_config(
            [
                "source.mp4",
                "--subtitle-template-dir",
                str(tmp_path / "missing-templates"),
            ]
        )


def test_help_exposes_the_documented_options_and_score_semantics() -> None:
    result = CliRunner().invoke(app, ["--help"], prog_name="multicuts")

    assert result.exit_code == 0
    help_text = result.stdout
    assert "Usage: multicuts" in help_text
    assert "SOURCE" in help_text
    assert "{generate}" not in help_text
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
    assert "ranking heuristic, not a probability" in " ".join(help_text.split())


def test_removed_generate_subcommand_is_rejected() -> None:
    result = CliRunner().invoke(app, ["generate", "source.mp4"])

    assert result.exit_code == 2


def test_main_passes_one_validated_config_to_pipeline() -> None:
    received: list[RunConfig] = []

    def fake_pipeline(config: RunConfig) -> None:
        received.append(config)

    exit_code = main(["source.mp4", "--clips", "2"], pipeline=fake_pipeline)

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

    assert main(["source.mp4"]) == 0
    assert called[0].source == "source.mp4"


def test_main_maps_incomplete_pipeline_to_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def incomplete_pipeline(_config: RunConfig) -> None:
        raise PipelineNotReadyError("pipeline incomplete")

    monkeypatch.setattr("multicuts.cli.run_pipeline", incomplete_pipeline)

    assert main(["source.mp4"]) == 1
    output = capsys.readouterr().err
    assert "Unexpected failure; no diagnostic details are available" in output
    assert "pipeline incomplete" not in output
    assert "Traceback" not in output


@pytest.mark.parametrize(
    ("error", "expected_exit", "label"),
    [
        (ConfigurationError("clips must be positive"), 2, "Invalid configuration"),
        (AcquisitionError("source is unavailable"), 3, "Acquisition failed"),
        (MediaError("source has no audio"), 3, "Media preflight failed"),
        (TranscriptionError("provider failed"), 4, "Transcription failed"),
        (ScoringError("scorer failed"), 5, "Scoring failed"),
        (RenderingError("FFmpeg failed"), 6, "Rendering failed"),
        (
            ArtifactError("manifest could not be written"),
            6,
            "Artifact publication failed",
        ),
    ],
)
def test_main_maps_project_errors_to_documented_exit_codes(
    error: Exception,
    expected_exit: int,
    label: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing_pipeline(_config: RunConfig) -> None:
        raise error

    assert main(["source.mp4"], pipeline=failing_pipeline) == expected_exit
    output = capsys.readouterr().err
    assert f"{label}: {error}" in output
    assert "Traceback" not in output


def test_main_reports_semantic_configuration_errors_without_running_pipeline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def failing_pipeline(_config: RunConfig) -> None:
        nonlocal called
        called = True

    assert (
        main(
            ["source.mp4", "--clips", "0"],
            pipeline=failing_pipeline,
        )
        == 2
    )
    assert not called
    assert "Invalid configuration: clips" in capsys.readouterr().err


def test_main_maps_typer_parse_errors_to_configuration_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["source.mp4", "--clips", "not-an-integer"]) == 2
    assert "Invalid value for '--clips'" in capsys.readouterr().err


def test_main_verbose_diagnostics_include_safe_failure_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing_pipeline(_config: RunConfig) -> None:
        raise AcquisitionError("download failed token=super-secret") from RuntimeError(
            "provider token=super-secret"
        )

    assert (
        main(
            ["https://example.test/video?token=super-secret", "--verbose"],
            pipeline=failing_pipeline,
        )
        == 3
    )
    output = capsys.readouterr().err
    assert "stage=acquire" in output
    assert "error_type=AcquisitionError" in output
    assert "super-secret" not in output
    assert "Traceback" not in output


def test_main_unexpected_failure_uses_only_generic_and_typed_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing_pipeline(_config: RunConfig) -> None:
        raise RuntimeError("provider response token=super-secret") from ValueError(
            "raw provider payload"
        )

    assert (
        main(
            ["source.mp4", "--verbose"],
            pipeline=failing_pipeline,
        )
        == 1
    )
    output = capsys.readouterr().err
    assert "Unexpected failure; no diagnostic details are available" in output
    assert "stage=run error_type=RuntimeError cause_type=ValueError" in output
    assert "provider response" not in output
    assert "raw provider payload" not in output
    assert "super-secret" not in output


def test_main_returns_clean_interruption_exit_without_success_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupt_pipeline(_config: RunConfig) -> None:
        raise KeyboardInterrupt

    assert main(["source.mp4"], pipeline=interrupt_pipeline) == 130
    output = capsys.readouterr().err
    assert "Run interrupted" in output
    assert "completion summary" in output


def test_pipeline_logging_configuration_sets_debug_level_for_verbose() -> None:
    from multicuts.cli import configure_logging

    root_logger = logging.getLogger()
    project_logger = logging.getLogger("multicuts")
    root_level = root_logger.level
    configure_logging(verbose=True)
    assert project_logger.level == logging.DEBUG
    assert root_logger.level == root_level
    configure_logging(verbose=False)
    assert project_logger.level == logging.WARNING
    assert root_logger.level == root_level

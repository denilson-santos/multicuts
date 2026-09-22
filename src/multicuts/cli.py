"""Typer command-line parsing and process-boundary handling for one run."""

import logging
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from multicuts.config import RunConfig
from multicuts.errors import (
    AcquisitionError,
    ArtifactError,
    ConfigurationError,
    MediaError,
    MulticutsError,
    RenderingError,
    ScoringError,
    TranscriptionError,
)
from multicuts.pipeline import run_pipeline

DEFAULT_OUTPUT_DIR = Path("multicuts-output")
DEFAULT_CLIPS = 5
DEFAULT_MIN_SCORE = 0
DEFAULT_CANDIDATE_BUDGET = 50
DEFAULT_OVERLAP_THRESHOLD = 0.60
DEFAULT_TEXT_SIMILARITY_THRESHOLD = 0.90
DEFAULT_ASPECT_RATIO = "original"
DEFAULT_SUBTITLE_TEMPLATE = "yellow-pop"
DEFAULT_SCORER = "heuristic"
DEFAULT_MODEL = "default"


PipelineRunner = Callable[[RunConfig], None]


@dataclass
class _CliContext:
    """State shared between Typer's command callback and the process boundary."""

    parsed_config: RunConfig | None = None


EXIT_SUCCESS = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIGURATION = 2
EXIT_ACQUISITION = 3
EXIT_TRANSCRIPTION = 4
EXIT_SCORING = 5
EXIT_RENDERING = 6

logger = logging.getLogger(__name__)
_CLI_HANDLER_MARKER = "_multicuts_cli_handler"
_MAX_SAFE_ERROR_LENGTH = 500
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(\b(?:access[_ -]?token|api[_ -]?key|authorization|cookie|password|"
    r"secret|token)\b\s*(?:[:=]\s*(?:bearer\s+)?|bearer\s+))[^\s,;]+"
)
_URL_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:access[_-]?token|api[_-]?key|signature|token|key)=)[^&#\s]+"
)

_ERROR_DETAILS: tuple[tuple[type[MulticutsError], int, str, str], ...] = (
    (ConfigurationError, EXIT_CONFIGURATION, "configuration", "Invalid configuration"),
    (AcquisitionError, EXIT_ACQUISITION, "acquire", "Acquisition failed"),
    # Media preflight is part of validating the acquired input.
    (MediaError, EXIT_ACQUISITION, "probe", "Media preflight failed"),
    (TranscriptionError, EXIT_TRANSCRIPTION, "transcribe", "Transcription failed"),
    (ScoringError, EXIT_SCORING, "score", "Scoring failed"),
    (RenderingError, EXIT_RENDERING, "render", "Rendering failed"),
    # Artifact publication is an output-stage failure and shares rendering's exit.
    (ArtifactError, EXIT_RENDERING, "publish", "Artifact publication failed"),
)


def configure_logging(verbose: bool) -> None:
    """Configure standard logging for one CLI invocation.

    The handler is attached only to the project logger hierarchy. This keeps
    verbose provider logging disabled while still allowing repeated in-process
    invocations to follow the current ``sys.stderr``.
    """
    project_logger = logging.getLogger("multicuts")
    project_logger.setLevel(logging.DEBUG if verbose else logging.WARNING)

    handler: logging.StreamHandler | None = next(
        (
            candidate
            for candidate in project_logger.handlers
            if isinstance(candidate, logging.StreamHandler)
            and getattr(candidate, _CLI_HANDLER_MARKER, False)
        ),
        None,
    )
    if handler is not None:
        project_logger.removeHandler(handler)
        handler.close()

    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _CLI_HANDLER_MARKER, True)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    project_logger.addHandler(handler)


def _safe_text(value: object) -> str:
    """Bound and redact text before it reaches user-facing diagnostics."""
    message = " ".join(str(value).split())
    if not message:
        message = "no further details available"
    message = _SECRET_VALUE_PATTERN.sub(r"\1[REDACTED]", message)
    message = _URL_SECRET_PATTERN.sub(r"\1[REDACTED]", message)
    if len(message) > _MAX_SAFE_ERROR_LENGTH:
        message = message[:_MAX_SAFE_ERROR_LENGTH].rstrip() + "..."
    return message


def _error_details(error: MulticutsError) -> tuple[int, str, str]:
    """Return the exit code, stage, and user-facing label for an expected error."""
    for error_type, exit_code, stage, label in _ERROR_DETAILS:
        if isinstance(error, error_type):
            return exit_code, stage, label
    return EXIT_UNEXPECTED, "unknown", "Unexpected project failure"


def _log_project_error(error: MulticutsError, *, verbose: bool) -> int:
    """Log a safe project error and return its documented process exit code."""
    exit_code, stage, label = _error_details(error)
    logger.error("%s: %s", label, _safe_text(error))
    if verbose:
        cause_type = type(error.__cause__).__name__ if error.__cause__ else "none"
        logger.debug(
            "stage=%s error_type=%s cause_type=%s exit_code=%d",
            stage,
            type(error).__name__,
            cause_type,
            exit_code,
        )
    return exit_code


def _log_unexpected_error(error: BaseException, *, stage: str, verbose: bool) -> int:
    """Log an unexpected failure without exposing its raw message or cause."""
    logger.error("Unexpected failure; no diagnostic details are available")
    if verbose:
        cause_type = type(error.__cause__).__name__ if error.__cause__ else "none"
        logger.debug(
            "stage=%s error_type=%s cause_type=%s exit_code=%d",
            stage,
            type(error).__name__,
            cause_type,
            EXIT_UNEXPECTED,
        )
    return EXIT_UNEXPECTED


app = typer.Typer(
    name="multicuts",
    help=(
        "Generate ranked short clips from SOURCE. The viral-potential score is "
        "an explainable ranking heuristic, not a probability."
    ),
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=False,
)


def _build_run_config(
    *,
    source: str,
    output_dir: Path,
    language: str,
    clips: int,
    min_score: int,
    min_duration: float,
    max_duration: float,
    candidate_budget: int,
    overlap_threshold: float,
    text_similarity_threshold: float,
    aspect_ratio: str,
    subtitle_template: str,
    subtitle_template_dir: Path | None,
    scorer: str,
    model: str,
    keep_intermediates: bool,
    force_recompute: bool,
    verbose: bool,
) -> RunConfig:
    """Convert Typer values into one validated project-owned configuration."""
    return RunConfig(
        source=source,
        output_dir=output_dir.expanduser(),
        clips=clips,
        min_score=min_score,
        aspect_ratio=aspect_ratio,
        subtitle_template=subtitle_template,
        scorer=scorer,
        model=model,
        language=language,
        min_duration=min_duration,
        max_duration=max_duration,
        candidate_budget=candidate_budget,
        overlap_threshold=overlap_threshold,
        text_similarity_threshold=text_similarity_threshold,
        subtitle_template_dir=(
            subtitle_template_dir.expanduser()
            if subtitle_template_dir is not None
            else None
        ),
        keep_intermediates=keep_intermediates,
        force_recompute=force_recompute,
        verbose=verbose,
    )


@app.command()
def run_command(
    ctx: typer.Context,
    source: Annotated[
        str,
        typer.Argument(
            ...,
            metavar="SOURCE",
            help="Local video path or supported source URL.",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            metavar="PATH",
            help="Directory for run artifacts and final clips.",
        ),
    ] = DEFAULT_OUTPUT_DIR,
    language: Annotated[
        str,
        typer.Option(
            "--lang",
            metavar="CODE|auto",
            help="Requested source language, or auto for provider detection.",
        ),
    ] = "auto",
    clips: Annotated[
        int,
        typer.Option(
            "--clips",
            metavar="INTEGER",
            help="Maximum number of selected clips.",
        ),
    ] = DEFAULT_CLIPS,
    min_score: Annotated[
        int,
        typer.Option(
            "--min-score",
            metavar="INTEGER",
            help="Minimum ranking score from 0 to 100.",
        ),
    ] = DEFAULT_MIN_SCORE,
    min_duration: Annotated[
        float,
        typer.Option(
            "--min-duration",
            metavar="SECONDS",
            help="Minimum candidate duration in seconds.",
        ),
    ] = 15.0,
    max_duration: Annotated[
        float,
        typer.Option(
            "--max-duration",
            metavar="SECONDS",
            help="Maximum candidate duration in seconds.",
        ),
    ] = 60.0,
    candidate_budget: Annotated[
        int,
        typer.Option(
            "--candidate-budget",
            metavar="INTEGER",
            help="Maximum candidates sent to downstream scoring.",
        ),
    ] = DEFAULT_CANDIDATE_BUDGET,
    overlap_threshold: Annotated[
        float,
        typer.Option(
            "--overlap-threshold",
            metavar="RATIO",
            help="Inclusive temporal-overlap suppression threshold from 0 to 1.",
        ),
    ] = DEFAULT_OVERLAP_THRESHOLD,
    text_similarity_threshold: Annotated[
        float,
        typer.Option(
            "--text-threshold",
            metavar="RATIO",
            help="Inclusive normalized-text redundancy threshold from 0 to 1.",
        ),
    ] = DEFAULT_TEXT_SIMILARITY_THRESHOLD,
    aspect_ratio: Annotated[
        str,
        typer.Option(
            "--aspect-ratio",
            metavar="original|9:16",
            help="Output presentation geometry.",
        ),
    ] = DEFAULT_ASPECT_RATIO,
    subtitle_template: Annotated[
        str,
        typer.Option(
            "--subtitle-template",
            metavar="NAME",
            help="Built-in or custom multisubs template name.",
        ),
    ] = DEFAULT_SUBTITLE_TEMPLATE,
    subtitle_template_dir: Annotated[
        Path | None,
        typer.Option(
            "--subtitle-template-dir",
            metavar="PATH",
            help="Directory containing custom subtitle templates.",
        ),
    ] = None,
    scorer: Annotated[
        str,
        typer.Option("--scorer", metavar="NAME", help="Scoring strategy name."),
    ] = DEFAULT_SCORER,
    model: Annotated[
        str,
        typer.Option("--model", metavar="NAME", help="Provider model name."),
    ] = DEFAULT_MODEL,
    keep_intermediates: Annotated[
        bool,
        typer.Option(
            "--keep-intermediates",
            help="Keep useful intermediate artifacts for diagnostics.",
        ),
    ] = False,
    force_recompute: Annotated[
        bool,
        typer.Option(
            "--force-recompute",
            help="Ignore reusable artifacts and recompute stages.",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Enable diagnostic output for the run."),
    ] = False,
) -> None:
    """Generate ranked short clips from SOURCE.

    The viral-potential score is an explainable ranking heuristic, not a
    probability.
    """
    config = _build_run_config(
        source=source,
        output_dir=output_dir,
        language=language,
        clips=clips,
        min_score=min_score,
        min_duration=min_duration,
        max_duration=max_duration,
        candidate_budget=candidate_budget,
        overlap_threshold=overlap_threshold,
        text_similarity_threshold=text_similarity_threshold,
        aspect_ratio=aspect_ratio,
        subtitle_template=subtitle_template,
        subtitle_template_dir=subtitle_template_dir,
        scorer=scorer,
        model=model,
        keep_intermediates=keep_intermediates,
        force_recompute=force_recompute,
        verbose=verbose,
    )
    state = ctx.obj if isinstance(ctx.obj, _CliContext) else _CliContext()
    state.parsed_config = config


def parse_run_config(argv: Sequence[str] | None = None) -> RunConfig:
    """Parse ``argv`` and validate it as one project-owned run configuration."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    state = _CliContext()
    try:
        app(
            args=arguments,
            prog_name="multicuts",
            obj=state,
            standalone_mode=True,
        )
    except SystemExit as error:
        if error.code not in (0, None):
            raise
    if state.parsed_config is None:
        raise RuntimeError("Typer did not produce a run configuration")
    return state.parsed_config


def main(
    argv: Sequence[str] | None = None,
    *,
    pipeline: PipelineRunner | None = None,
) -> int:
    """Run one command and translate process-boundary failures into exit codes."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    verbose = any(argument == "--verbose" for argument in arguments)
    configure_logging(verbose)

    stage = "validate"
    state = _CliContext()
    try:
        app(
            args=arguments,
            prog_name="multicuts",
            obj=state,
            standalone_mode=True,
        )
    except KeyboardInterrupt:
        logger.warning("Run interrupted; no completion summary was produced")
        return 130
    except SystemExit as error:
        if error.code not in (0, None):
            return int(error.code)
        if state.parsed_config is None:
            return EXIT_SUCCESS
    except MulticutsError as error:
        return _log_project_error(error, verbose=verbose)
    except Exception as error:
        return _log_unexpected_error(error, stage=stage, verbose=verbose)

    if state.parsed_config is None:
        return EXIT_SUCCESS
    logger.info("stage=validate complete")
    stage = "run"
    try:
        runner = run_pipeline if pipeline is None else pipeline
        runner(state.parsed_config)
    except KeyboardInterrupt:
        logger.warning("Run interrupted; no completion summary was produced")
        return 130
    except MulticutsError as error:
        return _log_project_error(error, verbose=verbose)
    except Exception as error:
        return _log_unexpected_error(error, stage=stage, verbose=verbose)
    return EXIT_SUCCESS

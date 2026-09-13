"""Command-line parsing and process-boundary handling for one run."""

import argparse
import logging
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

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
DEFAULT_ASPECT_RATIO = "original"
DEFAULT_SUBTITLE_TEMPLATE = "yellow-pop"
DEFAULT_SCORER = "heuristic"
DEFAULT_MODEL = "default"


PipelineRunner = Callable[[RunConfig], None]

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


def _path_argument(value: str) -> Path:
    """Convert a CLI path while preserving relative paths."""
    return Path(value).expanduser()


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


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the documented multicuts command surface."""
    parser = argparse.ArgumentParser(
        prog="multicuts",
        description=(
            "Generate ranked short clips from SOURCE. The viral-potential "
            "score is an explainable ranking heuristic, not a probability."
        ),
    )
    parser.add_argument(
        "source",
        metavar="SOURCE",
        help="Local video path or supported source URL.",
    )
    parser.add_argument(
        "--output-dir",
        type=_path_argument,
        default=DEFAULT_OUTPUT_DIR,
        metavar="PATH",
        help="Directory for run artifacts and final clips.",
    )
    parser.add_argument(
        "--lang",
        dest="language",
        default="auto",
        metavar="CODE|auto",
        help="Requested source language, or auto for provider detection.",
    )
    parser.add_argument(
        "--clips",
        type=int,
        default=DEFAULT_CLIPS,
        metavar="INTEGER",
        help="Maximum number of selected clips.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=DEFAULT_MIN_SCORE,
        metavar="INTEGER",
        help="Minimum ranking score from 0 to 100.",
    )
    parser.add_argument(
        "--min-duration",
        type=float,
        default=15.0,
        metavar="SECONDS",
        help="Minimum candidate duration in seconds.",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="Maximum candidate duration in seconds.",
    )
    parser.add_argument(
        "--aspect-ratio",
        default=DEFAULT_ASPECT_RATIO,
        metavar="original|9:16",
        help="Output presentation geometry.",
    )
    parser.add_argument(
        "--subtitle-template",
        default=DEFAULT_SUBTITLE_TEMPLATE,
        metavar="NAME",
        help="Built-in or custom multisubs template name.",
    )
    parser.add_argument(
        "--subtitle-template-dir",
        type=_path_argument,
        default=None,
        metavar="PATH",
        help="Directory containing custom subtitle templates.",
    )
    parser.add_argument(
        "--scorer",
        default=DEFAULT_SCORER,
        metavar="NAME",
        help="Scoring strategy name.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        metavar="NAME",
        help="Provider model name.",
    )
    parser.add_argument(
        "--keep-intermediates",
        action="store_true",
        help="Keep useful intermediate artifacts for diagnostics.",
    )
    parser.add_argument(
        "--force-recompute",
        action="store_true",
        help="Ignore reusable artifacts and recompute stages.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable diagnostic output for the run.",
    )
    return parser


def parse_run_config(argv: Sequence[str] | None = None) -> RunConfig:
    """Parse ``argv`` and validate it as one project-owned run configuration."""
    arguments = build_parser().parse_args(argv)
    return RunConfig(
        source=arguments.source,
        output_dir=arguments.output_dir,
        clips=arguments.clips,
        min_score=arguments.min_score,
        aspect_ratio=arguments.aspect_ratio,
        subtitle_template=arguments.subtitle_template,
        scorer=arguments.scorer,
        model=arguments.model,
        language=arguments.language,
        min_duration=arguments.min_duration,
        max_duration=arguments.max_duration,
        subtitle_template_dir=arguments.subtitle_template_dir,
        keep_intermediates=arguments.keep_intermediates,
        force_recompute=arguments.force_recompute,
        verbose=arguments.verbose,
    )


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
    try:
        config = parse_run_config(arguments)
        logger.info("stage=validate complete")
        stage = "run"
        runner = run_pipeline if pipeline is None else pipeline
        runner(config)
    except KeyboardInterrupt:
        logger.warning("Run interrupted; no completion summary was produced")
        return 130
    except MulticutsError as error:
        return _log_project_error(error, verbose=verbose)
    except Exception as error:
        return _log_unexpected_error(error, stage=stage, verbose=verbose)
    return EXIT_SUCCESS

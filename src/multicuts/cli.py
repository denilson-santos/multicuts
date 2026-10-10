"""Command line interface for one semantic multicuts run."""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from multicuts.adapters._llm_common import setting
from multicuts.app_config import AppConfig
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
from multicuts.pipeline import RunOutcome, RunResult, run_pipeline

PipelineRunner = Callable[[AppConfig], RunResult]
logger = logging.getLogger(__name__)


@dataclass
class _CliContext:
    parsed_config: AppConfig | None = None


EXIT_SUCCESS = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIGURATION = 2
EXIT_ACQUISITION = 3
EXIT_TRANSCRIPTION = 4
EXIT_SCORING = 5
EXIT_RENDERING = 6

_ERROR_DETAILS: tuple[tuple[type[MulticutsError], int, str], ...] = (
    (ConfigurationError, EXIT_CONFIGURATION, "Invalid configuration"),
    (AcquisitionError, EXIT_ACQUISITION, "Acquisition failed"),
    (MediaError, EXIT_ACQUISITION, "Media preflight failed"),
    (TranscriptionError, EXIT_TRANSCRIPTION, "Transcription failed"),
    (ScoringError, EXIT_SCORING, "AI analysis failed"),
    (RenderingError, EXIT_RENDERING, "Rendering failed"),
    (ArtifactError, EXIT_RENDERING, "Artifact publication failed"),
)
_SECRET = re.compile(
    r"(?i)(\b(?:access[_ -]?token|api[_ -]?key|authorization|cookie|password|"
    r"secret|token)\b\s*(?:[:=]\s*(?:bearer\s+)?|bearer\s+))[^\s,;]+"
)


class _CliHandler(logging.StreamHandler):
    """Marker for the handler owned by this CLI."""


class _ProjectLogs(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == "multicuts" or record.name.startswith("multicuts.")


def configure_logging(verbose: bool) -> None:
    project = logging.getLogger("multicuts")
    level = logging.DEBUG if verbose else logging.INFO
    project.setLevel(level)
    project.propagate = False
    for handler in list(project.handlers):
        if isinstance(handler, _CliHandler):
            project.removeHandler(handler)
            handler.close()
    handler = _CliHandler(sys.stderr)
    handler.setLevel(level)
    handler.addFilter(_ProjectLogs())
    label = "%(name)s" if verbose else "multicuts"
    handler.setFormatter(logging.Formatter(f"%(levelname)s [{label}]: %(message)s"))
    project.addHandler(handler)


@contextmanager
def _pipeline_output(verbose: bool) -> Iterator[None]:
    """Keep dependency output off the terminal during a normal synchronous run."""
    if verbose:
        yield
        return
    with ExitStack() as stack:
        sink = stack.enter_context(open(os.devnull, "w", encoding="utf-8"))
        project = logging.getLogger("multicuts")
        for handler in project.handlers:
            if not isinstance(handler, _CliHandler):
                continue
            try:
                descriptor = handler.stream.fileno()
            except (AttributeError, OSError, ValueError):
                continue
            if descriptor == 2:
                console = stack.enter_context(
                    os.fdopen(os.dup(2), "w", encoding="utf-8", errors="replace")
                )
                original = handler.setStream(console)
                stack.callback(handler.setStream, original)

        # Existing handlers can retain streams that Python redirection cannot reach.
        loggers = [logging.getLogger(), *logging.Logger.manager.loggerDict.values()]
        handlers = {
            handler
            for current in loggers
            if isinstance(current, logging.Logger)
            for handler in current.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        }
        if isinstance(logging.lastResort, logging.StreamHandler):
            handlers.add(logging.lastResort)
        project_filter = _ProjectLogs()
        for handler in handlers:
            handler.addFilter(project_filter)
            stack.callback(handler.removeFilter, project_filter)

        streams = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
        for stream in streams:
            if stream is not None:
                stream.flush()
        # Native libraries and inherited subprocess streams write directly to 1/2.
        for descriptor in (1, 2):
            saved = os.dup(descriptor)
            stack.callback(os.close, saved)
            stack.callback(os.dup2, saved, descriptor)
            os.dup2(sink.fileno(), descriptor)
        with redirect_stdout(sink), redirect_stderr(sink):
            try:
                yield
            finally:
                for stream in streams:
                    if stream is not None:
                        stream.flush()


def _safe_text(value: object) -> str:
    message = _SECRET.sub(r"\1[REDACTED]", " ".join(str(value).split()))
    return (message[:500] + "...") if len(message) > 500 else message


def _value(option: object | None, name: str, default: object) -> object:
    if option is not None:
        return option
    from_environment = setting(name)
    return default if from_environment is None else from_environment


def _integer(option: int | None, name: str, default: int) -> int:
    raw = _value(option, name, default)
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ConfigurationError(f"{name} must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


def _float(option: float | None, name: str, default: float) -> float:
    raw = _value(option, name, default)
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ConfigurationError(f"{name} must be a number")
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{name} must be a number") from exc


def _boolean(option: bool | None, name: str, default: bool) -> bool:
    return _parse_boolean(_value(option, name, default), name)


def _parse_boolean(raw: object, name: str) -> bool:
    if type(raw) is bool:
        return raw
    if isinstance(raw, str):
        if raw.casefold() in ("true", "yes", "1", "on"):
            return True
        if raw.casefold() in ("false", "no", "0", "off"):
            return False
    raise ConfigurationError(f"{name} must be a boolean")


def _boolean_override(
    option: bool | None,
    name: str,
    *,
    parent_options: tuple[bool | None, ...] = (),
    parent_env_names: tuple[str, ...] = (),
) -> bool | None:
    if option is not None:
        return option
    if any(parent is not None for parent in parent_options):
        return None
    # Source precedence also applies across inherited settings.
    if name not in os.environ and any(
        parent_name in os.environ for parent_name in parent_env_names
    ):
        return None
    raw = setting(name)
    return None if raw is None else _parse_boolean(raw, name)


app = typer.Typer(
    name="multicuts",
    help=(
        "Find and render transcript-based short and long clips with "
        "explainable viral-potential scores."
    ),
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command(
    epilog=(
        "Examples: --no-long-clips --no-short-variants publishes primary shorts; "
        "--no-subtitles --short-variant-subtitles captions only short variants."
    )
)
def run_command(
    ctx: typer.Context,
    source: Annotated[
        str,
        typer.Argument(
            ..., metavar="SOURCE", help="Local video path or supported YouTube URL."
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Root for unique runs and shared caches."),
    ],
    llm_backend: Annotated[
        str | None,
        typer.Option(
            "--llm-backend",
            help="openai, anthropic, gemini, codex, claude, or agy.",
            rich_help_panel="Analysis",
        ),
    ] = None,
    llm_model: Annotated[
        str | None,
        typer.Option(
            "--llm-model",
            help="Model identifier for the selected backend.",
            rich_help_panel="Analysis",
        ),
    ] = None,
    llm_effort: Annotated[
        str | None,
        typer.Option(
            "--llm-effort",
            help="Reasoning level; auto uses provider default.",
            rich_help_panel="Analysis",
        ),
    ] = None,
    context: Annotated[
        str | None,
        typer.Option(
            "--context",
            help="Describe the video's subject and scope to guide clips.",
            rich_help_panel="Analysis",
        ),
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option(
            "--lang",
            help="Transcription language code or auto.",
            rich_help_panel="Analysis",
        ),
    ] = None,
    asr_model: Annotated[
        str | None,
        typer.Option(
            "--asr-model",
            help="multisubs transcription model (default: turbo).",
            rich_help_panel="Analysis",
        ),
    ] = None,
    asr_backend: Annotated[
        str | None,
        typer.Option(
            "--asr-backend",
            help="whisperx, faster-whisper, parakeet, or qwen (default: whisperx).",
            rich_help_panel="Analysis",
        ),
    ] = None,
    overlap_threshold: Annotated[
        float | None,
        typer.Option(
            "--overlap-threshold",
            help="Same-class overlap suppression ratio.",
            rich_help_panel="Clips",
        ),
    ] = None,
    short_clips: Annotated[
        bool | None,
        typer.Option(
            "--short-clips/--no-short-clips",
            help="Enable short cuts and their variants (default: on).",
            rich_help_panel="Clips",
        ),
    ] = None,
    long_clips: Annotated[
        bool | None,
        typer.Option(
            "--long-clips/--no-long-clips",
            help="Enable long cuts and their variants (default: on).",
            rich_help_panel="Clips",
        ),
    ] = None,
    short_aspect_ratio: Annotated[
        str | None,
        typer.Option(
            "--short-aspect-ratio",
            help=(
                "Primary short format: original, 9:16, 16:9, or 1:1 (default: 9:16)."
            ),
            rich_help_panel="Clips",
        ),
    ] = None,
    long_aspect_ratio: Annotated[
        str | None,
        typer.Option(
            "--long-aspect-ratio",
            help=("Primary long format: original, 9:16, 16:9, or 1:1 (default: 16:9)."),
            rich_help_panel="Clips",
        ),
    ] = None,
    vertical_width: Annotated[
        int | None,
        typer.Option(
            "--vertical-width",
            help="9:16 width in pixels (default: 1080).",
            rich_help_panel="Clips",
        ),
    ] = None,
    vertical_height: Annotated[
        int | None,
        typer.Option(
            "--vertical-height",
            help="9:16 height in pixels (default: 1920).",
            rich_help_panel="Clips",
        ),
    ] = None,
    horizontal_width: Annotated[
        int | None,
        typer.Option(
            "--horizontal-width",
            help="16:9 width in pixels (default: 1920).",
            rich_help_panel="Clips",
        ),
    ] = None,
    horizontal_height: Annotated[
        int | None,
        typer.Option(
            "--horizontal-height",
            help="16:9 height in pixels (default: 1080).",
            rich_help_panel="Clips",
        ),
    ] = None,
    square_size: Annotated[
        int | None,
        typer.Option(
            "--square-size",
            help="1:1 side in pixels; positive and even (default: 1080).",
            rich_help_panel="Clips",
        ),
    ] = None,
    variants: Annotated[
        bool | None,
        typer.Option(
            "--variants/--no-variants",
            help=(
                "Add 9:16, 16:9, and 1:1 versions (default: on). "
                "--no-variants publishes only the primary format. "
                "Square primary output always has no variants, including "
                "original square sources."
                " Class-specific variant flags take precedence."
            ),
            rich_help_panel="Clips",
        ),
    ] = None,
    short_variants: Annotated[
        bool | None,
        typer.Option(
            "--short-variants/--no-short-variants",
            help="Additional short formats; inherits --variants by default.",
            rich_help_panel="Clips",
        ),
    ] = None,
    long_variants: Annotated[
        bool | None,
        typer.Option(
            "--long-variants/--no-long-variants",
            help="Additional long formats; inherits --variants by default.",
            rich_help_panel="Clips",
        ),
    ] = None,
    subtitle_template: Annotated[
        str | None,
        typer.Option(
            "--subtitle-template",
            help="Subtitle style (default: yellow-pop).",
            rich_help_panel="Subtitles",
        ),
    ] = None,
    subtitle_template_dir: Annotated[
        Path | None,
        typer.Option(
            "--subtitle-template-dir",
            help="Custom subtitle template directory.",
            rich_help_panel="Subtitles",
        ),
    ] = None,
    subtitles: Annotated[
        bool | None,
        typer.Option(
            "--subtitles/--no-subtitles",
            help=(
                "Enable/disable subtitles for both classes and variants (default: on). "
                "Class-specific CLI flags win regardless of order; "
                "CLI flags override environment settings."
            ),
            rich_help_panel="Subtitles",
        ),
    ] = None,
    short_subtitles: Annotated[
        bool | None,
        typer.Option(
            "--short-subtitles/--no-short-subtitles",
            help=(
                "Short subtitles and the default for short variants. "
                "Overrides the shared CLI shortcut."
            ),
            rich_help_panel="Subtitles",
        ),
    ] = None,
    long_subtitles: Annotated[
        bool | None,
        typer.Option(
            "--long-subtitles/--no-long-subtitles",
            help=(
                "Long subtitles and the default for long variants. "
                "Overrides the shared CLI shortcut."
            ),
            rich_help_panel="Subtitles",
        ),
    ] = None,
    short_variant_subtitles: Annotated[
        bool | None,
        typer.Option(
            "--short-variant-subtitles/--no-short-variant-subtitles",
            help="Short variant subtitles; inherits short subtitles by default.",
            rich_help_panel="Subtitles",
        ),
    ] = None,
    long_variant_subtitles: Annotated[
        bool | None,
        typer.Option(
            "--long-variant-subtitles/--no-long-variant-subtitles",
            help="Long variant subtitles; inherits long subtitles by default.",
            rich_help_panel="Subtitles",
        ),
    ] = None,
    block_chars: Annotated[
        int | None,
        typer.Option(
            "--block-chars",
            help="Transcript characters per AI block (default: 24000).",
            rich_help_panel="Analysis",
        ),
    ] = None,
    block_overlap_chars: Annotated[
        int | None,
        typer.Option(
            "--block-overlap-chars",
            help="Shared characters between AI blocks (default: 4000).",
            rich_help_panel="Analysis",
        ),
    ] = None,
    keep_intermediates: Annotated[
        bool | None,
        typer.Option(
            "--keep-intermediates/--discard-intermediates",
            help="Keep private render files for inspection (default: discard).",
            rich_help_panel="Execution",
        ),
    ] = None,
    force_recompute: Annotated[
        bool | None,
        typer.Option(
            "--force-recompute/--reuse-cache",
            help="Recompute transcription and AI analysis (default: reuse cache).",
            rich_help_panel="Execution",
        ),
    ] = None,
    verbose: Annotated[
        bool | None,
        typer.Option(
            "--verbose/--quiet",
            help="Show debug details and dependency output.",
            rich_help_panel="Execution",
        ),
    ] = None,
) -> None:
    backend = _value(llm_backend, "LLM_BACKEND", "")
    llm_model_value = _value(llm_model, "LLM_MODEL", "")
    if not isinstance(backend, str) or not backend.strip():
        raise ConfigurationError("Set LLM_BACKEND or pass --llm-backend")
    if not isinstance(llm_model_value, str) or not llm_model_value.strip():
        raise ConfigurationError("Set LLM_MODEL or pass --llm-model")
    effort_value = _value(llm_effort, "LLM_EFFORT", None)
    if effort_value is not None and not isinstance(effort_value, str):
        raise ConfigurationError("LLM_EFFORT must be a string")
    template_dir = _value(subtitle_template_dir, "SUBTITLE_TEMPLATE_DIR", None)
    config = AppConfig(
        source=source,
        output_dir=output_dir.expanduser(),
        llm_backend=backend,
        llm_model=llm_model_value,
        llm_effort=effort_value,
        editorial_context=context,
        overlap_threshold=_float(overlap_threshold, "OVERLAP_THRESHOLD", 0.60),
        language=lang,
        transcription_model=str(_value(asr_model, "ASR_MODEL", "turbo")),
        asr_backend=str(_value(asr_backend, "ASR_BACKEND", "whisperx")),
        short_aspect_ratio=str(
            _value(short_aspect_ratio, "SHORT_ASPECT_RATIO", "9:16")
        ),
        long_aspect_ratio=str(_value(long_aspect_ratio, "LONG_ASPECT_RATIO", "16:9")),
        vertical_width=_integer(vertical_width, "VERTICAL_WIDTH", 1080),
        vertical_height=_integer(vertical_height, "VERTICAL_HEIGHT", 1920),
        horizontal_width=_integer(horizontal_width, "HORIZONTAL_WIDTH", 1920),
        horizontal_height=_integer(horizontal_height, "HORIZONTAL_HEIGHT", 1080),
        square_size=_integer(square_size, "SQUARE_SIZE", 1080),
        short_clips_enabled=_boolean(short_clips, "SHORT_CLIPS_ENABLED", True),
        long_clips_enabled=_boolean(long_clips, "LONG_CLIPS_ENABLED", True),
        render_variants=_boolean(variants, "RENDER_VARIANTS", True),
        short_variants_enabled=_boolean_override(
            short_variants,
            "SHORT_VARIANTS_ENABLED",
            parent_options=(variants,),
            parent_env_names=("RENDER_VARIANTS",),
        ),
        long_variants_enabled=_boolean_override(
            long_variants,
            "LONG_VARIANTS_ENABLED",
            parent_options=(variants,),
            parent_env_names=("RENDER_VARIANTS",),
        ),
        subtitles_enabled=True if subtitles is None else subtitles,
        short_subtitles_enabled=_boolean_override(
            short_subtitles, "SHORT_SUBTITLES_ENABLED", parent_options=(subtitles,)
        ),
        long_subtitles_enabled=_boolean_override(
            long_subtitles, "LONG_SUBTITLES_ENABLED", parent_options=(subtitles,)
        ),
        short_variant_subtitles_enabled=_boolean_override(
            short_variant_subtitles,
            "SHORT_VARIANT_SUBTITLES_ENABLED",
            parent_options=(short_subtitles, subtitles),
            parent_env_names=("SHORT_SUBTITLES_ENABLED",),
        ),
        long_variant_subtitles_enabled=_boolean_override(
            long_variant_subtitles,
            "LONG_VARIANT_SUBTITLES_ENABLED",
            parent_options=(long_subtitles, subtitles),
            parent_env_names=("LONG_SUBTITLES_ENABLED",),
        ),
        subtitle_template=str(
            _value(subtitle_template, "SUBTITLE_TEMPLATE", "yellow-pop")
        ),
        subtitle_template_dir=Path(str(template_dir)).expanduser()
        if template_dir
        else None,
        block_chars=_integer(block_chars, "BLOCK_CHARS", 24000),
        block_overlap_chars=_integer(block_overlap_chars, "BLOCK_OVERLAP_CHARS", 4000),
        keep_intermediates=bool(keep_intermediates),
        force_recompute=bool(force_recompute),
        verbose=bool(verbose),
    )
    state = ctx.obj if isinstance(ctx.obj, _CliContext) else _CliContext()
    state.parsed_config = config


def parse_run_config(argv: Sequence[str] | None = None) -> AppConfig:
    state = _CliContext()
    try:
        app(
            args=list(sys.argv[1:] if argv is None else argv),
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


def _main(
    argv: Sequence[str] | None = None, *, pipeline: PipelineRunner | None = None
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    state = _CliContext()
    configure_logging("--verbose" in arguments)
    try:
        app(args=arguments, prog_name="multicuts", obj=state, standalone_mode=True)
    except KeyboardInterrupt:
        logger.warning("Run interrupted")
        return 130
    except SystemExit as error:
        if error.code not in (0, None):
            return int(error.code)
        if state.parsed_config is None:
            return EXIT_SUCCESS
    except MulticutsError as error:
        for error_type, code, label in _ERROR_DETAILS:
            if isinstance(error, error_type):
                logger.error("%s: %s", label, _safe_text(error))
                return code
        return EXIT_UNEXPECTED
    except Exception:
        logger.error("Unexpected failure while parsing options")
        return EXIT_UNEXPECTED
    if state.parsed_config is None:
        return EXIT_SUCCESS
    configure_logging(state.parsed_config.verbose)
    try:
        with _pipeline_output(state.parsed_config.verbose):
            result = (pipeline or run_pipeline)(state.parsed_config)
        typer.echo(
            f"Run {result.run_id}: {result.outcome.value}; "
            f"clips={len(result.clip_paths)}; manifest={result.manifest_path}"
        )
        return (
            EXIT_SUCCESS
            if result.outcome in (RunOutcome.COMPLETED, RunOutcome.ZERO_SELECTION)
            else EXIT_RENDERING
        )
    except KeyboardInterrupt:
        logger.warning("Run interrupted")
        return 130
    except MulticutsError as error:
        for error_type, code, label in _ERROR_DETAILS:
            if isinstance(error, error_type):
                logger.error("%s: %s", label, _safe_text(error))
                return code
        return EXIT_UNEXPECTED
    except Exception:
        logger.error("Unexpected run failure")
        return EXIT_UNEXPECTED


def main(
    argv: Sequence[str] | None = None, *, pipeline: PipelineRunner | None = None
) -> int:
    project = logging.getLogger("multicuts")
    level, propagate = project.level, project.propagate
    try:
        return _main(argv, pipeline=pipeline)
    finally:
        for handler in list(project.handlers):
            if isinstance(handler, _CliHandler):
                project.removeHandler(handler)
                handler.close()
        project.setLevel(level)
        project.propagate = propagate

"""Command line interface for one semantic multicuts run."""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Annotated, Any

import typer
from typer.core import TyperCommand, TyperOption

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
from multicuts.models import TimeRange
from multicuts.pipeline import RunOutcome, RunResult, run_pipeline
from multicuts.subtitles import SUBTITLE_BOOLEAN_FIELDS, SubtitleOptions
from multicuts.variants import VARIANT_RATIOS, OutputOptions

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


def _time_range(value: tuple[str, str] | None, option: str) -> TimeRange | None:
    if value is None:
        return None

    def seconds(raw: str) -> float:
        if re.fullmatch(r"\d+(?::\d{1,2}){0,2}(?:\.\d+)?", raw) is None:
            raise ValueError("invalid timestamp")
        parts = [float(part) for part in raw.split(":")]
        if any(part >= 60 for part in parts[1:]):
            raise ValueError("invalid clock component")
        total = 0.0
        for part in parts:
            total = total * 60 + part
        return total

    try:
        return TimeRange(seconds(value[0]), seconds(value[1]))
    except ValueError as exc:
        raise ConfigurationError(
            f"{option} requires ordered START END within the source; "
            "use nonnegative seconds, MM:SS, or HH:MM:SS (decimals allowed)"
        ) from exc


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


def _subtitle_options(options: SubtitleOptions) -> SubtitleOptions:
    values: dict[str, object] = {}
    for field in fields(options):
        name = "SUBTITLE_" + field.name.upper()
        raw = _value(getattr(options, field.name), name, None)
        if raw is None:
            continue
        if field.name in SUBTITLE_BOOLEAN_FIELDS:
            raw = _parse_boolean(raw, name)
        elif field.name == "fonts_dir":
            raw = Path(str(raw)).expanduser()
        elif not isinstance(raw, str):
            raise ConfigurationError(f"{name} must be text")
        values[field.name] = raw
    return replace(options, **values)


def _capture_output_option(
    ctx: typer.Context, param: TyperOption, value: object
) -> None:
    if value is not None:
        ctx.meta.setdefault("output_options", {})[param.name] = value


class _OutputCommand(TyperCommand):
    """Register the same public subtitle fields for every concrete output scope."""

    def __init__(self, name: str | None, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        for clip_class in ("short", "long"):
            for variant in (None, *VARIANT_RATIOS, "original"):
                scope = clip_class if variant is None else f"{clip_class}-{variant}"
                panel = f"{scope} output"
                if variant is not None:
                    self.params.append(
                        TyperOption(
                            param_decls=[f"--{scope}/--no-{scope}"],
                            is_flag=True,
                            default=None,
                            expose_value=False,
                            callback=_capture_output_option,
                            help="Render this variant when supported by the source.",
                            rich_help_panel=panel,
                        )
                    )
                self.params.append(
                    TyperOption(
                        param_decls=[f"--subtitle-{scope}/--no-subtitle-{scope}"],
                        is_flag=True,
                        default=None,
                        expose_value=False,
                        callback=_capture_output_option,
                        help="Enable captions for this output scope; unset inherits.",
                        rich_help_panel=panel,
                    )
                )
                for key in (
                    "template",
                    "template_dir",
                    *(field.name for field in fields(SubtitleOptions)),
                ):
                    flag = f"subtitle-{scope}-{key.replace('_', '-')}"
                    boolean = key in SUBTITLE_BOOLEAN_FIELDS
                    self.params.append(
                        TyperOption(
                            param_decls=[
                                f"--{flag}/--no-{flag}" if boolean else f"--{flag}"
                            ],
                            type=bool if boolean else str,
                            is_flag=boolean,
                            default=None,
                            expose_value=False,
                            callback=_capture_output_option,
                            help=(
                                f"Override subtitle {key.replace('_', ' ')}; "
                                "unset inherits."
                            ),
                            rich_help_panel=panel,
                        )
                    )


def _class_subtitle_value(
    option: bool | None, shared: bool | None, clip_class: str
) -> bool | None:
    if option is not None:
        return option
    if shared is not None:
        return None
    names = (
        f"SUBTITLE_{clip_class.upper()}_ENABLED",
        f"{clip_class.upper()}_SUBTITLES_ENABLED",
    )
    for name in names:
        if name in os.environ:
            return _parse_boolean(os.environ[name], name)
    for name in names:
        value = setting(name)
        if value is not None:
            return _parse_boolean(value, name)
    return None


def _output_options(ctx: typer.Context) -> tuple[OutputOptions, ...]:
    """Resolve source priority before specificity, independently for each field."""
    cli = dict(ctx.params)
    cli.update(ctx.meta.get("output_options", {}))
    cache: dict[str, str | None] = {}

    def resolve(
        keys: tuple[str, ...], env_names: tuple[str | None, ...] | None = None
    ) -> object | None:
        names = tuple(key.upper() for key in keys) if env_names is None else env_names
        for key in keys:
            if cli.get(key) is not None:
                return cli[key]
        for name in names:
            if name is not None and name in os.environ:
                return os.environ[name]
        for name in names:
            if name is None:
                continue
            if name not in cache:
                cache[name] = setting(name)
            if cache[name] is not None:
                return cache[name]
        return None

    def captions(clip_class: str, scope: str, *, additional: bool) -> bool | None:
        keys = (f"subtitle_{scope}",)
        names: tuple[str | None, ...] = (f"SUBTITLE_{scope.upper()}_ENABLED",)
        if additional:
            keys += (f"{clip_class}_variant_subtitles",)
            names += (f"{clip_class.upper()}_VARIANT_SUBTITLES_ENABLED",)
        keys += (
            f"subtitle_{clip_class}",
            f"{clip_class}_subtitles",
            "subtitles",
        )
        names += (
            f"SUBTITLE_{clip_class.upper()}_ENABLED",
            f"{clip_class.upper()}_SUBTITLES_ENABLED",
            None,
        )
        value = resolve(keys, names)
        return None if value is None else _parse_boolean(value, names[0] or scope)

    outputs: list[OutputOptions] = []
    for clip_class in ("short", "long"):
        for variant in (None, *VARIANT_RATIOS, "original"):
            scope = (
                clip_class
                if variant is None
                else f"{clip_class}_{variant.replace('-', '_')}"
            )
            prefixes = (f"subtitle_{scope}_", f"subtitle_{clip_class}_", "subtitle_")
            values: dict[str, object] = {}
            for field in fields(SubtitleOptions):
                raw = resolve(tuple(prefix + field.name for prefix in prefixes))
                if raw is None:
                    continue
                if field.name in SUBTITLE_BOOLEAN_FIELDS:
                    raw = _parse_boolean(raw, f"subtitle_{scope}_{field.name}".upper())
                elif field.name == "fonts_dir":
                    raw = Path(str(raw)).expanduser()
                values[field.name] = raw
            template = resolve(tuple(prefix + "template" for prefix in prefixes))
            directory = resolve(tuple(prefix + "template_dir" for prefix in prefixes))

            subtitle_enabled = captions(clip_class, scope, additional=False)
            additional_enabled = (
                captions(clip_class, scope, additional=True)
                if variant is not None
                else None
            )
            enabled = None
            if variant is not None:
                render_key = scope.upper() + "_ENABLED"
                enabled = _boolean_override(
                    cli.get(scope),
                    render_key,
                    parent_options=(
                        cli.get(f"{clip_class}_variants"),
                        cli.get("variants"),
                    ),
                    parent_env_names=(
                        f"{clip_class.upper()}_VARIANTS_ENABLED",
                        "RENDER_VARIANTS",
                    ),
                )
            outputs.append(
                OutputOptions(
                    clip_class,
                    variant,
                    enabled,
                    subtitle_enabled,
                    None if template is None else str(template),
                    None if directory is None else Path(str(directory)).expanduser(),
                    replace(SubtitleOptions(), **values),
                    additional_enabled,
                )
            )
    return tuple(outputs)


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
    cls=_OutputCommand,
    epilog=(
        "Examples: --no-long-clips --no-short-variants publishes primary shorts; "
        "--no-subtitles --short-variant-subtitles captions only short variants."
    ),
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
    search_range: Annotated[
        tuple[str, str] | None,
        typer.Option(
            "--search-range",
            metavar="START END",
            help=(
                "Search only within these source times (seconds or HH:MM:SS). "
                "YouTube acquisition may include extra keyframe data."
            ),
            rich_help_panel="Analysis",
        ),
    ] = None,
    clip_range: Annotated[
        tuple[str, str] | None,
        typer.Option(
            "--clip-range",
            metavar="START END",
            help=(
                "Render one source interval without AI review. Local bounds are "
                "exact; YouTube cuts include the acquired keyframe padding."
            ),
            rich_help_panel="Clips",
        ),
    ] = None,
    clip_full: Annotated[
        bool,
        typer.Option(
            "--clip-full",
            help="Render the entire source as one cut without AI review.",
            rich_help_panel="Clips",
        ),
    ] = False,
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
                "Add all source-compatible crop and blur variants (default: on). "
                "--no-variants publishes only the primary format. "
                "Class and individual variant flags can override this default."
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
    subtitle_position: Annotated[
        str | None,
        typer.Option(
            "--subtitle-position",
            metavar="POSITION",
            help=(
                "Subtitle position, such as bottom-center: top/middle/bottom with "
                "left/center/right."
            ),
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_margin_left: Annotated[
        str | None,
        typer.Option(
            "--subtitle-margin-left",
            metavar="LENGTH",
            help="Left margin as a percentage of width or pixels.",
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_margin_right: Annotated[
        str | None,
        typer.Option(
            "--subtitle-margin-right",
            metavar="LENGTH",
            help="Right margin as a percentage of width or pixels.",
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_margin_top: Annotated[
        str | None,
        typer.Option(
            "--subtitle-margin-top",
            metavar="LENGTH",
            help=(
                "Top-position margin as a percentage of render height or pixels; "
                "an explicit value is rejected for middle and bottom positions."
            ),
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_margin_bottom: Annotated[
        str | None,
        typer.Option(
            "--subtitle-margin-bottom",
            metavar="LENGTH",
            help=(
                "Bottom-position margin as a percentage of render height or "
                "pixels; an explicit value is rejected for top and middle "
                "positions."
            ),
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_max_width: Annotated[
        str | None,
        typer.Option(
            "--subtitle-max-width",
            metavar="LENGTH",
            help=(
                "Maximum subtitle line width. Native percentages use the width "
                "after horizontal margins; explicit percentages use render width."
            ),
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_max_height: Annotated[
        str | None,
        typer.Option(
            "--subtitle-max-height",
            metavar="LENGTH",
            help=(
                "Maximum subtitle box height. Native percentages use the height "
                "after the active margin; explicit percentages use the render "
                "height."
            ),
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_position_x: Annotated[
        str | None,
        typer.Option(
            "--subtitle-position-x",
            metavar="LENGTH",
            help="Horizontal anchor coordinate from the left edge of the final frame.",
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_position_y: Annotated[
        str | None,
        typer.Option(
            "--subtitle-position-y",
            metavar="LENGTH",
            help="Vertical anchor coordinate from the top edge of the final frame.",
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_anchor: Annotated[
        str | None,
        typer.Option(
            "--subtitle-anchor",
            metavar="POSITION",
            help="Required subtitle-box anchor for custom coordinates.",
            rich_help_panel="Subtitle positioning",
        ),
    ] = None,
    subtitle_font: Annotated[
        str | None,
        typer.Option(
            "--subtitle-font",
            metavar="NAME",
            help="Font family.",
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_font_weight: Annotated[
        str | None,
        typer.Option(
            "--subtitle-font-weight",
            metavar="WEIGHT",
            help=(
                "Font weight name or rank 100-900 in steps of 100; cannot be "
                "combined with bold flags."
            ),
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_bold: Annotated[
        bool | None,
        typer.Option(
            "--subtitle-bold/--no-subtitle-bold",
            help="Use bold weight (700) or regular weight (400).",
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_italic: Annotated[
        bool | None,
        typer.Option(
            "--subtitle-italic/--no-subtitle-italic",
            help="Enable or disable italic text.",
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_text_case: Annotated[
        str | None,
        typer.Option(
            "--subtitle-text-case",
            metavar="MODE",
            help="Subtitle display casing: original, uppercase, or lowercase.",
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_fonts_dir: Annotated[
        Path | None,
        typer.Option(
            "--subtitle-fonts-dir",
            metavar="DIR",
            help="Directory containing additional subtitle font files.",
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_font_size: Annotated[
        str | None,
        typer.Option(
            "--subtitle-font-size",
            metavar="LENGTH",
            help="Font size as a percentage of the render height or pixels.",
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_letter_spacing: Annotated[
        str | None,
        typer.Option(
            "--subtitle-letter-spacing",
            metavar="LENGTH",
            help="Extra character spacing in pixels or as a percentage of font size.",
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_line_height: Annotated[
        str | None,
        typer.Option(
            "--subtitle-line-height",
            metavar="auto|LENGTH",
            help=(
                "Distance between text baselines: auto, pixels, or a percentage "
                "of natural line height."
            ),
            rich_help_panel="Subtitle typography",
        ),
    ] = None,
    subtitle_text_color: Annotated[
        str | None,
        typer.Option(
            "--subtitle-text-color",
            metavar="COLOR",
            help="Subtitle text color.",
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_backdrop: Annotated[
        str | None,
        typer.Option(
            "--subtitle-backdrop",
            metavar="TYPE",
            help="Subtitle backdrop: none, outline, or box.",
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_backdrop_color: Annotated[
        str | None,
        typer.Option(
            "--subtitle-backdrop-color",
            metavar="COLOR",
            help="Outline, box, and shadow color.",
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_word_backdrop: Annotated[
        str | None,
        typer.Option(
            "--subtitle-word-backdrop",
            metavar="TYPE",
            help="Timed word decoration: none, outline, or box.",
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_word_backdrop_color: Annotated[
        str | None,
        typer.Option(
            "--subtitle-word-backdrop-color",
            metavar="COLOR",
            help="Word-box color using #RRGGBB or #RRGGBBAA.",
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_opacity: Annotated[
        str | None,
        typer.Option(
            "--subtitle-opacity",
            metavar="PERCENT",
            help=(
                "Opacity from 0% through 100%, multiplied with each component "
                "color opacity."
            ),
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_backdrop_size: Annotated[
        str | None,
        typer.Option(
            "--subtitle-backdrop-size",
            metavar="LENGTH",
            help=(
                "Backdrop/outline size as a percentage of the resolved font size "
                "or pixels."
            ),
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_word_backdrop_size: Annotated[
        str | None,
        typer.Option(
            "--subtitle-word-backdrop-size",
            metavar="LENGTH",
            help=(
                "Timed word-box padding as a percentage of the resolved font size "
                "or pixels."
            ),
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_shadow_size: Annotated[
        str | None,
        typer.Option(
            "--subtitle-shadow-size",
            metavar="LENGTH",
            help="Shadow size as a percentage of the resolved font size or pixels.",
            rich_help_panel="Subtitle appearance",
        ),
    ] = None,
    subtitle_animation_cue_text_entrance: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-text-entrance",
            metavar="TYPE",
            help="Cue text entrance animation; omission inherits the template.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_text_entrance_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-text-entrance-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_text_emphasis: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-text-emphasis",
            metavar="TYPE",
            help="Cue text emphasis animation; omission inherits the template.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_text_emphasis_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-text-emphasis-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_text_exit: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-text-exit",
            metavar="TYPE",
            help="Cue text exit animation; omission inherits the selected template.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_text_exit_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-text-exit-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_backdrop_entrance: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-backdrop-entrance",
            metavar="TYPE",
            help=(
                "Cue backdrop entrance animation; omission inherits the selected "
                "template."
            ),
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_backdrop_entrance_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-backdrop-entrance-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_backdrop_emphasis: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-backdrop-emphasis",
            metavar="TYPE",
            help=(
                "Cue backdrop emphasis animation; omission inherits the selected "
                "template."
            ),
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_backdrop_emphasis_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-backdrop-emphasis-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_backdrop_exit: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-backdrop-exit",
            metavar="TYPE",
            help="Cue backdrop exit animation; omission inherits the template.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_cue_backdrop_exit_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-cue-backdrop-exit-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_text_entrance: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-text-entrance",
            metavar="TYPE",
            help="Word text entrance animation; omission inherits the template.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_text_entrance_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-text-entrance-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_text_emphasis: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-text-emphasis",
            metavar="TYPE",
            help="Word text emphasis animation; omission inherits the template.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_text_emphasis_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-text-emphasis-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_text_exit: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-text-exit",
            metavar="TYPE",
            help="Word text exit animation; omission inherits the selected template.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_text_exit_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-text-exit-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_backdrop_entrance: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-backdrop-entrance",
            metavar="TYPE",
            help=(
                "Word backdrop entrance animation; omission inherits the selected "
                "template."
            ),
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_backdrop_entrance_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-backdrop-entrance-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_backdrop_emphasis: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-backdrop-emphasis",
            metavar="TYPE",
            help=(
                "Word backdrop emphasis animation; omission inherits the selected "
                "template."
            ),
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_backdrop_emphasis_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-backdrop-emphasis-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_backdrop_exit: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-backdrop-exit",
            metavar="TYPE",
            help="Word backdrop exit animation; omission inherits the template.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_backdrop_exit_duration: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-backdrop-exit-duration",
            metavar="DURATION",
            help="Override this effect duration with a value such as 150ms or 0.15s.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_text_mode: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-text-mode",
            metavar="MODE",
            help="Timed word text behavior: progressive or active-word.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_backdrop_mode: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-backdrop-mode",
            metavar="MODE",
            help="Timed word backdrop behavior: progressive or active-word.",
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_animation_word_text_highlight_color: Annotated[
        str | None,
        typer.Option(
            "--subtitle-animation-word-text-highlight-color",
            metavar="COLOR",
            help=(
                "Highlight text color as #RRGGBB or #RRGGBBAA; requires highlight "
                "emphasis."
            ),
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_disable_cue_animations: Annotated[
        bool | None,
        typer.Option(
            "--subtitle-disable-cue-animations/--no-subtitle-disable-cue-animations",
            help=(
                "Remove all cue text/backdrop animation phases while preserving "
                "the static cue backdrop."
            ),
            rich_help_panel="Subtitle animations",
        ),
    ] = None,
    subtitle_disable_word_animations: Annotated[
        bool | None,
        typer.Option(
            "--subtitle-disable-word-animations/--no-subtitle-disable-word-animations",
            help=(
                "Remove all word text/backdrop animation phases, word highlight, "
                "and timed word decoration."
            ),
            rich_help_panel="Subtitle animations",
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
    scoped_cli = ctx.meta.get("output_options", {})
    short_subtitles = scoped_cli.get("subtitle_short", short_subtitles)
    long_subtitles = scoped_cli.get("subtitle_long", long_subtitles)
    direct = clip_range is not None or clip_full
    backend = "" if direct else _value(llm_backend, "LLM_BACKEND", "")
    llm_model_value = "" if direct else _value(llm_model, "LLM_MODEL", "")
    if not isinstance(backend, str) or (not direct and not backend.strip()):
        raise ConfigurationError("Set LLM_BACKEND or pass --llm-backend")
    if not isinstance(llm_model_value, str) or (
        not direct and not llm_model_value.strip()
    ):
        raise ConfigurationError("Set LLM_MODEL or pass --llm-model")
    effort_value = None if direct else _value(llm_effort, "LLM_EFFORT", None)
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
        search_range=_time_range(search_range, "--search-range"),
        clip_range=_time_range(clip_range, "--clip-range"),
        full_video=clip_full,
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
        short_subtitles_enabled=_class_subtitle_value(
            short_subtitles, subtitles, "short"
        ),
        long_subtitles_enabled=_class_subtitle_value(long_subtitles, subtitles, "long"),
        short_variant_subtitles_enabled=_boolean_override(
            short_variant_subtitles,
            "SHORT_VARIANT_SUBTITLES_ENABLED",
            parent_options=(short_subtitles, subtitles),
            parent_env_names=("SUBTITLE_SHORT_ENABLED", "SHORT_SUBTITLES_ENABLED"),
        ),
        long_variant_subtitles_enabled=_boolean_override(
            long_variant_subtitles,
            "LONG_VARIANT_SUBTITLES_ENABLED",
            parent_options=(long_subtitles, subtitles),
            parent_env_names=("SUBTITLE_LONG_ENABLED", "LONG_SUBTITLES_ENABLED"),
        ),
        subtitle_template=str(
            _value(subtitle_template, "SUBTITLE_TEMPLATE", "yellow-pop")
        ),
        subtitle_template_dir=Path(str(template_dir)).expanduser()
        if template_dir
        else None,
        subtitle_options=_subtitle_options(
            SubtitleOptions(
                position=subtitle_position,
                margin_left=subtitle_margin_left,
                margin_right=subtitle_margin_right,
                margin_top=subtitle_margin_top,
                margin_bottom=subtitle_margin_bottom,
                max_width=subtitle_max_width,
                max_height=subtitle_max_height,
                position_x=subtitle_position_x,
                position_y=subtitle_position_y,
                anchor=subtitle_anchor,
                font=subtitle_font,
                font_weight=subtitle_font_weight,
                bold=subtitle_bold,
                italic=subtitle_italic,
                text_case=subtitle_text_case,
                fonts_dir=subtitle_fonts_dir,
                font_size=subtitle_font_size,
                letter_spacing=subtitle_letter_spacing,
                line_height=subtitle_line_height,
                text_color=subtitle_text_color,
                backdrop=subtitle_backdrop,
                backdrop_color=subtitle_backdrop_color,
                word_backdrop=subtitle_word_backdrop,
                word_backdrop_color=subtitle_word_backdrop_color,
                opacity=subtitle_opacity,
                backdrop_size=subtitle_backdrop_size,
                word_backdrop_size=subtitle_word_backdrop_size,
                shadow_size=subtitle_shadow_size,
                animation_cue_text_entrance=subtitle_animation_cue_text_entrance,
                animation_cue_text_entrance_duration=subtitle_animation_cue_text_entrance_duration,
                animation_cue_text_emphasis=subtitle_animation_cue_text_emphasis,
                animation_cue_text_emphasis_duration=subtitle_animation_cue_text_emphasis_duration,
                animation_cue_text_exit=subtitle_animation_cue_text_exit,
                animation_cue_text_exit_duration=subtitle_animation_cue_text_exit_duration,
                animation_cue_backdrop_entrance=subtitle_animation_cue_backdrop_entrance,
                animation_cue_backdrop_entrance_duration=subtitle_animation_cue_backdrop_entrance_duration,
                animation_cue_backdrop_emphasis=subtitle_animation_cue_backdrop_emphasis,
                animation_cue_backdrop_emphasis_duration=subtitle_animation_cue_backdrop_emphasis_duration,
                animation_cue_backdrop_exit=subtitle_animation_cue_backdrop_exit,
                animation_cue_backdrop_exit_duration=subtitle_animation_cue_backdrop_exit_duration,
                animation_word_text_entrance=subtitle_animation_word_text_entrance,
                animation_word_text_entrance_duration=subtitle_animation_word_text_entrance_duration,
                animation_word_text_emphasis=subtitle_animation_word_text_emphasis,
                animation_word_text_emphasis_duration=subtitle_animation_word_text_emphasis_duration,
                animation_word_text_exit=subtitle_animation_word_text_exit,
                animation_word_text_exit_duration=subtitle_animation_word_text_exit_duration,
                animation_word_backdrop_entrance=subtitle_animation_word_backdrop_entrance,
                animation_word_backdrop_entrance_duration=subtitle_animation_word_backdrop_entrance_duration,
                animation_word_backdrop_emphasis=subtitle_animation_word_backdrop_emphasis,
                animation_word_backdrop_emphasis_duration=subtitle_animation_word_backdrop_emphasis_duration,
                animation_word_backdrop_exit=subtitle_animation_word_backdrop_exit,
                animation_word_backdrop_exit_duration=subtitle_animation_word_backdrop_exit_duration,
                animation_word_text_mode=subtitle_animation_word_text_mode,
                animation_word_backdrop_mode=subtitle_animation_word_backdrop_mode,
                animation_word_text_highlight_color=subtitle_animation_word_text_highlight_color,
                disable_cue_animations=subtitle_disable_cue_animations,
                disable_word_animations=subtitle_disable_word_animations,
            )
        ),
        block_chars=_integer(block_chars, "BLOCK_CHARS", 24000),
        block_overlap_chars=_integer(block_overlap_chars, "BLOCK_OVERLAP_CHARS", 4000),
        keep_intermediates=bool(keep_intermediates),
        force_recompute=bool(force_recompute),
        verbose=bool(verbose),
    )
    state = ctx.obj if isinstance(ctx.obj, _CliContext) else _CliContext()
    state.parsed_config = replace(config, output_options=_output_options(ctx))


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

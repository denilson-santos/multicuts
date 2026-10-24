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
from multicuts.app_config import AppConfig, RenderEncoding
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
from multicuts.output_config import (
    collect_output_values,
    load_output_config,
    load_output_environment,
    output_key,
    parse_boolean,
    parse_render,
    subtitle_key,
)
from multicuts.pipeline import RunOutcome, RunResult, run_pipeline
from multicuts.subtitles import SUBTITLE_BOOLEAN_FIELDS, SubtitleOptions
from multicuts.variants import VARIANTS, OutputOptions

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


def _capture_output_option(
    ctx: typer.Context, param: TyperOption, value: object
) -> None:
    if not value:
        return
    name = param.name
    if name is None or not isinstance(value, tuple):
        raise ConfigurationError("Output options require text values")
    captured = ctx.meta.setdefault("output_options", {})
    collect_output_values(name, value, captured, name="--" + name.replace("_", "-"))


class _OutputCommand(TyperCommand):
    """Accept grouped scoped values and normalize them to repeatable options."""

    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
        options = {
            flag: param
            for param in self.get_params(ctx)
            if isinstance(param, TyperOption)
            for flag in (*param.opts, *param.secondary_opts)
        }
        expanded: list[str] = []
        source_seen = False
        index = 0
        while index < len(args):
            token = args[index]
            if token == "--":
                expanded.extend(args[index:])
                break
            flag, separator, _ = token.partition("=")
            option = options.get(flag)
            expanded.append(token)
            index += 1
            if option is None:
                if not token.startswith("-"):
                    source_seen = True
                continue
            count = 0 if option.is_flag else option.nargs - bool(separator)
            expanded.extend(args[index : index + count])
            index += count
            if option.callback is not _capture_output_option:
                continue
            while index < len(args) and not args[index].startswith("-"):
                # Before SOURCE, only explicit assignments can be distinguished
                # from the positional video path. Use -- to end a value group.
                if not source_seen and "=" not in args[index]:
                    break
                expanded.extend((flag, args[index]))
                index += 1
        return super().parse_args(ctx, expanded)

    def __init__(self, name: str | None, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        controls = {
            "render": "true: all compatible outputs; false: none; "
            "primary: only the primary (all/short/long scopes). Default: true. "
            "Named variants accept true/false. Per source: "
            "TYPE:VARIANT > all:VARIANT > TYPE > all.",
            "primary": "auto (default): follow source orientation, "
            "or a preferred variant name. All, short, or long scopes only.",
            "width": "Positive even pixels (default: horizontal 1920, "
            "vertical/square 1080). If height is omitted, derive it from "
            "the default variant ratio and round to even pixels. "
            "With both dimensions, their ratio is used; preserve variant orientation.",
            "height": "Positive even pixels (default: vertical 1920, "
            "horizontal/square 1080). If width is omitted, derive it from "
            "the default variant ratio and round to even pixels. "
            "With both dimensions, their ratio is used; preserve variant orientation.",
        }
        subtitle_help = {
            "enabled": "Caption switch (default: true).",
            "template": "Template name (default: yellow-pop).",
            "template_dir": "Template directory (default: built-in templates).",
            "position": "Position: top/middle/bottom with left/center/right.",
            "anchor": "Subtitle-box anchor for custom x/y coordinates.",
            "font": "Font family name.",
            "font_weight": "Weight name or 100-900; cannot be combined with bold.",
            "fonts_dir": "Directory containing additional font files.",
            "text_case": "Text case: original, uppercase, or lowercase.",
            "line_height": "Line height: auto, %, or px.",
            "opacity": "Opacity: 0% through 100%.",
            "backdrop": "Cue backdrop: none, outline, or box.",
            "word_backdrop": "Timed word backdrop: none, outline, or box.",
        }
        for key in (
            *controls,
            "subtitle_enabled",
            "subtitle_template",
            "subtitle_template_dir",
            *("subtitle_" + field.name for field in fields(SubtitleOptions)),
        ):
            subtitle = key.startswith("subtitle_")
            field = key.removeprefix("subtitle_")
            boolean = field == "enabled" or field in SUBTITLE_BOOLEAN_FIELDS
            help_text = controls.get(
                key, subtitle_help.get(field, f"Subtitle {field.replace('_', ' ')}.")
            )
            if subtitle and boolean:
                help_text += " Value: true/false."
            elif field.endswith("_duration"):
                help_text += " Value: 10ms-5000ms or seconds, e.g. 0.15s."
            elif field.endswith("_color"):
                help_text += " Value: #RRGGBB or #RRGGBBAA."
            elif field.endswith(("_mode", "_entrance", "_emphasis", "_exit")):
                help_text += (
                    " Value: progressive or active-word."
                    if field.endswith("_mode")
                    else " Value: effect name; none disables this phase."
                )
            elif field in (
                "font_size",
                "letter_spacing",
                "margin_left",
                "margin_right",
                "margin_top",
                "margin_bottom",
                "max_width",
                "max_height",
                "position_x",
                "position_y",
                "backdrop_size",
                "word_backdrop_size",
                "shadow_size",
            ):
                help_text += " Value: % or px."
            if subtitle and field not in ("enabled", "template", "template_dir"):
                help_text += " Default: inherit selected template."
            self.params.append(
                TyperOption(
                    param_decls=["--" + key.replace("_", "-")],
                    type=str,
                    multiple=True,
                    default=(),
                    expose_value=False,
                    callback=_capture_output_option,
                    metavar="[SCOPE=]VALUE...",
                    help=help_text,
                    rich_help_panel=(
                        "Outputs"
                        if not subtitle
                        else "Subtitles"
                        if field in ("enabled", "template", "template_dir")
                        else "Subtitle presentation"
                    ),
                )
            )


def _output_settings(
    cli: dict[str, object], preset: dict[str, object]
) -> dict[str, object]:
    """Normalize output values once, resolving source before scope specificity."""
    process, dotenv = load_output_environment()

    def resolve(keys: tuple[str, ...]) -> tuple[str, object] | None:
        for source in (cli, process, dotenv, preset):
            for key in keys:
                if key in source:
                    return key, source[key]
        return None

    def value(field: str, scopes: tuple[str, ...], default: object = None) -> object:
        key_for = subtitle_key if field.startswith("subtitle_") else output_key
        field = field.removeprefix("subtitle_")
        found = resolve(tuple(key_for(scope, field) for scope in scopes))
        return default if found is None else found[1]

    def boolean(field: str, scopes: tuple[str, ...], default: bool) -> bool:
        return parse_boolean(value(field, scopes, default), field.upper())

    def presentation(scopes: tuple[str, ...]) -> SubtitleOptions:
        values: dict[str, object] = {}
        for field in fields(SubtitleOptions):
            raw = value("subtitle_" + field.name, scopes)
            if raw is not None:
                if field.name in SUBTITLE_BOOLEAN_FIELDS:
                    raw = parse_boolean(
                        raw, subtitle_key(scopes[0], field.name).upper()
                    )
                elif field.name == "fonts_dir":
                    raw = Path(str(raw)).expanduser()
                values[field.name] = raw
        return replace(SubtitleOptions(), **values)

    def directory(scopes: tuple[str, ...]) -> Path | None:
        raw = value("subtitle_template_dir", scopes)
        return None if raw is None else Path(str(raw)).expanduser()

    outputs: list[OutputOptions] = []
    result: dict[str, object] = {
        "render": parse_render(value("render", ("all",), True), "RENDER"),
        "subtitles_enabled": boolean("subtitle_enabled", ("all",), True),
        "subtitle_template": str(value("subtitle_template", ("all",), "yellow-pop")),
        "subtitle_template_dir": directory(("all",)),
        "subtitle_options": presentation(("all",)),
    }
    for clip_class in ("short", "long"):
        scopes = (clip_class, "all")
        result[f"{clip_class}_render"] = parse_render(
            value("render", scopes, True), f"RENDER_{clip_class.upper()}"
        )
        result[f"{clip_class}_subtitles_enabled"] = boolean(
            "subtitle_enabled", scopes, True
        )
        result[f"{clip_class}_primary"] = str(value("primary", scopes, "auto"))
        for variant in (None, *VARIANTS):
            scopes = (
                (clip_class, "all")
                if variant is None
                else (
                    f"{clip_class}:{variant}",
                    f"all:{variant}",
                    clip_class,
                    "all",
                )
            )
            enabled = None
            if variant is not None:
                keys = tuple(output_key(scope, "render") for scope in scopes)
                found = resolve(keys)
                if found is not None and found[0] in keys[:2]:
                    enabled = parse_boolean(found[1], found[0].upper())
            dimensions: dict[str, int | None] = {}
            for field in ("width", "height"):
                raw = value(field, scopes)
                try:
                    dimensions[field] = None if raw is None else int(str(raw))
                except ValueError as exc:
                    raise ConfigurationError(f"--{field} must be an integer") from exc
            template = value("subtitle_template", scopes)
            outputs.append(
                OutputOptions(
                    clip_class=clip_class,
                    variant=variant,
                    enabled=enabled,
                    subtitles_enabled=boolean("subtitle_enabled", scopes, True),
                    subtitle_template=None if template is None else str(template),
                    subtitle_template_dir=directory(scopes),
                    subtitle_options=presentation(scopes),
                    **dimensions,
                )
            )
    result["output_options"] = tuple(outputs)
    return result


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
    help=(
        "Find and render short and long clips. Output controls accept multiple "
        "space-separated values or repeated flags: [SCOPE=]VALUE... "
        "Omitted scope means all; use short, long, all:VARIANT, or TYPE:VARIANT "
        "for specific outputs. Boolean values are true/false. "
        "Matching environment variables accept the same values. "
        "Defaults shown apply when CLI, environment, .env, and JSON presets "
        "leave the setting unset."
    ),
    epilog=(
        "Examples: --render long=false short=primary "
        "publishes primary shorts. "
        "--subtitle-enabled false short:vertical=true captions "
        "only vertical shorts. "
        "--subtitle-margin-bottom all:vertical=8% adjusts verticals in both classes. "
        "Scopes: all, short, long, all:VARIANT, TYPE:VARIANT."
        " Output controls: [SCOPE=]VALUE...; omitted scope means all. "
        "Place SOURCE before grouped values, or use -- before a trailing SOURCE. "
        "Quote values containing spaces. "
        "VARIANT: horizontal, vertical, square, horizontal-blur, vertical-blur, "
        "square-blur."
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
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Optional JSON output/subtitle preset; "
            "CLI and environment override it (default: none).",
        ),
    ] = None,
    search_range: Annotated[
        tuple[str, str] | None,
        typer.Option(
            "--search-range",
            metavar="START END",
            help=(
                "Search only within these source times (seconds or HH:MM:SS). "
                "YouTube acquisition may include extra keyframe data. "
                "Default: no search restriction."
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
                "exact; YouTube cuts include the acquired keyframe padding. "
                "Default: unset."
            ),
            rich_help_panel="Clip selection",
        ),
    ] = None,
    clip_full: Annotated[
        bool,
        typer.Option(
            "--clip-full",
            help="Render the entire source as one cut without AI review "
            "(default: false).",
            rich_help_panel="Clip selection",
        ),
    ] = False,
    llm_backend: Annotated[
        str | None,
        typer.Option(
            "--llm-backend",
            help="openai, anthropic, gemini, codex, claude, or agy. "
            "Default: unset; required for automatic clip selection.",
            rich_help_panel="Analysis",
        ),
    ] = None,
    llm_model: Annotated[
        str | None,
        typer.Option(
            "--llm-model",
            help="Model identifier for the selected backend. "
            "Default: unset; required for automatic clip selection.",
            rich_help_panel="Analysis",
        ),
    ] = None,
    llm_effort: Annotated[
        str | None,
        typer.Option(
            "--llm-effort",
            help="Reasoning level (default: auto, using the provider default).",
            rich_help_panel="Analysis",
        ),
    ] = None,
    context: Annotated[
        str | None,
        typer.Option(
            "--context",
            help="Describe the video's subject and scope to guide clips "
            "(default: none).",
            rich_help_panel="Analysis",
        ),
    ] = None,
    lang: Annotated[
        str | None,
        typer.Option(
            "--lang",
            help="Transcription language code or auto (default: auto).",
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
            help="Same-class overlap suppression ratio (default: 0.60).",
            rich_help_panel="Clip selection",
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
    jobs: Annotated[
        int | None,
        typer.Option(
            "--jobs",
            help="Maximum simultaneous renders across cuts and variants (default: 1).",
            rich_help_panel="Execution",
        ),
    ] = None,
    video_encoder: Annotated[
        str | None,
        typer.Option(
            "--video-encoder",
            help="libx264 or h264_nvenc "
            "(default: FFmpeg selection, matching multisubs).",
            rich_help_panel="Video encoding",
        ),
    ] = None,
    video_preset: Annotated[
        str | None,
        typer.Option(
            "--video-preset",
            help="Requires --video-encoder. Default: medium (libx264), "
            "p4 (h264_nvenc); omitted encoder: FFmpeg default.",
            rich_help_panel="Video encoding",
        ),
    ] = None,
    video_quality: Annotated[
        int | None,
        typer.Option(
            "--video-quality",
            help="Quality from 0 through 51; requires --video-encoder. "
            "Default: CRF 23 (libx264), CQ 28 (h264_nvenc); "
            "omitted encoder: FFmpeg default.",
            rich_help_panel="Video encoding",
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
            help="Show debug details and dependency output "
            "(default: quiet, showing normal progress).",
            rich_help_panel="Execution",
        ),
    ] = None,
) -> None:
    preset = load_output_config(config_file)
    output_settings = _output_settings(ctx.meta.get("output_options", {}), preset)
    direct = clip_range is not None or clip_full
    backend = _value(llm_backend, "LLM_BACKEND", "")
    llm_model_value = _value(llm_model, "LLM_MODEL", "")
    use_ai = not direct or bool(backend or llm_model_value)
    if not isinstance(backend, str) or (use_ai and not backend.strip()):
        raise ConfigurationError("Set LLM_BACKEND or pass --llm-backend")
    if not isinstance(llm_model_value, str) or (use_ai and not llm_model_value.strip()):
        raise ConfigurationError("Set LLM_MODEL or pass --llm-model")
    effort_value = _value(llm_effort, "LLM_EFFORT", None)
    if effort_value is not None and not isinstance(effort_value, str):
        raise ConfigurationError("LLM_EFFORT must be a string")
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
        block_chars=_integer(block_chars, "BLOCK_CHARS", 24000),
        block_overlap_chars=_integer(block_overlap_chars, "BLOCK_OVERLAP_CHARS", 4000),
        render_encoding=RenderEncoding(
            encoder=str(_value(video_encoder, "VIDEO_ENCODER", "")) or None,
            preset=str(_value(video_preset, "VIDEO_PRESET", "")) or None,
            quality=(
                _integer(video_quality, "VIDEO_QUALITY", 0)
                if _value(video_quality, "VIDEO_QUALITY", None) is not None
                else None
            ),
        ),
        render_jobs=_integer(jobs, "JOBS", 1),
        keep_intermediates=bool(keep_intermediates),
        force_recompute=bool(force_recompute),
        verbose=bool(verbose),
    )
    state = ctx.obj if isinstance(ctx.obj, _CliContext) else _CliContext()
    state.parsed_config = replace(config, **output_settings)


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
            f"clips={len(result.clip_paths)}; manifest={result.manifest_path}; "
            f"report={result.report_path}"
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

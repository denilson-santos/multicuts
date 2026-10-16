"""Validated options for the semantic short and long clip pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path

from multicuts.errors import ConfigurationError
from multicuts.models import MediaInfo, TimeRange
from multicuts.subtitles import SubtitleOptions
from multicuts.variants import VARIANTS, OutputOptions, aspect_ratio, available_variants

LLM_BACKENDS = frozenset({"openai", "anthropic", "gemini", "codex", "claude", "agy"})
ASR_BACKENDS = frozenset({"whisperx", "faster-whisper", "parakeet", "qwen"})
LLM_EFFORT_LEVELS = {
    "openai": frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max"}),
    "anthropic": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "gemini": frozenset({"minimal", "low", "medium", "high"}),
    "codex": frozenset({"low", "medium", "high", "xhigh", "max", "ultra"}),
    "claude": frozenset({"low", "medium", "high", "xhigh", "max"}),
    "agy": frozenset({"low", "medium", "high", "max"}),
}


@dataclass(frozen=True, slots=True)
class AppConfig:
    source: str
    output_dir: Path
    llm_backend: str = ""
    llm_model: str = ""
    overlap_threshold: float = 0.60
    language: str | None = None
    transcription_model: str = "turbo"
    short_primary: str = "vertical"
    long_primary: str = "horizontal"
    vertical_width: int = 1080
    vertical_height: int = 1920
    horizontal_width: int = 1920
    horizontal_height: int = 1080
    subtitles_enabled: bool = True
    subtitle_template: str = "yellow-pop"
    subtitle_template_dir: Path | None = None
    block_chars: int = 24000
    block_overlap_chars: int = 4000
    keep_intermediates: bool = False
    force_recompute: bool = False
    verbose: bool = False
    llm_effort: str | None = None
    editorial_context: str | None = None
    asr_backend: str = "whisperx"
    render_variants: bool = True
    square_size: int = 1080
    short_subtitles_enabled: bool | None = None
    long_subtitles_enabled: bool | None = None
    short_clips_enabled: bool = True
    long_clips_enabled: bool = True
    short_variants_enabled: bool | None = None
    long_variants_enabled: bool | None = None
    search_range: TimeRange | None = None
    clip_range: TimeRange | None = None
    full_video: bool = False
    subtitle_options: SubtitleOptions = SubtitleOptions()
    output_options: tuple[OutputOptions, ...] = ()
    render_variant: str | None = None

    def __post_init__(self) -> None:
        if self.render_variant is not None and self.render_variant not in VARIANTS:
            raise ConfigurationError("Unknown output variant")
        if not isinstance(self.output_options, tuple) or any(
            not isinstance(option, OutputOptions) for option in self.output_options
        ):
            raise ConfigurationError("Output options must be a tuple of OutputOptions")
        keys = [(option.clip_class, option.variant) for option in self.output_options]
        if len(keys) != len(set(keys)):
            raise ConfigurationError("Duplicate output options")
        if not isinstance(self.subtitle_options, SubtitleOptions):
            raise ConfigurationError("Subtitle options must use SubtitleOptions")
        for name in ("search_range", "clip_range"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, TimeRange):
                raise ConfigurationError(
                    f"--{name.replace('_', '-')} must be a time range"
                )
        if type(self.full_video) is not bool:
            raise ConfigurationError("--clip-full must be boolean")
        modes = (
            self.search_range is not None,
            self.clip_range is not None,
            self.full_video,
        )
        if sum(modes) > 1:
            raise ConfigurationError(
                "Choose only one of --search-range, --clip-range, or --clip-full"
            )
        if not isinstance(self.source, str) or not self.source.strip():
            raise ConfigurationError("source must not be empty")
        if not self.direct_clip and self.llm_backend not in LLM_BACKENDS:
            raise ConfigurationError(
                "LLM_BACKEND must be openai, anthropic, gemini, codex, claude, or agy"
            )
        if not self.direct_clip and (
            not isinstance(self.llm_model, str) or not self.llm_model.strip()
        ):
            raise ConfigurationError("LLM_MODEL must not be empty")
        if self.asr_backend not in ASR_BACKENDS:
            raise ConfigurationError(
                "ASR_BACKEND must be whisperx, faster-whisper, parakeet, or qwen"
            )
        if self.editorial_context is not None:
            if not isinstance(self.editorial_context, str):
                raise ConfigurationError("--context must be text")
            object.__setattr__(
                self, "editorial_context", self.editorial_context.strip() or None
            )
        if not self.direct_clip and self.llm_effort is not None:
            if not isinstance(self.llm_effort, str) or not self.llm_effort.strip():
                raise ConfigurationError("LLM_EFFORT must be a supported effort level")
            effort = self.llm_effort.strip().lower()
            if effort == "auto":
                object.__setattr__(self, "llm_effort", None)
            elif effort not in LLM_EFFORT_LEVELS[self.llm_backend]:
                allowed = ", ".join(sorted(LLM_EFFORT_LEVELS[self.llm_backend]))
                raise ConfigurationError(
                    f"LLM_EFFORT for {self.llm_backend} must be one of: {allowed}"
                )
            else:
                object.__setattr__(self, "llm_effort", effort)
        if (
            not self.direct_clip
            and self.llm_backend == "gemini"
            and self.llm_effort is not None
            and self.llm_model.startswith("gemini-2.5-")
        ):
            raise ConfigurationError(
                "Gemini 2.5 uses a thinking budget; omit LLM_EFFORT or choose Gemini 3"
            )
        if (
            isinstance(self.overlap_threshold, bool)
            or not isinstance(self.overlap_threshold, (int, float))
            or not isfinite(self.overlap_threshold)
            or not 0 < self.overlap_threshold <= 1
        ):
            raise ConfigurationError(
                "OVERLAP_THRESHOLD must be a ratio above 0 and at most 1"
            )
        if not isinstance(self.output_dir, Path):
            raise ConfigurationError("--output-dir must be a path")
        if self.language is not None:
            if not self.language.strip():
                raise ConfigurationError("--lang must be a language code or auto")
            if self.language.casefold() == "auto":
                object.__setattr__(self, "language", None)
        if not self.transcription_model.strip() or not self.subtitle_template.strip():
            raise ConfigurationError(
                "Transcription model and subtitle template must not be empty"
            )
        for name in ("short_primary", "long_primary"):
            if getattr(self, name) not in VARIANTS:
                raise ConfigurationError(f"{name} must name an output variant")
        if (
            type(self.vertical_width) is not int
            or type(self.vertical_height) is not int
            or self.vertical_width <= 0
            or self.vertical_height <= 0
            or self.vertical_width % 2
            or self.vertical_height % 2
            or self.vertical_width >= self.vertical_height
        ):
            raise ConfigurationError(
                "Vertical dimensions must be positive, even, and taller than wide"
            )
        if (
            type(self.horizontal_width) is not int
            or type(self.horizontal_height) is not int
            or self.horizontal_width <= 0
            or self.horizontal_height <= 0
            or self.horizontal_width % 2
            or self.horizontal_height % 2
            or self.horizontal_width <= self.horizontal_height
        ):
            raise ConfigurationError(
                "Horizontal dimensions must be positive, even, and wider than tall"
            )
        if type(self.block_chars) is not int or self.block_chars < 1000:
            raise ConfigurationError("BLOCK_CHARS must be at least 1000")
        if (
            type(self.square_size) is not int
            or self.square_size <= 0
            or self.square_size % 2
        ):
            raise ConfigurationError("Square size must be a positive, even integer")
        if (
            type(self.block_overlap_chars) is not int
            or not 0 <= self.block_overlap_chars < self.block_chars
        ):
            raise ConfigurationError("BLOCK_OVERLAP_CHARS must be below BLOCK_CHARS")
        if (
            self.subtitle_template_dir is not None
            and not self.subtitle_template_dir.is_dir()
        ):
            raise ConfigurationError(
                "SUBTITLE_TEMPLATE_DIR must be an existing directory"
            )
        for name in (
            "subtitles_enabled",
            "keep_intermediates",
            "force_recompute",
            "verbose",
            "render_variants",
            "short_clips_enabled",
            "long_clips_enabled",
        ):
            if type(getattr(self, name)) is not bool:
                raise ConfigurationError(f"{name} must be boolean")
        if not self.short_clips_enabled and not self.long_clips_enabled:
            raise ConfigurationError("Enable at least one clip class: short or long")
        for name in (
            "short_subtitles_enabled",
            "long_subtitles_enabled",
            "short_variants_enabled",
            "long_variants_enabled",
        ):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ConfigurationError(f"{name} must be boolean or unset")

    def clips_for(self, clip_class: str) -> bool:
        """Return whether a class and all its output versions are enabled."""
        if clip_class not in ("short", "long"):
            raise ConfigurationError("Clip class must be short or long")
        return (
            self.short_clips_enabled
            if clip_class == "short"
            else self.long_clips_enabled
        )

    @property
    def direct_clip(self) -> bool:
        """Whether the user chose the interval instead of automatic discovery."""
        return self.clip_range is not None or self.full_video

    @property
    def selection_mode(self) -> str:
        if self.full_video:
            return "full_video"
        return "custom" if self.clip_range is not None else "automatic"

    def variants_for(self, clip_class: str) -> bool:
        """Inherit the shared variant switch unless the class overrides it."""
        if not self.clips_for(clip_class):
            return False
        override = (
            self.short_variants_enabled
            if clip_class == "short"
            else self.long_variants_enabled
        )
        return self.render_variants if override is None else override

    def subtitles_for(self, clip_class: str) -> bool:
        """Read the caption decision for the current effective render config."""
        if clip_class not in ("short", "long"):
            raise ConfigurationError("Subtitle class must be short or long")
        override = (
            self.short_subtitles_enabled
            if clip_class == "short"
            else self.long_subtitles_enabled
        )
        return self.subtitles_enabled if override is None else override

    def outputs_for(self, clip_class: str, media: MediaInfo) -> tuple[str, ...]:
        """Select and validate supported outputs before transcription."""
        if not self.clips_for(clip_class):
            return ()
        available = available_variants(media)
        primary = self.primary_for(clip_class)
        if primary not in available:
            primary = available[0]
        overrides = {
            option.variant: option.enabled
            for option in self.output_options
            if option.clip_class == clip_class and option.variant is not None
        }
        for name, enabled in overrides.items():
            if enabled and name not in available:
                raise ConfigurationError(
                    f"{clip_class}-{name} is unavailable for this source orientation"
                )
        outputs = tuple(
            name
            for name in dict.fromkeys((primary, *available))
            if (
                overrides.get(name)
                if overrides.get(name) is not None
                else name == primary or self.variants_for(clip_class)
            )
        )
        if not outputs:
            raise ConfigurationError(f"Enable at least one {clip_class} output variant")
        for name in outputs:
            self.for_output(clip_class, name)
        return outputs

    def primary_for(self, clip_class: str) -> str:
        if clip_class not in ("short", "long"):
            raise ConfigurationError("Clip class must be short or long")
        return self.short_primary if clip_class == "short" else self.long_primary

    def dimensions_for(self, clip_class: str, variant: str) -> tuple[int, int]:
        """Merge dimensions per field; derive a missing side from the default canvas."""
        self.primary_for(clip_class)
        if variant not in VARIANTS:
            raise ConfigurationError("Unknown output variant")
        orientation = variant.removesuffix("-blur")
        if orientation == "horizontal":
            default_width, default_height = (
                self.horizontal_width,
                self.horizontal_height,
            )
        elif orientation == "vertical":
            default_width, default_height = self.vertical_width, self.vertical_height
        else:
            default_width = default_height = self.square_size
        width = height = None
        for scope in (None, variant):
            for option in self.output_options:
                if option.clip_class == clip_class and option.variant == scope:
                    if option.width is not None:
                        width = option.width
                    if option.height is not None:
                        height = option.height
        if width is None and height is None:
            width, height = default_width, default_height
        elif width is None:
            assert height is not None
            width = max(
                2,
                2 * ((height * default_width + default_height) // (2 * default_height)),
            )
        elif height is None:
            height = max(
                2, 2 * ((width * default_height + default_width) // (2 * default_width))
            )
        if (
            (orientation == "horizontal" and width <= height)
            or (orientation == "vertical" and width >= height)
            or (orientation == "square" and width != height)
        ):
            raise ConfigurationError(
                f"{clip_class}:{variant} dimensions must be {orientation} "
                "(horizontal: width > height; vertical: height > width; "
                "square: equal sides)"
            )
        return width, height

    def aspect_ratio_for(self, clip_class: str, variant: str) -> str:
        return aspect_ratio(*self.dimensions_for(clip_class, variant))

    def for_output(self, clip_class: str, variant: str) -> AppConfig:
        """Resolve captions and presentation before entering the render boundary."""
        enabled = self.subtitles_for(clip_class)
        template, template_dir = self.subtitle_template, self.subtitle_template_dir
        options = self.subtitle_options
        self.dimensions_for(clip_class, variant)
        for scope in (None, variant):
            override = next(
                (
                    item
                    for item in self.output_options
                    if item.clip_class == clip_class and item.variant == scope
                ),
                None,
            )
            if override is None:
                continue
            if override.subtitles_enabled is not None:
                enabled = override.subtitles_enabled
            if override.subtitle_template is not None:
                template = override.subtitle_template
            if override.subtitle_template_dir is not None:
                template_dir = override.subtitle_template_dir
            options = replace(options, **override.subtitle_options.overrides())
        return replace(
            self,
            **{
                f"{clip_class}_subtitles_enabled": enabled,
            },
            subtitle_template=template,
            subtitle_template_dir=template_dir,
            subtitle_options=options,
            render_variant=variant,
        )

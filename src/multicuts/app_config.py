"""Validated options for the semantic short and long clip pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from multicuts.errors import ConfigurationError

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
    llm_backend: str
    llm_model: str
    overlap_threshold: float = 0.60
    language: str | None = None
    transcription_model: str = "turbo"
    short_aspect_ratio: str = "9:16"
    long_aspect_ratio: str = "16:9"
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

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ConfigurationError("source must not be empty")
        if self.llm_backend not in LLM_BACKENDS:
            raise ConfigurationError(
                "LLM_BACKEND must be openai, anthropic, gemini, codex, claude, or agy"
            )
        if not isinstance(self.llm_model, str) or not self.llm_model.strip():
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
        if self.llm_effort is not None:
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
            self.llm_backend == "gemini"
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
        for name in ("short_aspect_ratio", "long_aspect_ratio"):
            if getattr(self, name) not in ("original", "9:16", "16:9", "1:1"):
                raise ConfigurationError(f"{name} must be original, 9:16, 16:9, or 1:1")
        if (
            type(self.vertical_width) is not int
            or type(self.vertical_height) is not int
            or self.vertical_width <= 0
            or self.vertical_height <= 0
            or self.vertical_width % 2
            or self.vertical_height % 2
            or self.vertical_width * 16 != self.vertical_height * 9
        ):
            raise ConfigurationError(
                "Vertical dimensions must be positive, even, and 9:16"
            )
        if (
            type(self.horizontal_width) is not int
            or type(self.horizontal_height) is not int
            or self.horizontal_width <= 0
            or self.horizontal_height <= 0
            or self.horizontal_width % 2
            or self.horizontal_height % 2
            or self.horizontal_width * 9 != self.horizontal_height * 16
        ):
            raise ConfigurationError(
                "Horizontal dimensions must be positive, even, and 16:9"
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
        ):
            if type(getattr(self, name)) is not bool:
                raise ConfigurationError(f"{name} must be boolean")
        for name in ("short_subtitles_enabled", "long_subtitles_enabled"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ConfigurationError(f"{name} must be boolean or unset")

    def subtitles_for(self, clip_class: str) -> bool:
        """Use a class override when set, otherwise inherit the general setting."""
        if clip_class not in ("short", "long"):
            raise ConfigurationError("Subtitle class must be short or long")
        override = (
            self.short_subtitles_enabled
            if clip_class == "short"
            else self.long_subtitles_enabled
        )
        return self.subtitles_enabled if override is None else override

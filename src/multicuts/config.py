"""Validated, provider-independent configuration for one CLI run."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from multicuts.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class RunConfig:
    """One run's normalized options; ``None`` language requests auto-detection."""

    source: str
    output_dir: Path
    clips: int
    min_score: int
    aspect_ratio: str
    subtitle_template: str
    scorer: str
    model: str
    language: str | None = None
    min_duration: float = 15.0
    max_duration: float = 60.0
    candidate_budget: int = 50
    overlap_threshold: float = 0.60
    text_similarity_threshold: float = 0.90
    refinement_pre_roll: float = 0.15
    refinement_post_roll: float = 0.25
    refinement_search_radius: float = 0.5
    refinement_pause_threshold: float = 0.4
    semantic_provider: str = "openai"
    semantic_model: str = "gpt-6-luna"
    semantic_reasoning_effort: str = "max"
    semantic_fallback: str = "heuristic"
    subtitle_template_dir: Path | None = None
    keep_intermediates: bool = False
    force_recompute: bool = False
    verbose: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "source",
            "subtitle_template",
            "scorer",
            "model",
            "semantic_provider",
            "semantic_model",
            "semantic_reasoning_effort",
            "semantic_fallback",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigurationError(f"{field_name} must not be empty")

        if not isinstance(self.output_dir, Path):
            raise ConfigurationError("output_dir must be a path")
        if (
            not isinstance(self.clips, int)
            or isinstance(self.clips, bool)
            or self.clips <= 0
        ):
            raise ConfigurationError("clips must be a positive integer")
        if (
            not isinstance(self.min_score, int)
            or isinstance(self.min_score, bool)
            or not 0 <= self.min_score <= 100
        ):
            raise ConfigurationError("min_score must be an integer from 0 to 100")
        if self.aspect_ratio not in ("original", "9:16"):
            raise ConfigurationError("aspect_ratio must be 'original' or '9:16'")
        if self.scorer not in ("heuristic", "hybrid"):
            raise ConfigurationError("scorer must be 'heuristic' or 'hybrid'")
        if self.semantic_provider != "openai":
            raise ConfigurationError("semantic_provider must be 'openai'")
        if self.semantic_reasoning_effort not in (
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ):
            raise ConfigurationError("semantic_reasoning_effort is unsupported")
        if self.semantic_fallback not in ("heuristic", "none"):
            raise ConfigurationError("semantic_fallback must be 'heuristic' or 'none'")

        for field_name in ("min_duration", "max_duration"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(value)
                or value <= 0
            ):
                raise ConfigurationError(f"{field_name} must be finite and positive")
        if self.min_duration > self.max_duration:
            raise ConfigurationError("min_duration must not exceed max_duration")
        if type(self.candidate_budget) is not int or self.candidate_budget <= 0:
            raise ConfigurationError("candidate_budget must be a positive integer")
        for field_name in ("overlap_threshold", "text_similarity_threshold"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or not 0.0 <= value <= 1.0
            ):
                raise ConfigurationError(
                    f"{field_name} must be a finite ratio from 0 to 1"
                )

        for field_name in (
            "refinement_pre_roll",
            "refinement_post_roll",
            "refinement_search_radius",
            "refinement_pause_threshold",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ConfigurationError(
                    f"{field_name} must be finite and non-negative"
                )
        if self.refinement_search_radius <= 0 or self.refinement_pause_threshold <= 0:
            raise ConfigurationError(
                "refinement search and pause thresholds must be positive"
            )

        if self.language is not None:
            if not isinstance(self.language, str) or not self.language.strip():
                raise ConfigurationError("language must be a code or 'auto'")
            if self.language.casefold() == "auto":
                object.__setattr__(self, "language", None)

        if self.subtitle_template_dir is not None:
            if not isinstance(self.subtitle_template_dir, Path) or not (
                self.subtitle_template_dir.is_dir()
            ):
                raise ConfigurationError(
                    "subtitle_template_dir must be an existing directory"
                )

"""Source-aware output variants shared by short and long cuts."""

from dataclasses import dataclass
from math import gcd
from pathlib import Path

from multicuts.errors import ConfigurationError
from multicuts.models import MediaInfo
from multicuts.subtitles import SubtitleOptions

VARIANTS = (
    "horizontal",
    "vertical",
    "square",
    "horizontal-blur",
    "vertical-blur",
    "square-blur",
)


def aspect_ratio(width: int, height: int) -> str:
    """Report the exact ratio of a final pixel canvas."""
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def available_variants(media: MediaInfo) -> tuple[str, ...]:
    """Use presentation dimensions, including rotation and pixel aspect ratio."""
    width, height = media.presentation_width, media.presentation_height
    if width > height:
        return VARIANTS
    if width < height:
        return "vertical", "square", "horizontal-blur", "square-blur"
    return "horizontal", "vertical", "square", "horizontal-blur", "vertical-blur"


@dataclass(frozen=True, slots=True)
class OutputOptions:
    """Sparse class or named-variant overrides; None inherits its parent."""

    clip_class: str
    variant: str | None = None
    enabled: bool | None = None
    subtitles_enabled: bool | None = None
    subtitle_template: str | None = None
    subtitle_template_dir: Path | None = None
    subtitle_options: SubtitleOptions = SubtitleOptions()
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if self.clip_class not in ("short", "long"):
            raise ConfigurationError("Output class must be short or long")
        if self.variant is not None and self.variant not in VARIANTS:
            raise ConfigurationError("Unknown output variant")
        for name in ("enabled", "subtitles_enabled"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ConfigurationError(f"Output {name} must be boolean or unset")
        for name in ("width", "height"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not int or value <= 0 or value % 2
            ):
                raise ConfigurationError(f"Output {name} must be positive even pixels")
        if self.subtitle_template is not None and (
            not isinstance(self.subtitle_template, str)
            or not self.subtitle_template.strip()
        ):
            raise ConfigurationError("Output subtitle template must not be empty")
        if self.subtitle_template_dir is not None and (
            not isinstance(self.subtitle_template_dir, Path)
            or not self.subtitle_template_dir.is_dir()
        ):
            raise ConfigurationError("Output subtitle template directory must exist")
        if not isinstance(self.subtitle_options, SubtitleOptions):
            raise ConfigurationError("Output subtitle options must use SubtitleOptions")

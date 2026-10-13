"""Project-owned, sparse subtitle presentation settings."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

from multicuts.errors import ConfigurationError

SUBTITLE_BOOLEAN_FIELDS = frozenset(
    {"bold", "italic", "disable_cue_animations", "disable_word_animations"}
)


@dataclass(frozen=True, slots=True)
class SubtitleOptions:
    """Unset fields inherit the template; units resolve against final geometry."""

    position: str | None = None
    margin_left: str | None = None
    margin_right: str | None = None
    margin_top: str | None = None
    margin_bottom: str | None = None
    max_width: str | None = None
    max_height: str | None = None
    position_x: str | None = None
    position_y: str | None = None
    anchor: str | None = None
    font: str | None = None
    font_weight: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    text_case: str | None = None
    fonts_dir: Path | None = None
    font_size: str | None = None
    letter_spacing: str | None = None
    line_height: str | None = None
    text_color: str | None = None
    backdrop: str | None = None
    backdrop_color: str | None = None
    word_backdrop: str | None = None
    word_backdrop_color: str | None = None
    opacity: str | None = None
    backdrop_size: str | None = None
    word_backdrop_size: str | None = None
    shadow_size: str | None = None
    animation_cue_text_entrance: str | None = None
    animation_cue_text_entrance_duration: str | None = None
    animation_cue_text_emphasis: str | None = None
    animation_cue_text_emphasis_duration: str | None = None
    animation_cue_text_exit: str | None = None
    animation_cue_text_exit_duration: str | None = None
    animation_cue_backdrop_entrance: str | None = None
    animation_cue_backdrop_entrance_duration: str | None = None
    animation_cue_backdrop_emphasis: str | None = None
    animation_cue_backdrop_emphasis_duration: str | None = None
    animation_cue_backdrop_exit: str | None = None
    animation_cue_backdrop_exit_duration: str | None = None
    animation_word_text_entrance: str | None = None
    animation_word_text_entrance_duration: str | None = None
    animation_word_text_emphasis: str | None = None
    animation_word_text_emphasis_duration: str | None = None
    animation_word_text_exit: str | None = None
    animation_word_text_exit_duration: str | None = None
    animation_word_backdrop_entrance: str | None = None
    animation_word_backdrop_entrance_duration: str | None = None
    animation_word_backdrop_emphasis: str | None = None
    animation_word_backdrop_emphasis_duration: str | None = None
    animation_word_backdrop_exit: str | None = None
    animation_word_backdrop_exit_duration: str | None = None
    animation_word_text_mode: str | None = None
    animation_word_backdrop_mode: str | None = None
    animation_word_text_highlight_color: str | None = None
    disable_cue_animations: bool | None = None
    disable_word_animations: bool | None = None

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if value is None:
                continue
            if field.name in SUBTITLE_BOOLEAN_FIELDS:
                valid = type(value) is bool
            elif field.name == "fonts_dir":
                valid = isinstance(value, Path)
            else:
                valid = isinstance(value, str) and bool(value.strip())
            if not valid:
                raise ConfigurationError(
                    f"Invalid subtitle setting: {field.name.replace('_', '-')}"
                )

    def overrides(self) -> dict[str, object]:
        """Supply only explicit settings at the provider boundary."""
        return {
            field.name: value
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        }

    def metadata(self) -> dict[str, object]:
        """Preserve supplied presentation values without local font paths."""
        values = self.overrides()
        if "fonts_dir" in values:
            del values["fonts_dir"]
            values["custom_fonts"] = True
        return values

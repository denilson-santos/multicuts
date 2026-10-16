"""Parse scoped output controls and optional JSON presentation presets."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from multicuts.errors import ConfigurationError
from multicuts.subtitles import SUBTITLE_BOOLEAN_FIELDS, SubtitleOptions
from multicuts.variants import VARIANTS

SUBTITLE_FIELDS = frozenset(
    {
        "enabled",
        "template",
        "template_dir",
        *(field.name for field in fields(SubtitleOptions)),
    }
)
OUTPUT_FIELDS = frozenset({"render", "variants", "primary", "width", "height"})


def output_scope(scope: str) -> str:
    """Normalize all, TYPE, or TYPE:VARIANT into a configuration key suffix."""
    if scope == "all":
        return ""
    clip_class, separator, variant = scope.partition(":")
    if clip_class not in ("short", "long") or (separator and variant not in VARIANTS):
        raise ConfigurationError(
            "Output scope must be all, short, long, or TYPE:VARIANT "
            "(horizontal, vertical, square, horizontal-blur, "
            "vertical-blur, square-blur)"
        )
    return clip_class + ("_" + variant.replace("-", "_") if separator else "")


def subtitle_key(scope: str, field: str) -> str:
    suffix = output_scope(scope)
    return "subtitle_" + (suffix + "_" if suffix else "") + field


def output_key(scope: str, field: str) -> str:
    suffix = output_scope(scope)
    if field in ("variants", "primary") and ":" in scope:
        raise ConfigurationError(
            f"--{field.replace('_', '-')} scopes must be all, short, or long"
        )
    return field + ("_" + suffix if suffix else "")


def scoped_value(value: str) -> tuple[str, str]:
    scope, separator, raw = value.partition("=")
    if not separator:
        scope, raw = "all", value
    scope, raw = scope.strip(), raw.strip()
    output_scope(scope)
    if not raw:
        raise ConfigurationError("Output values must not be empty; use [SCOPE=]VALUE")
    return scope, raw


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError("Duplicate key in output configuration")
        result[key] = value
    return result


def load_output_config(path: Path | None) -> dict[str, object]:
    """Read only output settings; source, credentials, and run controls stay outside."""
    if path is None:
        return {}
    path = path.expanduser()
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigurationError(
            "Could not read --config as a UTF-8 JSON object"
        ) from exc
    if not isinstance(data, dict) or data.keys() - (OUTPUT_FIELDS | {"subtitles"}):
        raise ConfigurationError(
            "--config accepts only render, variants, primary, width, height, "
            "and subtitles objects"
        )
    result: dict[str, object] = {}
    for group, settings in data.items():
        if not isinstance(settings, dict):
            raise ConfigurationError(f"--config {group} must be an object")
        for scope, value in settings.items():
            if group == "subtitles":
                output_scope(scope)
                if not isinstance(value, dict) or value.keys() - SUBTITLE_FIELDS:
                    raise ConfigurationError(
                        "Unknown field or invalid object in --config subtitles"
                    )
                for field, raw in value.items():
                    if field == "enabled" or field in SUBTITLE_BOOLEAN_FIELDS:
                        valid = type(raw) is bool
                    else:
                        valid = isinstance(raw, str) and bool(raw.strip())
                    if not valid:
                        raise ConfigurationError(
                            f"Invalid --config subtitle field: {field}"
                        )
                    if field in ("fonts_dir", "template_dir"):
                        directory = Path(str(raw)).expanduser()
                        raw = (
                            directory
                            if directory.is_absolute()
                            else path.resolve().parent / directory
                        )
                    result[subtitle_key(scope, field)] = raw
            else:
                key = output_key(scope, group)
                if group in ("render", "variants"):
                    valid = type(value) is bool
                elif group in ("width", "height"):
                    valid = type(value) is int and value > 0 and value % 2 == 0
                else:
                    valid = value in VARIANTS
                if not valid:
                    raise ConfigurationError(f"Invalid --config {group} value")
                result[key] = value
    return result

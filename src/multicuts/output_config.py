"""Parse scoped output controls and optional JSON presentation presets."""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import fields
from pathlib import Path

from multicuts.errors import ConfigurationError
from multicuts.subtitles import SUBTITLE_BOOLEAN_FIELDS, SubtitleOptions
from multicuts.variants import VARIANTS, RenderMode

SUBTITLE_FIELDS = frozenset(
    {
        "enabled",
        "template",
        "template_dir",
        *(field.name for field in fields(SubtitleOptions)),
    }
)
OUTPUT_FIELDS = frozenset({"render", "primary", "width", "height"})
ENVIRONMENT_FIELDS = OUTPUT_FIELDS | {"subtitle_" + field for field in SUBTITLE_FIELDS}


def parse_boolean(raw: object, name: str) -> bool:
    if type(raw) is bool:
        return raw
    if isinstance(raw, str):
        if raw.casefold() in ("true", "yes", "1", "on"):
            return True
        if raw.casefold() in ("false", "no", "0", "off"):
            return False
    raise ConfigurationError(f"{name} must be a boolean")


def parse_render(raw: object, name: str, *, named: bool = False) -> RenderMode:
    if isinstance(raw, str) and raw.strip().casefold() == "primary":
        if named:
            raise ConfigurationError(
                f"{name}: primary is allowed only at all, short, or long scope"
            )
        return "primary"
    try:
        return parse_boolean(raw, name)
    except ConfigurationError as exc:
        raise ConfigurationError(f"{name} must be true, false, or primary") from exc


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
    if field == "primary" and ":" in scope:
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


def collect_output_values(
    field: str, values: Sequence[str], destination: dict[str, object], *, name: str
) -> None:
    """Use the same scope and conflict rules for CLI and environment values."""
    for raw in values:
        scope, supplied = scoped_value(raw)
        if field.startswith("subtitle_"):
            subtitle_field = field.removeprefix("subtitle_")
            key = subtitle_key(scope, subtitle_field)
            boolean = (
                subtitle_field == "enabled" or subtitle_field in SUBTITLE_BOOLEAN_FIELDS
            )
        else:
            key = output_key(scope, field)
            boolean = False
        normalized: object = supplied
        if field == "render":
            normalized = parse_render(supplied, name, named=":" in scope)
        elif boolean:
            normalized = parse_boolean(supplied, name)
        if key in destination and destination[key] != normalized:
            raise ConfigurationError(f"Conflicting values for {name} at scope {scope}")
        destination[key] = normalized


def environment_output_config(values: Mapping[str, str]) -> dict[str, object]:
    """Read one variable per scoped option; quoting is literal and never executed."""
    result: dict[str, object] = {}
    for field in sorted(ENVIRONMENT_FIELDS):
        name = field.upper()
        raw = values.get(name)
        if raw is None or not raw.strip():
            continue
        try:
            tokens = shlex.split(raw, comments=False)
        except ValueError as exc:
            raise ConfigurationError(f"Invalid quoting in {name}") from exc
        collect_output_values(field, tokens, result, name=name)
    return result


def load_output_environment() -> tuple[dict[str, object], dict[str, object]]:
    """Keep process and dotenv scopes separate so source priority comes first."""
    try:
        lines = (Path.cwd() / ".env").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError("Could not read .env as UTF-8 text") from exc
    dotenv: dict[str, str] = {}
    names = {field.upper() for field in ENVIRONMENT_FIELDS}
    for line in lines:
        name, separator, raw = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        if not separator or name not in names:
            continue
        if name in dotenv:
            raise ConfigurationError(f"Duplicate output variable in .env: {name}")
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            try:
                unquoted = shlex.split(raw, comments=False)
            except ValueError as exc:
                raise ConfigurationError(f"Invalid quoting in {name}") from exc
            if len(unquoted) == 1:
                raw = unquoted[0]
        dotenv[name] = raw
    return environment_output_config(os.environ), environment_output_config(dotenv)


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
            "--config accepts only render, primary, width, height, "
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
                if group == "render":
                    valid = type(value) is bool or (
                        ":" not in scope and value == "primary"
                    )
                elif group in ("width", "height"):
                    valid = type(value) is int and value > 0 and value % 2 == 0
                else:
                    valid = value in ("auto", *VARIANTS)
                if not valid:
                    raise ConfigurationError(f"Invalid --config {group} value")
                result[key] = value
    return result

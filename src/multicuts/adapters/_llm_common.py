"""Shared settings, HTTP, CLI, and JSON helpers for LLM adapters."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from multicuts.errors import ConfigurationError, ScoringError

_HTTP_TIMEOUT = 180
_CLI_TIMEOUT = 600
_MAX_TRANSIENT_ATTEMPTS = 3


def setting(name: str) -> str | None:
    """Resolve a secret or option from process environment, then cwd .env."""
    value = os.environ.get(name)
    if value is not None:
        return value
    path = Path.cwd() / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigurationError("Could not read .env") from exc
    for line in lines:
        key, separator, raw = line.partition("=")
        if separator and key.strip().removeprefix("export ").strip() == name:
            raw = raw.strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                raw = raw[1:-1]
            return raw
    return None


def _json_text(value: str) -> object:
    try:
        return json.loads(
            value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
        )
    except (ValueError, TypeError) as exc:
        raise ScoringError("AI returned invalid JSON") from exc


def _post(
    url: str, headers: dict[str, str], payload: dict[str, object]
) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(_MAX_TRANSIENT_ATTEMPTS):
        try:
            with urlopen(request, timeout=_HTTP_TIMEOUT) as response:
                raw = response.read()
            parsed = _json_text(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ScoringError("AI returned an invalid response")
            return parsed
        except HTTPError as exc:
            if (
                exc.code in (408, 409, 429, 500, 502, 503, 504)
                and attempt + 1 < _MAX_TRANSIENT_ATTEMPTS
            ):
                sleep(2**attempt)
                continue
            raise ScoringError(f"AI provider returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt + 1 < _MAX_TRANSIENT_ATTEMPTS:
                sleep(2**attempt)
                continue
            raise ScoringError("AI provider connection failed") from exc
    raise AssertionError("transient retry loop did not terminate")


def _require_key(name: str) -> str:
    key = setting(name)
    if not key:
        raise ConfigurationError(f"{name} is required for the selected AI backend")
    return key


def _run_cli(command: list[str], prompt: str, *, cwd: Path) -> str:
    try:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            timeout=_CLI_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ConfigurationError(f"AI CLI {command[0]} is not installed") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScoringError(f"AI CLI {command[0]} failed or timed out") from exc
    if result.returncode != 0:
        raise ScoringError(f"AI CLI {command[0]} exited with code {result.returncode}")
    return result.stdout

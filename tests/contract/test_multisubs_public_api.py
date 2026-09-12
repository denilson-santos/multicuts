"""Checks for the public multisubs operations consumed by the adapter."""

import importlib
import inspect
from pathlib import Path
from types import ModuleType

import pytest


def _installed_provider() -> ModuleType:
    try:
        return importlib.import_module("multisubs")
    except ModuleNotFoundError as exc:
        if exc.name == "multisubs":
            pytest.skip("multisubs is not installed in this environment")
        raise


@pytest.mark.parametrize("language", [None, "pt"])
def test_public_transcription_signature_and_version(language: str | None) -> None:
    provider = _installed_provider()
    generate = getattr(provider, "generate_transcriptions", None)
    assert callable(generate), "multisubs.generate_transcriptions is unavailable"
    assert isinstance(getattr(provider, "__version__", None), str)
    assert provider.__version__, "multisubs does not expose its version"
    major, minor, *_ = provider.__version__.split(".")
    assert major == "4" and int(minor) >= 1, "unsupported multisubs version"

    try:
        inspect.signature(generate).bind(
            Path("source.mp4"),
            Path("output"),
            lang=language,
            task="transcribe",
            model_name="turbo",
        )
    except (TypeError, ValueError) as exc:
        pytest.fail(f"multisubs public transcription signature changed: {exc}")

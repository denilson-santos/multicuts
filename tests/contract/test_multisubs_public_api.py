"""Checks for the public multisubs operations consumed by the adapter."""

import importlib
import inspect
import subprocess
import sys
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


def test_multisubs_subtitle_timed_cue_json_signature_and_artifact_shape() -> None:
    """Pin the 4.3 contract consumed through the supported CLI boundary."""
    provider = _installed_provider()
    version = getattr(provider, "__version__", "")
    major, minor, *_ = version.split(".")
    assert major == "4" and int(minor) >= 3, "multisubs 4.3 or newer is required"

    generate = getattr(provider, "generate_subtitles_from_json", None)
    assert callable(generate), "multisubs.generate_subtitles_from_json is unavailable"
    try:
        inspect.signature(generate).bind(
            Path("cues.json"),
            Path("clip.mp4"),
            Path("output"),
            subtitle_config=None,
        )
    except (TypeError, ValueError) as exc:
        pytest.fail(f"multisubs public timed-cue signature changed: {exc}")

    artifacts = getattr(provider, "GeneratedSubtitleArtifacts", None)
    assert artifacts is not None, "multisubs.GeneratedSubtitleArtifacts is unavailable"
    assert {"srt_path", "ass_path", "video_path"}.issubset(
        getattr(artifacts, "__dataclass_fields__", {})
    ), "multisubs timed-cue artifact fields changed"


def test_multisubs_subtitle_cli_options() -> None:
    _installed_provider()
    executable = Path(sys.executable).with_name("multisubs")
    assert executable.is_file(), "multisubs CLI entry point is unavailable"
    completed = subprocess.run(
        [str(executable), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, "multisubs CLI help failed"
    for option in ("--cues-json", "--template", "--template-dir"):
        assert option in completed.stdout, f"multisubs CLI lacks {option}"

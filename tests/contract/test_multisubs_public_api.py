"""Checks for the public multisubs operations consumed by the adapter."""

import importlib
import inspect
import re
import subprocess
import sys
from importlib import metadata
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


def _assert_supported_provider_version() -> None:
    version = metadata.version("multisubs")
    parts = version.split(".")
    assert len(parts) >= 2 and all(part.isdigit() for part in parts[:2]), (
        "multisubs distribution lacks a numeric major/minor version"
    )
    assert parts[0] == "4" and int(parts[1]) >= 4, (
        "multisubs 4.4 or newer is required by the consumed public contract"
    )


@pytest.mark.parametrize("language", [None, "pt"])
@pytest.mark.parametrize(
    ("backend", "model"),
    [
        ("whisperx", "turbo"),
        ("faster-whisper", "large-v3"),
        ("parakeet", "nvidia/parakeet-tdt-0.6b-v3"),
        ("qwen", "Qwen/Qwen3-ASR-1.7B-hf"),
    ],
)
def test_public_transcription_signature_and_version(
    language: str | None, backend: str, model: str
) -> None:
    provider = _installed_provider()
    generate = getattr(provider, "generate_transcriptions", None)
    assert callable(generate), "multisubs.generate_transcriptions is unavailable"
    _assert_supported_provider_version()

    try:
        inspect.signature(generate).bind(
            Path("source.mp4"),
            Path("output"),
            lang=language,
            task="transcribe",
            model_name=model,
            asr_backend=backend,
        )
    except (TypeError, ValueError) as exc:
        pytest.fail(f"multisubs public transcription signature changed: {exc}")


def test_multisubs_subtitle_timed_cue_json_signature_and_artifact_shape() -> None:
    """Pin the 4.4 timed-cue splitting contract consumed by the adapter."""
    provider = _installed_provider()
    _assert_supported_provider_version()

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
    help_text = re.sub(r"\x1b\[[0-9;]*m", "", completed.stdout)
    for option in ("--cues-json", "--template", "--template-dir"):
        assert option in help_text, f"multisubs CLI lacks {option}"

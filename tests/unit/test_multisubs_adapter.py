"""Hermetic tests for the public multisubs transcription boundary."""

import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.errors import TranscriptionError


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    generate: Callable[..., object] | None,
    *,
    version: str = "4.1.0",
) -> None:
    provider = ModuleType("multisubs")
    provider.__dict__["__version__"] = version
    if generate is not None:
        provider.__dict__["generate_transcriptions"] = generate
    monkeypatch.setitem(sys.modules, "multisubs", provider)


def _write_artifacts(
    output_dir: Path,
    *,
    json_text: str = '{"segments": [{"text": "hello"}]}',
) -> tuple[str, str, str]:
    json_path = output_dir / "source.json"
    srt_path = output_dir / "source.srt"
    ass_path = output_dir / "source.ass"
    json_path.write_text(json_text, encoding="utf-8")
    srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    ass_path.write_text("[Script Info]\n", encoding="utf-8")
    return str(json_path), str(srt_path), str(ass_path)


def test_auto_language_and_default_model_use_public_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Path, Path, dict[str, object]]] = []

    def generate(
        input_path: Path, output_dir: Path, **kwargs: object
    ) -> tuple[str, str, str]:
        calls.append((input_path, output_dir, kwargs))
        return _write_artifacts(output_dir)

    _install_provider(monkeypatch, generate)
    video_path = tmp_path / "source.mp4"
    result = MultisubsAdapter().transcribe_to_artifact(
        video_path,
        language=None,
        model="default",
        workspace=tmp_path / "run",
    )

    assert result.json_path == (tmp_path / "run/multisubs/source.json").resolve()
    assert result.provider_version == "4.1.0"
    assert result.language_requested is None
    assert calls == [
        (
            video_path,
            (tmp_path / "run/multisubs").resolve(),
            {"lang": None, "task": "transcribe"},
        )
    ]


def test_explicit_language_and_model_are_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options: list[dict[str, object]] = []

    def generate(
        _input_path: Path, output_dir: Path, **kwargs: object
    ) -> tuple[str, str, str]:
        options.append(kwargs)
        return _write_artifacts(output_dir)

    _install_provider(monkeypatch, generate)

    result = MultisubsAdapter().transcribe_to_artifact(
        tmp_path / "source.mp4",
        language="pt",
        model="large-v3",
        workspace=tmp_path / "run",
    )

    assert result.language_requested == "pt"
    assert options == [{"lang": "pt", "task": "transcribe", "model_name": "large-v3"}]


def test_provider_failure_is_chained_without_leaking_provider_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = RuntimeError("private video path and provider details")

    def generate(_input_path: Path, _output_dir: Path, **_kwargs: object) -> None:
        raise failure

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="could not transcribe") as caught:
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )
    assert caught.value.__cause__ is failure
    assert "private video path" not in str(caught.value)


def test_missing_public_api_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, None)

    with pytest.raises(TranscriptionError, match="public transcription API"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_unavailable_provider_is_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = ModuleNotFoundError("private dependency detail")

    def unavailable(_name: str) -> ModuleType:
        raise failure

    monkeypatch.setattr(
        "multicuts.adapters.multisubs.importlib.import_module", unavailable
    )

    with pytest.raises(TranscriptionError, match="public transcription API") as caught:
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )
    assert caught.value.__cause__ is failure
    assert "private dependency detail" not in str(caught.value)


@pytest.mark.parametrize("generated", [None, (), ("only.json",), (1, 2, 3)])
def test_invalid_provider_return_is_rejected(
    generated: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(_input_path: Path, _output_dir: Path, **_kwargs: object) -> object:
        return generated

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="invalid artifact paths"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


@pytest.mark.parametrize("json_text", ["", "{invalid", "{}", "[]"])
def test_missing_or_invalid_json_cannot_be_successful(
    json_text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        return _write_artifacts(output_dir, json_text=json_text)

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="JSON transcript"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_missing_companion_artifact_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        paths = _write_artifacts(output_dir)
        (output_dir / "source.ass").unlink()
        return paths

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="readable JSON transcript"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_missing_json_artifact_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        paths = _write_artifacts(output_dir)
        (output_dir / "source.json").unlink()
        return paths

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="readable JSON transcript"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )


def test_provider_output_cannot_escape_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def generate(
        _input_path: Path, output_dir: Path, **_kwargs: object
    ) -> tuple[str, str, str]:
        paths = _write_artifacts(output_dir)
        outside = tmp_path / "outside.json"
        outside.write_text('{"text": "hello"}', encoding="utf-8")
        return str(outside), paths[1], paths[2]

    _install_provider(monkeypatch, generate)

    with pytest.raises(TranscriptionError, match="inside its workspace"):
        MultisubsAdapter().transcribe_to_artifact(
            tmp_path / "source.mp4",
            language=None,
            model="default",
            workspace=tmp_path / "run",
        )

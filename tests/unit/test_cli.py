"""Public CLI configuration and process-boundary behavior."""

from pathlib import Path

import pytest

from multicuts.app_config import AppConfig
from multicuts.cli import main, parse_run_config
from multicuts.errors import ScoringError
from multicuts.pipeline import RunOutcome, RunResult


def _args() -> list[str]:
    return [
        "source.mp4",
        "--output-dir",
        "out",
        "--llm-backend",
        "codex",
        "--llm-model",
        "test-model",
    ]


def test_cli_defaults_seek_both_classes_without_a_clip_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_EFFORT", raising=False)
    config = parse_run_config(_args())
    assert config.llm_backend == "codex"
    assert config.llm_model == "test-model"
    assert config.llm_effort is None
    assert config.short_aspect_ratio == "9:16"
    assert config.long_aspect_ratio == "16:9"
    assert config.language is None
    assert not hasattr(config, "clips")


def test_cli_options_override_process_environment_and_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "LLM_BACKEND=gemini\nLLM_MODEL=dotenv-model\nLLM_EFFORT=low\nOVERLAP_THRESHOLD=0.7\nSUBTITLES_ENABLED=false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_MODEL", "process-model")
    monkeypatch.setenv("LLM_EFFORT", "medium")
    config = parse_run_config(
        [
            "source.mp4",
            "--output-dir",
            str(tmp_path / "out"),
            "--llm-backend",
            "anthropic",
            "--llm-effort",
            "high",
            "--overlap-threshold",
            "0.8",
            "--subtitles",
        ]
    )
    assert config.output_dir == tmp_path / "out"
    assert config.llm_backend == "anthropic"
    assert config.llm_model == "process-model"
    assert config.llm_effort == "high"
    assert config.overlap_threshold == 0.8
    assert config.subtitles_enabled


def test_cli_rejects_removed_fixed_count_and_heuristic_options() -> None:
    assert main(_args() + ["--clips", "2"]) == 2
    assert main(_args() + ["--scorer", "heuristic"]) == 2
    assert main(_args() + ["--min-score", "70"]) == 2


@pytest.mark.parametrize("flag", ["--ai-backend", "--ai-model", "--ai-effort"])
def test_cli_rejects_removed_ai_flags(flag: str) -> None:
    assert main(_args() + [flag, "legacy"]) == 2


def test_cli_ignores_removed_ai_environment_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_BACKEND", "LLM_MODEL", "LLM_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_BACKEND", "codex")
    monkeypatch.setenv("AI_MODEL", "old-model")
    monkeypatch.setenv("AI_EFFORT", "high")
    assert main(["source.mp4", "--output-dir", str(tmp_path / "out")]) == 2


def test_cli_requires_backend_and_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert main(["source.mp4", "--output-dir", str(tmp_path / "out")]) == 2
    assert (
        main(
            [
                "source.mp4",
                "--output-dir",
                str(tmp_path / "out"),
                "--llm-backend",
                "openai",
            ]
        )
        == 2
    )


def test_cli_reports_zero_selection_as_success(tmp_path: Path) -> None:
    def fake_pipeline(config: AppConfig) -> RunResult:
        assert config.source == "source.mp4"
        return RunResult(
            "run-1", RunOutcome.ZERO_SELECTION, tmp_path / "manifest.json", ()
        )

    assert main(_args(), pipeline=fake_pipeline) == 0


def test_cli_reports_provider_failure_without_fallback() -> None:
    def fake_pipeline(_config: AppConfig) -> RunResult:
        raise ScoringError("provider unavailable")

    assert main(_args(), pipeline=fake_pipeline) == 5


def test_transcription_language_comes_only_from_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "TRANSCRIPTION_LANGUAGE=es\nLLM_BACKEND=codex\nLLM_MODEL=test-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRANSCRIPTION_LANGUAGE", "fr")
    automatic = parse_run_config(["source.mp4", "--output-dir", str(tmp_path / "out")])
    specified = parse_run_config(
        ["source.mp4", "--output-dir", str(tmp_path / "out"), "--lang", "pt"]
    )
    assert automatic.language is None
    assert specified.language == "pt"


def test_output_dir_is_required_even_when_environment_defines_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OUTPUT_DIR=dotenv-out\nLLM_BACKEND=codex\nLLM_MODEL=test-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OUTPUT_DIR", "process-out")
    assert main(["source.mp4"]) == 2
    config = parse_run_config(["source.mp4", "--output-dir", "cli-out"])
    assert config.output_dir == Path("cli-out")


def test_asr_model_flag_replaces_model_flag() -> None:
    config = parse_run_config(_args() + ["--asr-model", "large-v3"])
    assert config.transcription_model == "large-v3"
    assert main(_args() + ["--model", "large-v3"]) == 2


def test_llm_effort_from_environment_and_auto_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("LLM_EFFORT=low\n", encoding="utf-8")
    assert parse_run_config(_args()).llm_effort == "low"
    monkeypatch.setenv("LLM_EFFORT", "medium")
    assert parse_run_config(_args()).llm_effort == "medium"
    assert parse_run_config(_args() + ["--llm-effort", "auto"]).llm_effort is None


@pytest.mark.parametrize(
    ("backend", "effort"),
    [
        ("openai", "ultra"),
        ("anthropic", "none"),
        ("gemini", "xhigh"),
        ("codex", "none"),
        ("claude", "ultra"),
        ("agy", "xhigh"),
    ],
)
def test_cli_rejects_effort_unsupported_by_backend(
    backend: str, effort: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_EFFORT", raising=False)
    args = _args() + ["--llm-backend", backend, "--llm-effort", effort]
    assert main(args) == 2


def test_gemini_25_rejects_explicit_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_EFFORT", raising=False)
    args = _args() + [
        "--llm-backend",
        "gemini",
        "--llm-model",
        "gemini-2.5-pro",
        "--llm-effort",
        "high",
    ]
    assert main(args) == 2
    assert parse_run_config(args[:-2]).llm_effort is None


@pytest.mark.parametrize("location", ["dotenv", "process"])
def test_run_controls_are_cli_only(
    location: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    variables = {
        "VERBOSE": "true",
        "FORCE_RECOMPUTE": "true",
        "KEEP_INTERMEDIATES": "true",
    }
    if location == "dotenv":
        (tmp_path / ".env").write_text(
            "".join(f"{name}={value}\n" for name, value in variables.items()),
            encoding="utf-8",
        )
    else:
        for name, value in variables.items():
            monkeypatch.setenv(name, value)

    automatic = parse_run_config(_args())
    explicit = parse_run_config(
        _args() + ["--verbose", "--force-recompute", "--keep-intermediates"]
    )
    assert not automatic.verbose
    assert not automatic.force_recompute
    assert not automatic.keep_intermediates
    assert explicit.verbose
    assert explicit.force_recompute
    assert explicit.keep_intermediates


def test_main_ignores_verbose_environment_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VERBOSE", "true")
    calls: list[bool] = []
    monkeypatch.setattr("multicuts.cli.configure_logging", calls.append)

    def fake_pipeline(_config: AppConfig) -> RunResult:
        return RunResult(
            "run-1", RunOutcome.ZERO_SELECTION, tmp_path / "manifest.json", ()
        )

    assert main(_args(), pipeline=fake_pipeline) == 0
    assert calls == [False, False]

"""Public CLI configuration and process-boundary behavior."""

import logging
import os
import subprocess
import sys
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


@pytest.mark.parametrize("verbose", [False, True])
def test_cli_controls_dependency_output_and_preserves_project_progress(
    verbose: bool, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    dependency = logging.getLogger("test_dependency")
    original_level = dependency.level
    dependency.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stderr)
    dependency.addHandler(handler)
    other = logging.getLogger("multicuts_other")
    other.addHandler(handler)
    file_handler = logging.FileHandler(tmp_path / "dependency.log", encoding="utf-8")
    dependency.addHandler(file_handler)
    original_filters = list(handler.filters)

    def fake_pipeline(_config: AppConfig) -> RunResult:
        logging.getLogger("multicuts.pipeline").info("Application progress")
        logging.getLogger("multicuts.pipeline").debug("Application debug detail")
        dependency.warning("Dependency warning")
        other.warning("Unrelated namespace")
        print("Dependency stdout")
        print("Dependency stderr", file=sys.stderr)
        os.write(1, b"Native stdout\n")
        os.write(2, b"Native stderr\n")
        subprocess.run(
            [sys.executable, "-c", "import os; os.write(2, b'Child output\\n')"],
            check=True,
        )
        late_handler = logging.StreamHandler(sys.stderr)
        late_logger = logging.getLogger("test_late_dependency")
        late_logger.addHandler(late_handler)
        try:
            late_logger.warning("Late dependency warning")
        finally:
            late_logger.removeHandler(late_handler)
            late_handler.close()
        return RunResult(
            "run-logs", RunOutcome.ZERO_SELECTION, tmp_path / "manifest.json", ()
        )

    try:
        assert (
            main(_args() + (["--verbose"] if verbose else []), pipeline=fake_pipeline)
            == 0
        )
        assert handler.filters == original_filters
    finally:
        other.removeHandler(handler)
        dependency.removeHandler(handler)
        handler.close()
        dependency.removeHandler(file_handler)
        file_handler.close()
        dependency.setLevel(original_level)

    output = capfd.readouterr()
    assert "Application progress" in output.err
    assert "Dependency warning" in (tmp_path / "dependency.log").read_text(
        encoding="utf-8"
    )
    assert "Run run-logs: zero_selection; clips=0; manifest=" in output.out
    assert ("Application debug detail" in output.err) is verbose
    for text in (
        "Dependency warning",
        "Dependency stdout",
        "Dependency stderr",
        "Native stdout",
        "Native stderr",
        "Child output",
        "Late dependency warning",
        "Unrelated namespace",
    ):
        assert (text in output.out + output.err) is verbose


@pytest.mark.parametrize(
    "error", [ScoringError("provider failed"), KeyboardInterrupt()]
)
def test_cli_restores_output_and_logging_after_failure_or_interrupt(
    error: BaseException, tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    project = logging.getLogger("multicuts")
    previous = (project.level, project.propagate, tuple(project.handlers))
    stdout, stderr = sys.stdout, sys.stderr

    def fake_pipeline(_config: AppConfig) -> RunResult:
        print("Hidden provider output", file=sys.stderr)
        raise error

    assert main(_args(), pipeline=fake_pipeline) == (
        130 if isinstance(error, KeyboardInterrupt) else 5
    )
    assert (project.level, project.propagate, tuple(project.handlers)) == previous
    assert sys.stdout is stdout
    assert sys.stderr is stderr
    os.write(1, b"Restored stdout\n")
    os.write(2, b"Restored stderr\n")
    output = capfd.readouterr()
    assert "Restored stdout" in output.out
    assert "Restored stderr" in output.err
    assert "Hidden provider output" not in output.err
    assert (
        "Run interrupted"
        if isinstance(error, KeyboardInterrupt)
        else "AI analysis failed: provider failed"
    ) in output.err


def test_cli_does_not_duplicate_progress_on_repeated_invocations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_pipeline(_config: AppConfig) -> RunResult:
        logging.getLogger("multicuts.pipeline").info("Repeated progress")
        return RunResult(
            "run-repeat", RunOutcome.ZERO_SELECTION, tmp_path / "manifest.json", ()
        )

    assert main(_args(), pipeline=fake_pipeline) == 0
    assert main(_args() + ["--verbose", "--quiet"], pipeline=fake_pipeline) == 0
    output = capsys.readouterr()
    assert output.err.count("Repeated progress") == 2
    assert output.out.count("Run run-repeat:") == 2


def test_cli_preserves_progress_with_real_process_console_descriptors() -> None:
    script = """
import logging
import os
from pathlib import Path
import sys

from multicuts.cli import main
from multicuts.pipeline import RunOutcome, RunResult

def pipeline(config):
    logging.getLogger('multicuts.pipeline').info('Real console progress')
    logging.getLogger('dependency').warning('Hidden dependency log')
    print('Hidden provider print')
    os.write(2, b'Hidden native output\\n')
    return RunResult(
        'real-console', RunOutcome.ZERO_SELECTION, Path('manifest.json'), ()
    )

code = main(
    ['source.mp4', '--output-dir', 'out', '--llm-backend', 'codex',
     '--llm-model', 'test-model'],
    pipeline=pipeline,
)
print('Console restored', file=sys.stderr)
sys.exit(code)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "INFO [multicuts]: Real console progress" in result.stderr
    assert "Console restored" in result.stderr
    assert (
        "Run real-console: zero_selection; clips=0; manifest=manifest.json"
        in result.stdout
    )
    assert "Hidden" not in result.stdout + result.stderr

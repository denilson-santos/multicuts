"""Public CLI configuration and process-boundary behavior."""

import logging
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.app_config import AppConfig
from multicuts.cli import main, parse_run_config
from multicuts.errors import ConfigurationError, ScoringError
from multicuts.models import TimeRange
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


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("0", "90.5", TimeRange(0, 90.5)),
        ("01:30", "02:45.25", TimeRange(90, 165.25)),
        ("01:00:00", "01:02:30", TimeRange(3600, 3750)),
    ],
)
def test_search_range_accepts_seconds_and_clock_times(
    start: str, end: str, expected: TimeRange
) -> None:
    assert (
        parse_run_config(_args() + ["--search-range", start, end]).search_range
        == expected
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("10", "10"),
        ("20", "10"),
        ("-1", "10"),
        ("nan", "10"),
        ("0", "inf"),
        ("0", "01:60"),
        ("0", "1:2:3:4"),
        ("oops", "10"),
    ],
)
def test_search_range_rejects_invalid_timestamps(start: str, end: str) -> None:
    with pytest.raises(ConfigurationError, match="--search-range"):
        parse_run_config(_args() + ["--search-range", start, end])


@pytest.mark.parametrize(
    "flags", [["--clip-range", "01:30.25", "180.5"], ["--clip-full"]]
)
def test_direct_modes_do_not_require_ai_settings(
    flags: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_BACKEND", "LLM_MODEL", "LLM_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    config = parse_run_config(["source.mp4", "--output-dir", "out", *flags])
    assert config.direct_clip
    assert config.llm_backend == config.llm_model == ""
    assert config.llm_effort is None
    if "--clip-range" in flags:
        assert config.clip_range == TimeRange(90.25, 180.5)
        assert config.selection_mode == "custom"
    else:
        assert config.full_video
        assert config.selection_mode == "full_video"


@pytest.mark.parametrize("mode", [["--clip-full"], ["--clip-range", "0", "60"]])
@pytest.mark.parametrize("configured_in", ["cli", "process", "dotenv"])
def test_direct_modes_load_ai_title_settings(
    mode: list[str], configured_in: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_BACKEND", "LLM_MODEL", "LLM_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    args = ["source.mp4", "--output-dir", "out", *mode]
    if configured_in == "cli":
        args += ["--llm-backend", "codex", "--llm-model", "test", "--llm-effort", "low"]
    elif configured_in == "process":
        monkeypatch.setenv("LLM_BACKEND", "codex")
        monkeypatch.setenv("LLM_MODEL", "test")
        monkeypatch.setenv("LLM_EFFORT", "low")
    else:
        (tmp_path / ".env").write_text(
            "LLM_BACKEND=codex\nLLM_MODEL=test\nLLM_EFFORT=low\n", encoding="utf-8"
        )
    config = parse_run_config(args)
    assert (config.llm_backend, config.llm_model, config.llm_effort) == (
        "codex",
        "test",
        "low",
    )


@pytest.mark.parametrize(
    ("settings", "error"),
    [
        ({"LLM_BACKEND": "codex"}, "LLM_MODEL"),
        ({"LLM_MODEL": "test"}, "LLM_BACKEND"),
        ({"LLM_BACKEND": "unknown", "LLM_MODEL": "test"}, "LLM_BACKEND"),
        (
            {"LLM_BACKEND": "codex", "LLM_MODEL": "test", "LLM_EFFORT": "invalid"},
            "LLM_EFFORT",
        ),
    ],
)
def test_direct_modes_reject_incomplete_or_invalid_ai_settings(
    settings: dict[str, str],
    error: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_BACKEND", "LLM_MODEL", "LLM_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError, match=error):
        parse_run_config(["source.mp4", "--output-dir", "out", "--clip-full"])


@pytest.mark.parametrize(
    "flags",
    [
        ["--search-range", "0", "60", "--clip-range", "0", "30"],
        ["--search-range", "0", "60", "--clip-full"],
        ["--clip-range", "0", "30", "--clip-full"],
    ],
)
def test_selection_modes_are_mutually_exclusive(flags: list[str]) -> None:
    with pytest.raises(ConfigurationError, match="Choose only one"):
        parse_run_config(_args() + flags)


def test_custom_range_rejects_reversed_times() -> None:
    with pytest.raises(ConfigurationError, match="--clip-range"):
        parse_run_config(_args() + ["--clip-range", "60", "10"])


@pytest.fixture(autouse=True)
def _clear_output_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in tuple(os.environ):
        if name.startswith(
            (
                "RENDER",
                "VARIANTS",
                "ASPECT_RATIO",
                "PRIMARY",
                "WIDTH",
                "HEIGHT",
                "SUBTITLE_",
            )
        ):
            monkeypatch.delenv(name)


@pytest.mark.parametrize("clip_class", ["short", "long"])
@pytest.mark.parametrize("configured_in", ["dotenv", "process"])
@pytest.mark.parametrize("field", ["render", "subtitle-enabled"])
def test_output_boolean_sources_and_scope_precedence(
    clip_class, configured_in, field, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    name = "SUBTITLE_ENABLED" if field == "subtitle-enabled" else field.upper()
    raw = f"{clip_class}=false"
    if configured_in == "dotenv":
        (tmp_path / ".env").write_text(f"{name}={raw}\n", encoding="utf-8")
    else:
        monkeypatch.setenv(name, raw)

    def effective(config):
        return (
            config.clips_for(clip_class)
            if field == "render"
            else config.for_output(clip_class, "vertical").subtitles_for(clip_class)
        )

    assert effective(parse_run_config(_args())) is False
    assert effective(parse_run_config(_args() + [f"--{field}", "true"])) is True
    for assignments in (
        ("false", f"{clip_class}=true"),
        (f"{clip_class}=true", "false"),
    ):
        config = parse_run_config(
            _args() + [f"--{field}", assignments[0], f"--{field}", assignments[1]]
        )
        assert effective(config) is True


@pytest.mark.parametrize("field", ["render", "subtitle-enabled"])
def test_process_shared_setting_overrides_dotenv_class(field, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parent = "SUBTITLE_ENABLED" if field == "subtitle-enabled" else field.upper()
    (tmp_path / ".env").write_text(f"{parent}=long=false\n", encoding="utf-8")
    monkeypatch.setenv(parent, "true")
    config = parse_run_config(_args())
    assert config.clips_for("long")
    assert config.for_output("long", "vertical").subtitles_for("long")


@pytest.mark.parametrize(
    "name",
    ["RENDER", "SUBTITLE_ENABLED"],
)
def test_output_settings_reject_invalid_booleans(name, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(name, "sometimes")
    with pytest.raises(ConfigurationError, match="must be"):
        parse_run_config(_args())


def test_disabling_both_classes_fails_before_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            _args() + ["--render", "false"],
            pipeline=lambda _: pytest.fail("pipeline called"),
        )
        == 2
    )
    monkeypatch.setenv("RENDER", "false")
    with pytest.raises(ConfigurationError, match="at least one clip class"):
        parse_run_config(_args())
    assert parse_run_config(_args() + ["--render", "short=true"]).clips_for("short")


def test_cli_defaults_seek_both_classes_without_a_clip_quota(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_EFFORT", "ASR_MODEL", "ASR_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    config = parse_run_config(_args())
    assert config.short_primary == "auto"
    assert config.long_primary == "auto"
    assert config.render is True
    assert config.square_size == 1080
    for clip_class in ("short", "long"):
        assert config.clips_for(clip_class)
        assert config.render_for(clip_class) is True
        assert config.for_output(clip_class, "vertical").subtitles_for(clip_class)
    assert config.language is None
    assert config.transcription_model == "turbo"
    assert config.asr_backend == "whisperx"
    assert not hasattr(config, "clips")


@pytest.mark.parametrize("size", [0, -2, 361, True])
def test_square_size_requires_positive_even_pixels(size, tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Square size"):
        AppConfig("source.mp4", tmp_path, "codex", "test", square_size=size)


def test_cli_options_override_process_environment_and_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "LLM_BACKEND=gemini\nLLM_MODEL=dotenv-model\nLLM_EFFORT=low\n"
        "OVERLAP_THRESHOLD=0.7\nSUBTITLE_ENABLED=short=false long=false\n",
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
            "--subtitle-enabled",
            "true",
        ]
    )
    assert config.output_dir == tmp_path / "out"
    assert config.llm_backend == "anthropic"
    assert config.llm_model == "process-model"
    assert config.llm_effort == "high"
    assert config.overlap_threshold == 0.8
    assert config.subtitles_enabled
    assert config.subtitles_for("short") is config.subtitles_for("long") is True


@pytest.mark.parametrize("configured_in", ["dotenv", "process"])
def test_editorial_context_is_optional_and_cli_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured_in: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLIP_CONTEXT", raising=False)
    assert parse_run_config(_args()).editorial_context is None
    if configured_in == "dotenv":
        (tmp_path / ".env").write_text(
            'CLIP_CONTEXT="Interview about leadership"\n', encoding="utf-8"
        )
    else:
        monkeypatch.setenv("CLIP_CONTEXT", "Prioritize entrepreneurship")
    assert parse_run_config(_args()).editorial_context is None
    context = '  Entrevista sobre educação.\nO convidado é chamado de "professor".  '
    assert (
        parse_run_config(_args() + ["--context", context]).editorial_context
        == context.strip()
    )
    assert parse_run_config(_args() + ["--context", "  "]).editorial_context is None


def test_cli_passes_optional_context_to_pipeline(tmp_path: Path) -> None:
    def fake_pipeline(config: AppConfig) -> RunResult:
        assert config.editorial_context == "Prioritize hiring lessons"
        return RunResult(
            "run-context", RunOutcome.ZERO_SELECTION, tmp_path / "manifest.json", ()
        )

    assert (
        main(
            _args() + ["--context", "Prioritize hiring lessons"], pipeline=fake_pipeline
        )
        == 0
    )


def test_configuration_rejects_nontext_editorial_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigurationError, match="--context must be text"):
        replace(parse_run_config(_args()), editorial_context=42)


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


def test_cli_reports_zero_selection_as_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_pipeline(config: AppConfig) -> RunResult:
        assert config.source == "source.mp4"
        return RunResult(
            "run-1", RunOutcome.ZERO_SELECTION, tmp_path / "manifest.json", ()
        )

    assert main(_args(), pipeline=fake_pipeline) == 0
    summary = capsys.readouterr().out
    assert f"manifest={tmp_path / 'manifest.json'}" in summary
    assert f"report={tmp_path / 'report.md'}" in summary


def test_cli_reports_provider_failure_without_fallback() -> None:
    def fake_pipeline(_config: AppConfig) -> RunResult:
        raise ScoringError("provider unavailable")

    assert main(_args(), pipeline=fake_pipeline) == 5


@pytest.mark.parametrize("verbose", [False, True])
def test_cli_reports_wrapped_cuda_loading_failure_without_private_details(
    verbose: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    def generate(_source: Path, **_kwargs: object) -> None:
        calls.append("transcribe")
        try:
            raise RuntimeError(
                "Library libcublas.so.12 is not found or cannot be loaded"
            )
        except RuntimeError as error:
            raise RuntimeError("private input path; token=private-token") from error

    provider = ModuleType("multisubs")
    provider.__dict__["transcribe_speech"] = generate
    monkeypatch.setitem(sys.modules, "multisubs", provider)
    monkeypatch.setattr(
        "multicuts.adapters.multisubs.importlib.metadata.version", lambda _name: "4.4.0"
    )

    def missing_library(_name: str, *, mode: int) -> None:
        raise OSError("Native libraries unavailable in this hermetic test")

    def missing_distribution(name: str) -> None:
        from importlib.metadata import PackageNotFoundError

        raise PackageNotFoundError(name)

    monkeypatch.setattr("multicuts.adapters.multisubs.ctypes.CDLL", missing_library)
    monkeypatch.setattr(
        "multicuts.adapters.multisubs.importlib.metadata.distribution",
        missing_distribution,
    )

    def pipeline(config: AppConfig) -> RunResult:
        MultisubsAdapter().transcribe(
            Path(config.source),
            language=config.language,
            backend=config.asr_backend,
            model=config.transcription_model,
            workspace=tmp_path / "work",
        )
        raise AssertionError("Provider failure must stop the run")

    arguments = _args() + ["--asr-backend", "faster-whisper", "--asr-model", "turbo"]
    if verbose:
        arguments.append("--verbose")
    assert main(arguments, pipeline=pipeline) == 4
    output = capfd.readouterr()
    assert "Transcription failed" in output.err
    assert "NVIDIA cuBLAS (CUDA 12)" in output.err
    assert "Python environment" in output.err
    assert "private" not in output.out + output.err
    assert calls == ["transcribe"]


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
    config = parse_run_config(_args() + ["--asr-model", "medium"])
    assert config.transcription_model == "medium"
    assert main(_args() + ["--model", "medium"]) == 2


def test_asr_settings_resolve_cli_environment_and_dotenv_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASR_MODEL", raising=False)
    monkeypatch.delenv("ASR_BACKEND", raising=False)
    (tmp_path / ".env").write_text(
        "ASR_BACKEND=faster-whisper\nASR_MODEL=large-v3\n", encoding="utf-8"
    )
    config = parse_run_config(_args())
    assert (config.asr_backend, config.transcription_model) == (
        "faster-whisper",
        "large-v3",
    )

    monkeypatch.setenv("ASR_BACKEND", "parakeet")
    monkeypatch.setenv("ASR_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
    config = parse_run_config(_args())
    assert (config.asr_backend, config.transcription_model) == (
        "parakeet",
        "nvidia/parakeet-tdt-0.6b-v3",
    )

    config = parse_run_config(
        _args() + ["--asr-backend", "whisperx", "--asr-model", "turbo"]
    )
    assert (config.asr_backend, config.transcription_model) == ("whisperx", "turbo")


@pytest.mark.parametrize("configured_in", ["dotenv", "process"])
def test_removed_transcription_model_setting_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured_in: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASR_MODEL", raising=False)
    monkeypatch.delenv("TRANSCRIPTION_MODEL", raising=False)
    if configured_in == "dotenv":
        (tmp_path / ".env").write_text("TRANSCRIPTION_MODEL=small\n", encoding="utf-8")
    else:
        monkeypatch.setenv("TRANSCRIPTION_MODEL", "small")
    assert parse_run_config(_args()).transcription_model == "turbo"


@pytest.mark.parametrize("backend", ["whisperx", "faster-whisper", "parakeet", "qwen"])
def test_asr_backend_flag_is_independent_of_llm_backend(backend: str) -> None:
    config = parse_run_config(_args() + ["--asr-backend", backend])
    assert config.asr_backend == backend
    assert config.llm_backend == "codex"


@pytest.mark.parametrize("backend", ["", "unknown"])
def test_invalid_asr_backend_is_rejected_before_pipeline(backend: str) -> None:
    with pytest.raises(ConfigurationError, match="ASR_BACKEND must be"):
        parse_run_config(_args() + ["--asr-backend", backend])


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


def test_render_encoding_cli_overrides_environment(monkeypatch):
    from multicuts.app_config import RenderEncoding

    monkeypatch.setenv("RENDER_ENCODER", "h264_nvenc")
    monkeypatch.setenv("RENDER_PRESET", "p4")
    monkeypatch.setenv("RENDER_QUALITY", "28")
    assert parse_run_config(_args()).render_encoding == RenderEncoding(
        "h264_nvenc", "p4", 28
    )
    config = parse_run_config(
        _args()
        + [
            "--render-encoder",
            "libx264",
            "--render-preset",
            "fast",
            "--render-quality",
            "0",
        ]
    )
    assert config.render_encoding == RenderEncoding("libx264", "fast", 0)


@pytest.mark.parametrize(
    "options",
    [
        {"preset": "fast"},
        {"quality": 18},
        {"encoder": "unknown"},
        {"encoder": "libx264", "preset": "p4"},
        {"encoder": "h264_nvenc", "preset": "fast"},
        {"encoder": "libx264", "quality": -1},
        {"encoder": "libx264", "quality": True},
        {"encoder": "libx264", "quality": 52},
    ],
)
def test_invalid_render_encoding_fails_configuration(options):
    from multicuts.app_config import RenderEncoding

    with pytest.raises(ConfigurationError):
        RenderEncoding(**options)


def test_render_jobs_configuration_and_validation(monkeypatch):
    monkeypatch.setenv("RENDER_JOBS", "3")
    assert parse_run_config(_args()).render_jobs == 3
    assert parse_run_config(_args() + ["--render-jobs", "2"]).render_jobs == 2


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_render_jobs(value):
    with pytest.raises(ConfigurationError, match="Render jobs"):
        AppConfig("source.mp4", Path("out"), full_video=True, render_jobs=value)

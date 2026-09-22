from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from multicuts.config import RunConfig
from multicuts.errors import ConfigurationError


@pytest.fixture
def valid_config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        source="/missing/video.mp4",
        output_dir=tmp_path / "output",
        clips=3,
        min_score=65,
        aspect_ratio="9:16",
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="large-v3",
    )


def test_run_config_uses_explicit_defaults_without_external_access(
    valid_config: RunConfig,
) -> None:
    assert valid_config.source == "/missing/video.mp4"
    assert valid_config.language is None
    assert valid_config.min_duration == 15.0
    assert valid_config.max_duration == 60.0
    assert valid_config.overlap_threshold == 0.60
    assert valid_config.text_similarity_threshold == 0.90
    assert valid_config.subtitle_template_dir is None
    assert not valid_config.keep_intermediates
    assert not valid_config.force_recompute
    assert not valid_config.verbose
    with pytest.raises(FrozenInstanceError):
        valid_config.clips = 5  # type: ignore[misc]


def test_run_config_preserves_explicit_run_options(valid_config: RunConfig) -> None:
    config = replace(
        valid_config,
        language="pt",
        min_duration=20.0,
        max_duration=40.0,
        keep_intermediates=True,
        force_recompute=True,
        verbose=True,
    )

    assert (config.language, config.min_duration, config.max_duration) == (
        "pt",
        20.0,
        40.0,
    )
    assert config.keep_intermediates and config.force_recompute and config.verbose


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [(None, None), ("auto", None), ("AUTO", None), ("pt-BR", "pt-BR")],
)
def test_run_config_normalizes_auto_language(
    valid_config: RunConfig, supplied: str | None, expected: str | None
) -> None:
    assert replace(valid_config, language=supplied).language == expected


@pytest.mark.parametrize("clips", [0, -1, True])
def test_run_config_rejects_invalid_clip_count(
    valid_config: RunConfig, clips: int
) -> None:
    with pytest.raises(ConfigurationError, match="clips"):
        replace(valid_config, clips=clips)


@pytest.mark.parametrize("min_score", [-1, 101, True])
def test_run_config_rejects_invalid_score(
    valid_config: RunConfig, min_score: int
) -> None:
    with pytest.raises(ConfigurationError, match="min_score"):
        replace(valid_config, min_score=min_score)


@pytest.mark.parametrize("min_score", [0, 100])
def test_run_config_accepts_score_boundaries(
    valid_config: RunConfig, min_score: int
) -> None:
    assert replace(valid_config, min_score=min_score).min_score == min_score


@pytest.mark.parametrize("value", [-0.1, 1.1, True, float("inf"), float("nan")])
def test_run_config_rejects_invalid_selection_thresholds(
    valid_config: RunConfig, value: float
) -> None:
    with pytest.raises(ConfigurationError, match="overlap_threshold"):
        replace(valid_config, overlap_threshold=value)
    with pytest.raises(ConfigurationError, match="text_similarity_threshold"):
        replace(valid_config, text_similarity_threshold=value)


@pytest.mark.parametrize("duration", [0.0, -1.0, float("inf"), float("nan")])
def test_run_config_rejects_invalid_duration(
    valid_config: RunConfig, duration: float
) -> None:
    with pytest.raises(ConfigurationError, match="min_duration"):
        replace(valid_config, min_duration=duration)
    with pytest.raises(ConfigurationError, match="max_duration"):
        replace(valid_config, max_duration=duration)


def test_run_config_rejects_reversed_duration_range(valid_config: RunConfig) -> None:
    with pytest.raises(ConfigurationError, match="min_duration"):
        replace(valid_config, min_duration=61.0)


def test_run_config_accepts_equal_duration_bounds(valid_config: RunConfig) -> None:
    config = replace(valid_config, min_duration=30.0, max_duration=30.0)

    assert config.min_duration == config.max_duration == 30.0


def test_run_config_rejects_unsupported_aspect_ratio(valid_config: RunConfig) -> None:
    with pytest.raises(ConfigurationError, match="aspect_ratio"):
        replace(valid_config, aspect_ratio="square")


@pytest.mark.parametrize("aspect_ratio", ["original", "9:16"])
def test_run_config_accepts_supported_aspect_ratios(
    valid_config: RunConfig, aspect_ratio: str
) -> None:
    assert replace(valid_config, aspect_ratio=aspect_ratio).aspect_ratio == aspect_ratio


def test_run_config_validates_supplied_template_directory(
    valid_config: RunConfig, tmp_path: Path
) -> None:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    template_file = template_dir / "template.json"
    template_file.write_text("{}", encoding="utf-8")

    configured = replace(valid_config, subtitle_template_dir=template_dir)
    assert configured.subtitle_template_dir == template_dir
    for invalid in (template_file, tmp_path / "missing"):
        with pytest.raises(ConfigurationError, match="subtitle_template_dir"):
            replace(valid_config, subtitle_template_dir=invalid)


@pytest.mark.parametrize(
    "field_name", ["source", "subtitle_template", "scorer", "model"]
)
def test_run_config_rejects_blank_required_names(
    valid_config: RunConfig, field_name: str
) -> None:
    with pytest.raises(ConfigurationError, match=field_name):
        replace(valid_config, **{field_name: "  "})


def test_run_config_rejects_blank_language(valid_config: RunConfig) -> None:
    with pytest.raises(ConfigurationError, match="language"):
        replace(valid_config, language="  ")

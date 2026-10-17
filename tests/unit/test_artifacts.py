"""Portable names keep source and generated title text inside artifact paths."""

import re

import pytest

from multicuts.artifacts import artifact_slug, source_label


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("A decisão que mudou tudo!", "a-decisao-que-mudou-tudo"),
        ("../../Outside\\Video: *?|<>\n", "outside-video"),
        ("🎬 字幕", "clip"),
        ("---", "clip"),
    ],
)
def test_artifact_slug_produces_portable_names(title: str, expected: str) -> None:
    assert artifact_slug(title, fallback="clip") == expected


def test_artifact_slug_bounds_long_names() -> None:
    slug = artifact_slug("Á long title " * 100, fallback="clip")
    assert len(slug.encode("utf-8")) <= 48
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("/videos/Minha entrevista.mp4", "minha-entrevista"),
        ("https://www.youtube.com/watch?v=abc_123&tracking=secret", "youtube-abc-123"),
        ("https://youtu.be/abc_123", "youtube-abc-123"),
        ("https://user:secret@example.com/video.mp4?token=private", "source"),
    ],
)
def test_source_label_uses_only_filename_or_youtube_identity(
    source: str, expected: str
) -> None:
    assert source_label(source) == expected

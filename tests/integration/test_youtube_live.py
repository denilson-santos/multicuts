import os
from pathlib import Path

import pytest

from multicuts.adapters.youtube import YoutubeAdapter


@pytest.mark.integration
def test_youtube_adapter_against_explicit_fixture_source(tmp_path: Path) -> None:
    source = os.environ.get("MULTICUTS_YOUTUBE_TEST_URL")
    if not source:
        pytest.skip("set MULTICUTS_YOUTUBE_TEST_URL to run the live YouTube check")
    assert source is not None

    acquired = YoutubeAdapter().acquire(source, tmp_path / "downloads")

    assert acquired.source_kind == "youtube"
    assert acquired.provider_id
    assert acquired.title
    assert acquired.local_path.is_file()
    assert acquired.local_path.is_relative_to((tmp_path / "downloads").resolve())

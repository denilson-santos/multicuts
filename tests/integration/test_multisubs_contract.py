"""Opt-in real-media check of the public multisubs transcription JSON contract."""

import os
from pathlib import Path

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter


@pytest.mark.integration
def test_real_transcription_normalizes_public_json(tmp_path: Path) -> None:
    source_value = os.environ.get("MULTICUTS_MULTISUBS_CONTRACT_VIDEO")
    if not source_value:
        pytest.skip("set MULTICUTS_MULTISUBS_CONTRACT_VIDEO to a short local video")
    source = Path(source_value).expanduser()
    if not source.is_file():
        pytest.fail("MULTICUTS_MULTISUBS_CONTRACT_VIDEO must name a local file")

    transcript = MultisubsAdapter().transcribe(
        source,
        language=None,
        model=os.environ.get("MULTICUTS_MULTISUBS_CONTRACT_MODEL", "default"),
        workspace=tmp_path,
    )

    assert transcript.provider == "multisubs"
    assert transcript.provider_version
    assert transcript.language_requested is None
    assert transcript.language_detected
    assert transcript.segments
    assert transcript.words

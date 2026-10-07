"""Opt-in real-media check of the public multisubs transcription JSON contract."""

import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "linux", reason="CUDA wheel loading targets Linux")
def test_faster_whisper_loads_cuda_wheels_in_a_fresh_process_without_library_path(
    tmp_path: Path,
) -> None:
    for package, folder, library in (
        ("nvidia-cublas-cu12", "cublas", "libcublasLt.so.12"),
        ("nvidia-cublas-cu12", "cublas", "libcublas.so.12"),
        ("nvidia-cudnn-cu12", "cudnn", "libcudnn.so.9"),
    ):
        try:
            distribution = metadata.distribution(package)
        except metadata.PackageNotFoundError:
            pytest.skip("installed NVIDIA runtime wheels are required")
        if not Path(
            str(distribution.locate_file(f"nvidia/{folder}/lib/{library}"))
        ).is_file():
            pytest.skip("installed NVIDIA runtime shared libraries are required")
    script = """
import ctypes
import os
import sys
from pathlib import Path
from types import ModuleType
from multicuts.adapters.multisubs import MultisubsAdapter

assert 'LD_LIBRARY_PATH' not in os.environ
provider = ModuleType('multisubs')
def generate(source, output, **options):
    json_path = output / 'source.json'
    json_path.write_text(
        Path(sys.argv[1]).read_text(encoding='utf-8'), encoding='utf-8',
    )
    srt_path = output / 'source.srt'
    ass_path = output / 'source.ass'
    srt_path.touch()
    ass_path.touch()
    return json_path, srt_path, ass_path
provider.generate_transcriptions = generate
sys.modules['multisubs'] = provider
transcript = MultisubsAdapter().transcribe(
    Path('source.mp4'), language='pt', backend='faster-whisper', model='turbo',
    workspace=Path(sys.argv[2]),
)
assert transcript.words
for library in ('libcublasLt.so.12', 'libcublas.so.12', 'libcudnn.so.9'):
    ctypes.CDLL(library)
assert 'LD_LIBRARY_PATH' not in os.environ
"""
    environment = dict(os.environ)
    environment.pop("LD_LIBRARY_PATH", None)
    fixture = (
        Path(__file__).parent.parent / "fixtures" / "multisubs_v4_1_transcript.json"
    )
    subprocess.run(
        [sys.executable, "-c", script, str(fixture), str(tmp_path)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


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

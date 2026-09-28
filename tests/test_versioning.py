"""Check the release version policy at its command-line boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

VERIFIER = Path(__file__).parents[1] / "scripts" / "verify_version.py"


@pytest.mark.parametrize("version", ["0.0.0", "0.1.0", "1.2.3", "12.34.56"])
def test_accepts_stable_semver(tmp_path: Path, version: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "multicuts"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "--project-root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GITHUB_REF": "refs/heads/main"},
    )
    assert result.returncode == 0, result.stderr
    assert f"multicuts {version}" in result.stdout


@pytest.mark.parametrize("version", ["1.2", "01.2.3", "1.02.3", "1.2.03", "1.2.3-rc.1"])
def test_rejects_noncanonical_release_versions(tmp_path: Path, version: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nversion = "{version}"\n', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "--project-root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GITHUB_REF": "refs/heads/main"},
    )
    assert result.returncode == 1
    assert "stable SemVer" in result.stderr


def test_tag_push_must_match_package_version(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.2.0"\n', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "--project-root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GITHUB_REF": "refs/tags/v0.3.0"},
    )
    assert result.returncode == 1
    assert "must be v0.2.0" in result.stderr


def test_release_tag_matching_package_version_passes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.2.0"\n', encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--project-root",
            str(tmp_path),
            "--tag",
            "v0.2.0",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GITHUB_REF": "refs/heads/main"},
    )
    assert result.returncode == 0, result.stderr
    assert "multicuts 0.2.0 (v0.2.0)" in result.stdout


def test_development_placeholder_cannot_be_tagged(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.0.0"\n', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "--project-root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GITHUB_REF": "refs/tags/v0.0.0"},
    )
    assert result.returncode == 1
    assert "development placeholder" in result.stderr

"""Build and smoke-test multicuts distributions outside the checkout."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path


class VerificationError(RuntimeError):
    """Raised when a distribution does not satisfy the packaging contract."""


_MEDIA_SUFFIXES = {
    ".avi",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}
_FORBIDDEN_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    ".cache",
    "downloads",
    "models",
    "multicuts-output",
    "node_modules",
    "venv",
}
_FORBIDDEN_NAMES = {
    ".env",
    ".env.development",
    ".env.local",
    ".env.production",
    "api_keys.json",
    "cookies.txt",
    "credentials.json",
    "secrets.json",
}
_FORBIDDEN_NAME_MARKERS = ("access_token", "api_key", "apikey", "secret", "token")
_MODEL_MARKERS = (
    "model-download",
    "model_download",
    "whisper-model",
    "whisper_model",
)


@dataclass(frozen=True, slots=True)
class _ProjectMetadata:
    name: str
    requires_python: str
    dependencies: tuple[str, ...]
    extras: tuple[str, ...]
    console_script: str


def _project_metadata() -> _ProjectMetadata:
    # These are the supported package contracts declared in pyproject.toml.
    # Keeping them here makes a packaging-policy change fail this verifier until
    # the check is deliberately reviewed and updated with the declaration.
    return _ProjectMetadata(
        name="multicuts",
        requires_python=">=3.10,<3.14",
        dependencies=("typer", "yt-dlp", "multisubs"),
        extras=("openai", "dev"),
        console_script="multicuts.cli:main",
    )


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> None:
    """Run a validation command and preserve its output for CI diagnostics."""
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _single_artifact(directory: Path, pattern: str) -> Path:
    artifacts = sorted(directory.glob(pattern))
    if len(artifacts) != 1:
        raise VerificationError(
            f"expected one {pattern} artifact in {directory}, found {len(artifacts)}"
        )
    return artifacts[0]


def _member_parts(name: str) -> tuple[str, ...]:
    return tuple(part for part in name.replace("\\", "/").split("/") if part)


def _assert_safe_members(members: Sequence[str]) -> None:
    forbidden: list[str] = []
    for name in members:
        parts = _member_parts(name)
        lowered = name.lower()
        basename = parts[-1].lower() if parts else ""
        if any(part.lower() in _FORBIDDEN_PARTS for part in parts):
            forbidden.append(name)
            continue
        if basename in _FORBIDDEN_NAMES or any(
            marker in basename for marker in _FORBIDDEN_NAME_MARKERS
        ):
            forbidden.append(name)
            continue
        if Path(name).suffix.lower() in _MEDIA_SUFFIXES:
            forbidden.append(name)
            continue
        if any(marker in lowered for marker in _MODEL_MARKERS):
            forbidden.append(name)
    if forbidden:
        sample = ", ".join(sorted(forbidden)[:5])
        raise VerificationError(f"distribution contains forbidden files: {sample}")


def _inspect_wheel(path: Path, expected: _ProjectMetadata) -> None:
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        metadata_paths = [
            name for name in members if name.endswith(".dist-info/METADATA")
        ]
        entry_point_paths = [
            name for name in members if name.endswith(".dist-info/entry_points.txt")
        ]
        if len(metadata_paths) != 1:
            raise VerificationError(f"wheel has invalid metadata files: {path}")
        if len(entry_point_paths) != 1:
            raise VerificationError(
                f"wheel is missing the console entry point metadata: {path}"
            )
        metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
        entry_points = archive.read(entry_point_paths[0]).decode("utf-8")
    _assert_safe_members(members)
    if f"{expected.name}/__init__.py" not in members:
        raise VerificationError(f"wheel is missing the package source: {path}")
    if metadata["Name"] != expected.name:
        raise VerificationError(f"wheel has unexpected package name: {path}")
    actual_python_constraints = {
        constraint.strip()
        for constraint in (metadata["Requires-Python"] or "").split(",")
        if constraint.strip()
    }
    expected_python_constraints = {
        constraint.strip() for constraint in expected.requires_python.split(",")
    }
    if actual_python_constraints != expected_python_constraints:
        raise VerificationError(f"wheel changed Python support metadata: {path}")
    requirements = tuple(metadata.get_all("Requires-Dist") or ())
    for dependency in expected.dependencies:
        match = re.match(r"[A-Za-z0-9_.-]+", dependency)
        if match is None:
            raise VerificationError(
                f"project dependency cannot be inspected: {dependency}"
            )
        name = match.group(0).lower().replace("_", "-")
        if not any(
            re.match(r"[A-Za-z0-9_.-]+", requirement)
            and re.match(r"[A-Za-z0-9_.-]+", requirement)
            .group(0)
            .lower()
            .replace("_", "-")
            == name
            for requirement in requirements
        ):
            raise VerificationError(f"wheel is missing declared dependency: {name}")
    provided_extras = {
        value.lower() for value in metadata.get_all("Provides-Extra") or ()
    }
    missing_extras = [
        extra for extra in expected.extras if extra.lower() not in provided_extras
    ]
    if missing_extras:
        raise VerificationError(
            f"wheel is missing declared optional extras: {', '.join(missing_extras)}"
        )
    expected_entry_point = f"multicuts = {expected.console_script}"
    if expected_entry_point not in entry_points:
        raise VerificationError(
            f"wheel is missing the multicuts console entry point: {path}"
        )


def _inspect_sdist(path: Path) -> str:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getnames()
    _assert_safe_members(members)
    roots = {_member_parts(name)[0] for name in members if _member_parts(name)}
    if len(roots) != 1:
        raise VerificationError(f"source distribution has unexpected roots: {roots}")
    root = roots.pop()
    required = (
        f"{root}/pyproject.toml",
        f"{root}/README.md",
        f"{root}/src/multicuts/__init__.py",
    )
    missing = [name for name in required if name not in members]
    if missing:
        raise VerificationError(f"source distribution is missing: {', '.join(missing)}")
    return root


def _extract_sdist(path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True)
    destination_root = destination.resolve()
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination_root):
                raise VerificationError(
                    "source distribution member escapes extraction directory: "
                    f"{member.name}"
                )
            if member.issym() or member.islnk():
                raise VerificationError(
                    f"source distribution contains an unexpected link: {member.name}"
                )
        archive.extractall(destination, members=members)
    root = _inspect_sdist(path)
    extracted = destination / root
    if not extracted.is_dir():
        raise VerificationError(f"source distribution did not extract to {extracted}")
    return extracted


def _venv_python(venv: Path) -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    executable = venv / relative
    if not executable.is_file():
        raise VerificationError(f"virtual environment has no Python executable: {venv}")
    return executable


def _create_venv(host_python: Path, destination: Path) -> Path:
    _run([str(host_python), "-m", "venv", str(destination)], cwd=destination.parent)
    return _venv_python(destination)


def _smoke_installed_distribution(
    *,
    host_python: Path,
    package_artifact: Path,
    environment: Path,
    project_root: Path,
    work_dir: Path,
) -> None:
    python = _create_venv(host_python, environment)
    _run(
        [str(python), "-m", "pip", "install", "--no-deps", str(package_artifact)],
        cwd=work_dir,
    )
    # The package is intentionally installed without dependencies first. Typer
    # is then provisioned alone so the console entry point can be exercised
    # without claiming that this smoke check validates the full dependency set.
    _run(
        [str(python), "-m", "pip", "install", "typer>=0.27.2,<0.28"],
        cwd=work_dir,
    )
    probe_dir = work_dir / f"probe-{environment.name}"
    probe_dir.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    probe = """
import importlib.metadata
import os
import sys
from pathlib import Path

import multicuts

project_root = Path(sys.argv[1]).resolve()
module_path = Path(multicuts.__file__).resolve()
assert not module_path.is_relative_to(project_root), module_path
assert importlib.metadata.version("multicuts")
assert importlib.metadata.metadata("multicuts")["Name"] == "multicuts"
assert "PYTHONPATH" not in os.environ
assert all(
    not Path(entry or ".").resolve().is_relative_to(project_root)
    for entry in sys.path
)
"""
    _run(
        [str(python), "-c", probe, str(project_root)],
        cwd=probe_dir,
        env=env,
    )
    _run(
        [
            str(
                environment
                / ("Scripts/multicuts.exe" if os.name == "nt" else "bin/multicuts")
            ),
            "--help",
        ],
        cwd=probe_dir,
        env=env,
    )


def verify_distributions(
    *, project_root: Path, work_dir: Path, host_python: Path
) -> tuple[Path, Path, Path]:
    """Build, inspect, and install wheel/sdist artifacts in isolated environments."""
    project_root = project_root.resolve()
    work_dir = work_dir.resolve()
    expected = _project_metadata()
    if not project_root.is_dir():
        raise VerificationError(f"project root does not exist: {project_root}")
    if work_dir.exists() and any(work_dir.iterdir()):
        raise VerificationError(f"work directory must be empty: {work_dir}")
    work_dir.mkdir(parents=True, exist_ok=True)

    source_dist = work_dir / "source-dist"
    _run(
        [
            str(host_python),
            "-m",
            "build",
            "--wheel",
            "--sdist",
            "--outdir",
            str(source_dist),
            str(project_root),
        ],
        cwd=project_root,
    )
    wheel = _single_artifact(source_dist, "*.whl")
    sdist = _single_artifact(source_dist, "*.tar.gz")
    _inspect_wheel(wheel, expected)
    _inspect_sdist(sdist)

    extracted_root = _extract_sdist(sdist, work_dir / "sdist-source")
    derived_dist = work_dir / "sdist-wheel"
    _run(
        [
            str(host_python),
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(derived_dist),
            str(extracted_root),
        ],
        cwd=extracted_root,
    )
    derived_wheel = _single_artifact(derived_dist, "*.whl")
    _inspect_wheel(derived_wheel, expected)

    _smoke_installed_distribution(
        host_python=host_python,
        package_artifact=wheel,
        environment=work_dir / "wheel-venv",
        project_root=project_root,
        work_dir=work_dir,
    )
    _smoke_installed_distribution(
        host_python=host_python,
        package_artifact=sdist,
        environment=work_dir / "sdist-venv",
        project_root=project_root,
        work_dir=work_dir,
    )
    _smoke_installed_distribution(
        host_python=host_python,
        package_artifact=derived_wheel,
        environment=work_dir / "sdist-wheel-venv",
        project_root=project_root,
        work_dir=work_dir,
    )
    return wheel, sdist, derived_wheel


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=Path.cwd(), help="checkout to package"
    )
    parser.add_argument(
        "--work-dir", type=Path, required=True, help="empty directory for artifacts"
    )
    parser.add_argument(
        "--python",
        dest="host_python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable with the build dependency installed",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        wheel, sdist, derived_wheel = verify_distributions(
            project_root=args.project_root,
            work_dir=args.work_dir,
            host_python=args.host_python,
        )
    except (OSError, subprocess.CalledProcessError, VerificationError) as exc:
        print(f"distribution verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"wheel: {wheel}")
    print(f"sdist: {sdist}")
    print(f"sdist-derived wheel: {derived_wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

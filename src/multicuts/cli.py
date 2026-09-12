"""Command-line parsing for one multicuts run."""

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from multicuts.config import RunConfig

DEFAULT_OUTPUT_DIR = Path("multicuts-output")
DEFAULT_CLIPS = 5
DEFAULT_MIN_SCORE = 0
DEFAULT_ASPECT_RATIO = "original"
DEFAULT_SUBTITLE_TEMPLATE = "yellow-pop"
DEFAULT_SCORER = "heuristic"
DEFAULT_MODEL = "default"


PipelineRunner = Callable[[RunConfig], None]


def _path_argument(value: str) -> Path:
    """Convert a CLI path while preserving relative paths."""
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the documented multicuts command surface."""
    parser = argparse.ArgumentParser(
        prog="multicuts",
        description=(
            "Generate ranked short clips from a source. The viral-potential "
            "score is an explainable ranking heuristic, not a probability."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser(
        "generate",
        help="Generate ranked clips from a local video or supported URL.",
        description=(
            "Generate ranked short clips from SOURCE. The viral-potential "
            "score is an explainable ranking heuristic, not a probability."
        ),
    )
    generate.add_argument(
        "source",
        metavar="SOURCE",
        help="Local video path or supported source URL.",
    )
    generate.add_argument(
        "--output-dir",
        type=_path_argument,
        default=DEFAULT_OUTPUT_DIR,
        metavar="PATH",
        help="Directory for run artifacts and final clips.",
    )
    generate.add_argument(
        "--lang",
        dest="language",
        default="auto",
        metavar="CODE|auto",
        help="Requested source language, or auto for provider detection.",
    )
    generate.add_argument(
        "--clips",
        type=int,
        default=DEFAULT_CLIPS,
        metavar="INTEGER",
        help="Maximum number of selected clips.",
    )
    generate.add_argument(
        "--min-score",
        type=int,
        default=DEFAULT_MIN_SCORE,
        metavar="INTEGER",
        help="Minimum ranking score from 0 to 100.",
    )
    generate.add_argument(
        "--min-duration",
        type=float,
        default=15.0,
        metavar="SECONDS",
        help="Minimum candidate duration in seconds.",
    )
    generate.add_argument(
        "--max-duration",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="Maximum candidate duration in seconds.",
    )
    generate.add_argument(
        "--aspect-ratio",
        default=DEFAULT_ASPECT_RATIO,
        metavar="original|9:16",
        help="Output presentation geometry.",
    )
    generate.add_argument(
        "--subtitle-template",
        default=DEFAULT_SUBTITLE_TEMPLATE,
        metavar="NAME",
        help="Built-in or custom multisubs template name.",
    )
    generate.add_argument(
        "--subtitle-template-dir",
        type=_path_argument,
        default=None,
        metavar="PATH",
        help="Directory containing custom subtitle templates.",
    )
    generate.add_argument(
        "--scorer",
        default=DEFAULT_SCORER,
        metavar="NAME",
        help="Scoring strategy name.",
    )
    generate.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        metavar="NAME",
        help="Provider model name.",
    )
    generate.add_argument(
        "--keep-intermediates",
        action="store_true",
        help="Keep useful intermediate artifacts for diagnostics.",
    )
    generate.add_argument(
        "--force-recompute",
        action="store_true",
        help="Ignore reusable artifacts and recompute stages.",
    )
    generate.add_argument(
        "--verbose",
        action="store_true",
        help="Enable diagnostic output for the run.",
    )
    return parser


def parse_run_config(argv: Sequence[str] | None = None) -> RunConfig:
    """Parse ``argv`` and validate it as one project-owned run configuration."""
    arguments = build_parser().parse_args(argv)
    return RunConfig(
        source=arguments.source,
        output_dir=arguments.output_dir,
        clips=arguments.clips,
        min_score=arguments.min_score,
        aspect_ratio=arguments.aspect_ratio,
        subtitle_template=arguments.subtitle_template,
        scorer=arguments.scorer,
        model=arguments.model,
        language=arguments.language,
        min_duration=arguments.min_duration,
        max_duration=arguments.max_duration,
        subtitle_template_dir=arguments.subtitle_template_dir,
        keep_intermediates=arguments.keep_intermediates,
        force_recompute=arguments.force_recompute,
        verbose=arguments.verbose,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    pipeline: PipelineRunner | None = None,
) -> int:
    """Parse one command and hand its configuration to the pipeline boundary."""
    config = parse_run_config(argv)
    if pipeline is None:
        raise RuntimeError(
            "Pipeline orchestration is not available until the pipeline boundary "
            "is configured"
        )
    pipeline(config)
    return 0

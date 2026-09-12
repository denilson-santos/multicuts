"""Source transcription through the public multisubs package API."""

import importlib
import json
from dataclasses import dataclass
from pathlib import Path

from multicuts.errors import TranscriptionError


@dataclass(frozen=True, slots=True)
class TranscriptionArtifact:
    """Validated provider JSON location and source-transcription provenance."""

    json_path: Path
    provider_version: str
    language_requested: str | None


class MultisubsAdapter:
    """Run multisubs once for a source, retaining only its JSON artifact."""

    def transcribe_to_artifact(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
    ) -> TranscriptionArtifact:
        """Generate source artifacts inside the workspace and verify the JSON."""
        try:
            provider = importlib.import_module("multisubs")
            generate = provider.generate_transcriptions
            version = provider.__version__
        except Exception as exc:
            raise TranscriptionError(
                "multisubs public transcription API is unavailable; "
                "check the multisubs installation"
            ) from exc
        if not callable(generate) or not isinstance(version, str) or not version:
            raise TranscriptionError("multisubs public transcription API is invalid")

        workspace_root = workspace.expanduser().resolve(strict=False)
        output_dir = workspace_root / "multisubs"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            actual_output_dir = output_dir.resolve(strict=True)
        except OSError as exc:
            raise TranscriptionError(
                "Could not prepare the multisubs workspace; check its permissions"
            ) from exc
        if not actual_output_dir.is_relative_to(workspace_root):
            raise TranscriptionError(
                "multisubs workspace must stay inside the configured workspace"
            )

        model_options = {} if model == "default" else {"model_name": model}
        try:
            generated = generate(
                video_path,
                actual_output_dir,
                lang=language,
                task="transcribe",
                **model_options,
            )
        except Exception as exc:
            raise TranscriptionError(
                "multisubs could not transcribe the source; check its audio, "
                "language, and model compatibility"
            ) from exc

        if (
            not isinstance(generated, tuple)
            or len(generated) != 3
            or any(not isinstance(path, (str, Path)) for path in generated)
        ):
            raise TranscriptionError("multisubs returned invalid artifact paths")

        try:
            artifact_paths = tuple(
                Path(path).resolve(strict=True) for path in generated
            )
            if any(
                not path.is_relative_to(actual_output_dir) or not path.is_file()
                for path in artifact_paths
            ):
                raise TranscriptionError(
                    "multisubs artifacts must be files inside its workspace"
                )
            resolved_json = artifact_paths[0]
            with resolved_json.open(encoding="utf-8") as artifact_file:
                payload = json.load(artifact_file)
        except (OSError, UnicodeError, ValueError) as exc:
            raise TranscriptionError(
                "multisubs did not produce a readable JSON transcript"
            ) from exc
        if not isinstance(payload, dict) or not payload:
            raise TranscriptionError(
                "multisubs produced an empty or invalid JSON transcript"
            )

        return TranscriptionArtifact(
            json_path=resolved_json,
            provider_version=version,
            language_requested=language,
        )

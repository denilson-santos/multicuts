from collections.abc import Callable

import pytest

from multicuts.errors import (
    AcquisitionError,
    ArtifactError,
    ConfigurationError,
    MediaError,
    MulticutsError,
    RenderingError,
    ScoringError,
    TranscriptionError,
)

ERROR_TYPES: tuple[type[MulticutsError], ...] = (
    ConfigurationError,
    AcquisitionError,
    MediaError,
    TranscriptionError,
    ScoringError,
    RenderingError,
    ArtifactError,
)


@pytest.mark.parametrize("error_type", ERROR_TYPES)
def test_specific_errors_derive_from_project_error(
    error_type: type[MulticutsError],
) -> None:
    error = error_type("safe operation context")

    assert isinstance(error, MulticutsError)
    assert str(error) == "safe operation context"


@pytest.mark.parametrize("error_type", ERROR_TYPES)
def test_specific_errors_preserve_chained_cause(
    error_type: type[MulticutsError],
) -> None:
    def raise_provider_error() -> None:
        raise RuntimeError("provider token=secret")

    def translate_error(operation: Callable[[], None]) -> None:
        try:
            operation()
        except RuntimeError as exc:
            raise error_type("Could not process source.mp4") from exc

    with pytest.raises(error_type, match=r"^Could not process source\.mp4$") as caught:
        translate_error(raise_provider_error)

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "secret" not in str(caught.value)

"""Project exception hierarchy."""


class MulticutsError(Exception):
    """Base exception for expected multicuts failures."""


class ConfigurationError(MulticutsError):
    """Raised when run configuration is invalid."""


class AcquisitionError(MulticutsError):
    """Raised when a source cannot be acquired."""


class MediaError(MulticutsError):
    """Raised when media inspection or validation fails."""


class TranscriptionError(MulticutsError):
    """Raised when source transcription fails."""


class ScoringError(MulticutsError):
    """Raised when candidate scoring fails."""


class RenderingError(MulticutsError):
    """Raised when clip or subtitle rendering fails."""


class ArtifactError(MulticutsError):
    """Raised when artifact persistence fails."""

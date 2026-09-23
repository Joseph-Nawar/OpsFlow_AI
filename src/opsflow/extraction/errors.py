"""Small, safe exception hierarchy for structured extraction."""


class ExtractionError(ValueError):
    """Base class for safe Phase 4 extraction failures."""


class ExtractionResponseError(ExtractionError):
    """The provider response is structurally invalid or ungrounded."""


class ProviderError(ExtractionError):
    """A provider or provider-adapter operation failed safely."""


class ProviderTimeoutError(ProviderError):
    """The configured provider timeout was reached."""


class ProviderUnavailableError(ProviderError):
    """The provider is temporarily unavailable."""

"""Domain-specific errors for supporting records."""


class DomainValidationError(ValueError):
    """Raised when a domain record violates a structural invariant."""

"""Bounded request correlation context."""

import re
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

_MAX_CORRELATION_LENGTH = 128
_SAFE_CORRELATION = re.compile(r"[A-Za-z0-9._:-]+", re.ASCII)


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    """Correlation metadata that is never business identity or authorization."""

    request_id: str
    workflow_execution_id: str | None = None


correlation_context: ContextVar[CorrelationContext | None] = ContextVar(
    "opsflow_correlation_context", default=None
)


def normalize_request_id(value: object) -> str | None:
    """Return a safe caller value, or None when a generated value is required."""

    return _normalize(value)


def normalize_workflow_execution_id(value: object) -> str | None:
    """Return a safe workflow execution value, or None when it must be omitted."""

    return _normalize(value)


def generate_request_id() -> str:
    """Generate a bounded UUID correlation value."""

    return str(uuid4())


def _normalize(value: object) -> str | None:
    if type(value) is not str:
        return None
    if not 1 <= len(value) <= _MAX_CORRELATION_LENGTH:
        return None
    if not value.isascii() or _SAFE_CORRELATION.fullmatch(value) is None:
        return None
    return value


__all__ = [
    "CorrelationContext",
    "correlation_context",
    "generate_request_id",
    "normalize_request_id",
    "normalize_workflow_execution_id",
]

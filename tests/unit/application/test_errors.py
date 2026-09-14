"""Unit tests for application-layer errors."""

import inspect

from opsflow.application.errors import IdempotencyConflictError, OrderNotFoundError


def test_order_not_found_error_is_http_independent() -> None:
    assert issubclass(OrderNotFoundError, Exception)
    assert "fastapi" not in inspect.getsource(OrderNotFoundError).lower()
    assert "http" not in inspect.getsource(OrderNotFoundError).lower()


def test_idempotency_conflict_error_keeps_key_without_http_dependency() -> None:
    error = IdempotencyConflictError("opaque-key")

    assert error.idempotency_key == "opaque-key"
    assert "fastapi" not in inspect.getsource(IdempotencyConflictError).lower()
    assert "http" not in inspect.getsource(IdempotencyConflictError).lower()

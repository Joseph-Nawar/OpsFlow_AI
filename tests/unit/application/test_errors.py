"""Unit tests for application-layer errors."""

import inspect

from opsflow.application.errors import OrderNotFoundError


def test_order_not_found_error_is_http_independent() -> None:
    assert issubclass(OrderNotFoundError, Exception)
    assert "fastapi" not in inspect.getsource(OrderNotFoundError).lower()
    assert "http" not in inspect.getsource(OrderNotFoundError).lower()

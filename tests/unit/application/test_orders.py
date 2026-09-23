"""Unit tests for the backward-compatible order creation disposition seam."""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

import opsflow.application.orders as orders_module
from opsflow.application.orders import (
    CreateOrderDisposition,
    CreateOrderInput,
    CreateOrderResult,
    create_order,
    create_order_with_disposition,
)
from opsflow.domain import Order
from opsflow.persistence.repositories import PersistedOrder


class _TransactionContext:
    async def __aenter__(self) -> "_TransactionContext":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _SessionStub:
    def begin(self) -> _TransactionContext:
        return _TransactionContext()


class _UniqueKeyViolation:
    constraint_name = "order_creation_idempotency_pkey"


def _persisted_order() -> PersistedOrder:
    return PersistedOrder(
        order=Order.received(uuid4()),
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
        validation_issues=(),
    )


def test_create_order_disposition_has_exact_values() -> None:
    assert CreateOrderDisposition.CREATED_BY_THIS_COMMAND.value == "CREATED_BY_THIS_COMMAND"
    assert CreateOrderDisposition.REPLAYED_EXISTING.value == "REPLAYED_EXISTING"


def test_create_order_result_is_frozen_and_slotted() -> None:
    result = CreateOrderResult(
        persisted=_persisted_order(),
        disposition=CreateOrderDisposition.CREATED_BY_THIS_COMMAND,
    )

    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.disposition = CreateOrderDisposition.REPLAYED_EXISTING  # type: ignore[misc]


def test_new_creation_reports_created_by_this_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orders_module, "insert_order_graph", _async_noop)
    monkeypatch.setattr(orders_module, "insert_audit_event", _async_noop)
    monkeypatch.setattr(orders_module, "insert_idempotency_record", _async_noop)

    result = asyncio.run(
        create_order_with_disposition(_SessionStub(), CreateOrderInput(), "new-key")
    )

    assert result.disposition is CreateOrderDisposition.CREATED_BY_THIS_COMMAND
    assert isinstance(result.persisted, PersistedOrder)


def test_same_fingerprint_race_reports_replayed_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted = _persisted_order()

    async def conflicting_insert(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise IntegrityError(None, None, _UniqueKeyViolation())

    async def resolve_race(*args: object, **kwargs: object) -> PersistedOrder:
        del args, kwargs
        return persisted

    monkeypatch.setattr(orders_module, "insert_order_graph", _async_noop)
    monkeypatch.setattr(orders_module, "insert_audit_event", _async_noop)
    monkeypatch.setattr(orders_module, "insert_idempotency_record", conflicting_insert)
    monkeypatch.setattr(orders_module, "_resolve_idempotency_race", resolve_race)

    result = asyncio.run(
        create_order_with_disposition(_SessionStub(), CreateOrderInput(), "existing-key")
    )

    assert result.disposition is CreateOrderDisposition.REPLAYED_EXISTING
    assert result.persisted is persisted


def test_create_order_compatibility_wrapper_returns_persisted_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted = _persisted_order()

    async def disposition_authority(*args: object, **kwargs: object) -> CreateOrderResult:
        del args, kwargs
        return CreateOrderResult(
            persisted=persisted,
            disposition=CreateOrderDisposition.REPLAYED_EXISTING,
        )

    monkeypatch.setattr(orders_module, "create_order_with_disposition", disposition_authority)

    result = asyncio.run(create_order(_SessionStub(), CreateOrderInput(), "compat-key"))

    assert result is persisted
    assert isinstance(result, PersistedOrder)


async def _async_noop(*args: object, **kwargs: object) -> None:
    del args, kwargs

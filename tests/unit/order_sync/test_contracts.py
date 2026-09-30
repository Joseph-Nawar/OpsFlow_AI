"""Validation tests for immutable Phase 9 synchronization contracts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from opsflow.application.order_sync import next_order_sync_step
from opsflow.domain import OrderState
from opsflow.order_sync.contracts import (
    ExecuteNextKind,
    OrderSync,
    OrderSyncExecutionResult,
    OrderSyncFailureCode,
    OrderSyncStep,
)

_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _sync(**overrides: object) -> OrderSync:
    values: dict[str, object] = {
        "order_id": uuid4(),
        "claim_token": None,
        "claim_expires_at": None,
        "attempt_count": 0,
        "retry_generation": 0,
        "next_attempt_at": _NOW,
        "odoo_sale_order_id": None,
        "odoo_sale_order_name": None,
        "hubspot_company_id": None,
        "hubspot_deal_id": None,
        "hubspot_association_confirmed_at": None,
        "in_flight_step": None,
        "last_failure_step": None,
        "last_failure_code": None,
        "last_attempt_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return OrderSync(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("attempt_count", (0, 3))
def test_attempt_count_includes_both_allowed_bounds(attempt_count: int) -> None:
    assert _sync(attempt_count=attempt_count).attempt_count == attempt_count


def test_retry_generation_is_unbounded_above_zero() -> None:
    assert _sync(retry_generation=10_000).retry_generation == 10_000


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("attempt_count", -1),
        ("attempt_count", 4),
        ("attempt_count", True),
        ("retry_generation", -1),
        ("retry_generation", True),
        ("claim_token", uuid4()),
        ("in_flight_step", "RAW_PROVIDER_METHOD"),
        ("last_failure_code", "RAW_PROVIDER_ERROR"),
        ("odoo_sale_order_id", -1),
        ("odoo_sale_order_name", "S00001"),
    ),
)
def test_order_sync_rejects_invalid_contract_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _sync(**{field: value})


def test_failure_code_requires_matching_bounded_step() -> None:
    with pytest.raises(ValueError):
        _sync(last_failure_code=OrderSyncFailureCode.PROVIDER_UNAVAILABLE)
    with pytest.raises(ValueError):
        _sync(last_failure_step=OrderSyncStep.HUBSPOT_DEAL)


def test_execution_result_is_bounded_and_has_authoritative_state() -> None:
    result = OrderSyncExecutionResult(
        kind=ExecuteNextKind.COMPLETED,
        order_id=uuid4(),
        state=OrderState.COMPLETED,
    )
    assert result.kind is ExecuteNextKind.COMPLETED
    with pytest.raises(ValueError):
        OrderSyncExecutionResult(ExecuteNextKind.NO_WORK, uuid4(), None)


@pytest.mark.parametrize(
    ("overrides", "lookup_succeeded", "expected"),
    (
        ({}, False, OrderSyncStep.ODOO_LOOKUP),
        ({}, True, OrderSyncStep.ODOO_BRIDGE),
        (
            {"odoo_sale_order_id": 1, "odoo_sale_order_name": "S00001"},
            False,
            OrderSyncStep.HUBSPOT_COMPANY,
        ),
        (
            {
                "odoo_sale_order_id": 1,
                "odoo_sale_order_name": "S00001",
                "hubspot_company_id": "company-1",
            },
            False,
            OrderSyncStep.HUBSPOT_DEAL,
        ),
        (
            {
                "odoo_sale_order_id": 1,
                "odoo_sale_order_name": "S00001",
                "hubspot_company_id": "company-1",
                "hubspot_deal_id": "deal-1",
            },
            False,
            OrderSyncStep.HUBSPOT_ASSOCIATION,
        ),
        (
            {
                "odoo_sale_order_id": 1,
                "odoo_sale_order_name": "S00001",
                "hubspot_company_id": "company-1",
                "hubspot_deal_id": "deal-1",
                "hubspot_association_confirmed_at": _NOW,
            },
            False,
            None,
        ),
    ),
)
def test_next_step_is_first_missing_receipt(
    overrides: dict[str, object],
    lookup_succeeded: bool,
    expected: OrderSyncStep | None,
) -> None:
    assert next_order_sync_step(_sync(**overrides), lookup_succeeded=lookup_succeeded) is expected


def test_uncertain_odoo_bridge_resumes_without_repeating_lookup() -> None:
    sync = _sync(in_flight_step=OrderSyncStep.ODOO_BRIDGE)
    assert next_order_sync_step(sync) is OrderSyncStep.ODOO_BRIDGE

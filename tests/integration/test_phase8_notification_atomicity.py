"""PostgreSQL transaction proofs for all seven notification trigger paths."""

import asyncio
from decimal import Decimal

import pytest
from test_phase5_application import _assert_final_write_failure_stage
from test_phase6_commands import _assert_approval_notification_failure_rolls_back
from test_phase6_revalidation import (
    _assert_final_write_stage_rolls_back,
    _draft_body,
)
from test_phase7_failure_matrix import _assert_notification_failure_rollback

from opsflow.domain import OrderState


@pytest.mark.parametrize("quantity", [Decimal("2"), None], ids=["approval-ready", "needs-review"])
def test_validation_notification_insert_failure_rolls_back_transition_event_and_intent(
    monkeypatch: pytest.MonkeyPatch,
    quantity: Decimal | None,
) -> None:
    asyncio.run(
        _assert_final_write_failure_stage(
            monkeypatch,
            "notification",
            quantity=quantity,
        )
    )


@pytest.mark.parametrize(
    "candidate",
    [
        _draft_body(po_number="PO-101", sku="SKU-MISSING"),
        _draft_body(po_number="PO-HIGH", sku="SKU-HV", quantity="50", submitted_price="25"),
    ],
    ids=["remains-needs-review", "ready-after-human-correction"],
)
def test_revalidation_notification_insert_failure_rolls_back_revision_and_order_writes(
    monkeypatch: pytest.MonkeyPatch,
    candidate: dict[str, str],
) -> None:
    asyncio.run(
        _assert_final_write_stage_rolls_back(
            monkeypatch,
            "create_notification_intent",
            candidate,
        )
    )


@pytest.mark.parametrize("origin", [OrderState.PROCESSING, OrderState.EXTRACTED])
def test_failure_notification_insert_failure_rolls_back_transition_and_audit(
    monkeypatch: pytest.MonkeyPatch,
    origin: OrderState,
) -> None:
    asyncio.run(_assert_notification_failure_rollback(monkeypatch, origin))


def test_approval_notification_insert_failure_rolls_back_transition_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_approval_notification_failure_rolls_back(monkeypatch))

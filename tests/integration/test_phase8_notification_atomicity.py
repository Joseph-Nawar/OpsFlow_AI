"""PostgreSQL transaction proofs for all seven notification trigger paths."""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from test_phase5_application import _assert_final_write_failure_stage
from test_phase6_commands import (
    APPROVER_TOKEN,
    _assert_approval_notification_failure_rolls_back,
    _case,
    _command_client,
    _etag_from_detail,
    _get_detail,
    _post_command,
    _read_order_and_audits,
)
from test_phase6_revalidation import (
    _assert_final_write_stage_rolls_back,
    _draft_body,
)
from test_phase7_failure_matrix import _assert_notification_failure_rollback

from opsflow.application import review_commands
from opsflow.domain import OrderState
from opsflow.persistence.models import NotificationDeliveryModel, SourceDocumentModel


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


def test_gmail_approval_intents_roll_back_together_with_transition_and_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_gmail_approval_intents_roll_back(monkeypatch))


async def _assert_gmail_approval_intents_roll_back(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case(OrderState.READY_FOR_APPROVAL)
    original_create = review_commands.create_notification_intent
    writes = 0

    async def fail_after_both_intents(*args: object, **kwargs: object) -> None:
        nonlocal writes
        writes += 1
        await original_create(*args, **kwargs)
        if writes == 2:
            raise IntegrityError(
                "synthetic Gmail intent failure", {}, RuntimeError("private detail")
            )

    monkeypatch.setattr(review_commands, "create_notification_intent", fail_after_both_intents)
    async with _command_client((case,)) as (client, session_factory, _):
        async with session_factory() as session, session.begin():
            await session.execute(
                update(SourceDocumentModel)
                .where(SourceDocumentModel.id == case.source_id)
                .values(
                    message_id="synthetic-gmail-approval",
                    metadata_=[["source_system", "GMAIL"]],
                )
            )

        detail = await _get_detail(client, case.order_id, APPROVER_TOKEN)
        before_order, before_audits = await _read_order_and_audits(session_factory, case.order_id)
        response = await _post_command(
            client,
            "approve",
            case.order_id,
            APPROVER_TOKEN,
            _etag_from_detail(detail),
        )
        after_order, after_audits = await _read_order_and_audits(session_factory, case.order_id)
        async with session_factory() as session:
            notification_count = await session.scalar(
                select(func.count())
                .select_from(NotificationDeliveryModel)
                .where(NotificationDeliveryModel.order_id == case.order_id)
            )

    assert writes == 2
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVIEW_PERSISTENCE_CONFLICT"
    assert "private detail" not in response.text
    assert after_order == before_order
    assert after_audits == before_audits
    assert notification_count == 0

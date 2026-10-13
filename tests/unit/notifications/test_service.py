"""Deterministic retry policy for durable notification outcomes."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from opsflow.domain import AuditEvent, Order, OrderState, SourceDocument, SourceDocumentType
from opsflow.notifications.contracts import NotificationChannel, NotificationKind
from opsflow.notifications.service import (
    _retry_delay_seconds,
    create_notification_intent,
)
from opsflow.persistence.models import NotificationDeliveryModel


class _CaptureSession:
    def __init__(self) -> None:
        self.rows: list[NotificationDeliveryModel] = []

    def add(self, row: NotificationDeliveryModel) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        return None


def _completion_order(*, gmail_source: bool, state: OrderState = OrderState.COMPLETED) -> Order:
    sources = ()
    if gmail_source:
        sources = (
            SourceDocument(
                id=uuid4(),
                document_type=SourceDocumentType.EMAIL_BODY,
                name="synthetic-email.txt",
                mime_type="text/plain",
                sha256="a" * 64,
                message_id="original-gmail-message-id",
                storage_reference=None,
                metadata=(("source_system", "GMAIL"),),
            ),
        )
    return Order(id=uuid4(), source_documents=sources, state=state)


def _completion_event(order: Order) -> AuditEvent:
    return AuditEvent(
        id=uuid4(),
        order_id=order.id,
        event_type="ORDER_SYNC_COMPLETED",
        actor="opsflow-order-sync",
        occurred_at=datetime(2026, 10, 13, 12, tzinfo=UTC),
        description="All required ERP and CRM synchronization receipts are durable.",
    )


@pytest.mark.parametrize(
    ("attempt", "slack", "hint", "expected"),
    [
        (1, False, None, 30),
        (2, False, 300, 120),
        (1, True, None, 30),
        (1, True, 0, 30),
        (1, True, 60, 60),
        (2, True, 30, 120),
        (2, True, 121, 121),
        (2, True, 300, 300),
    ],
)
def test_retry_delay_uses_backend_schedule_and_bounded_slack_hint(
    attempt: int,
    slack: bool,
    hint: int | None,
    expected: int,
) -> None:
    assert _retry_delay_seconds(attempt, slack=slack, retry_after_seconds=hint) == expected


@pytest.mark.parametrize("hint", [-1, 301, True])
def test_service_rejects_invalid_retry_hints_even_beyond_api_validation(hint: object) -> None:
    with pytest.raises(ValueError):
        _retry_delay_seconds(1, slack=True, retry_after_seconds=hint)  # type: ignore[arg-type]


def test_completed_non_gmail_order_can_create_slack_completion_intent() -> None:
    asyncio.run(_completed_non_gmail_order_can_create_slack_completion_intent())


async def _completed_non_gmail_order_can_create_slack_completion_intent() -> None:
    order = _completion_order(gmail_source=False)
    event = _completion_event(order)
    session = _CaptureSession()

    await create_notification_intent(
        session,
        order=order,
        event=event,
        channel=NotificationChannel.SLACK,
        kind=NotificationKind.ORDER_SYNC_COMPLETED,
        review_base_url="http://localhost:5173",
    )

    assert len(session.rows) == 1
    row = session.rows[0]
    assert row.order_id == order.id
    assert row.trigger_audit_event_id == event.id
    assert row.channel == "SLACK" and row.kind == "ORDER_SYNC_COMPLETED"
    assert row.payload["state"] == "COMPLETED"
    assert "synchronization completed" in row.payload["summary"].lower()


def test_gmail_completion_reply_requires_persisted_gmail_provenance() -> None:
    asyncio.run(_gmail_completion_reply_requires_persisted_gmail_provenance())


async def _gmail_completion_reply_requires_persisted_gmail_provenance() -> None:
    order = _completion_order(gmail_source=False)
    event = _completion_event(order)
    session = _CaptureSession()

    with pytest.raises(ValueError, match="Gmail"):
        await create_notification_intent(
            session,
            order=order,
            event=event,
            channel=NotificationChannel.GMAIL,
            kind=NotificationKind.ORDER_SYNC_COMPLETED,
            review_base_url="http://localhost:5173",
        )
    assert session.rows == []


def test_completion_intent_rejects_order_not_in_completed_state() -> None:
    asyncio.run(_completion_intent_rejects_order_not_completed())


async def _completion_intent_rejects_order_not_completed() -> None:
    order = _completion_order(gmail_source=False, state=OrderState.SYNCING)
    event = _completion_event(order)
    session = _CaptureSession()

    with pytest.raises(ValueError, match="completed synchronization"):
        await create_notification_intent(
            session,
            order=order,
            event=event,
            channel=NotificationChannel.SLACK,
            kind=NotificationKind.ORDER_SYNC_COMPLETED,
            review_base_url="http://localhost:5173",
        )
    assert session.rows == []


def test_gmail_completion_reply_uses_original_message_id_and_completion_event() -> None:
    asyncio.run(_gmail_completion_reply_uses_original_message_id_and_completion_event())


async def _gmail_completion_reply_uses_original_message_id_and_completion_event() -> None:
    order = _completion_order(gmail_source=True)
    event = _completion_event(order)
    session = _CaptureSession()

    await create_notification_intent(
        session,
        order=order,
        event=event,
        channel=NotificationChannel.GMAIL,
        kind=NotificationKind.ORDER_SYNC_COMPLETED,
        review_base_url="http://localhost:5173",
    )

    assert len(session.rows) == 1
    row = session.rows[0]
    assert row.order_id == order.id
    assert row.trigger_audit_event_id == event.id
    assert row.channel == "GMAIL" and row.kind == "ORDER_SYNC_COMPLETED"
    assert row.payload["message_id"] == "original-gmail-message-id"
    assert "synchronization is complete" in row.payload["body"].lower()

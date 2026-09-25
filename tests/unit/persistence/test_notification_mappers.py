"""Round-trip and defensive-copy tests for notification persistence mapping."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from opsflow.domain import DomainValidationError
from opsflow.notifications.contracts import (
    NotificationChannel,
    NotificationDelivery,
    NotificationKind,
    NotificationStatus,
)
from opsflow.persistence.mappers import (
    notification_delivery_from_model,
    notification_delivery_to_model,
)
from opsflow.persistence.models import NotificationDeliveryModel


def _delivery() -> NotificationDelivery:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    return NotificationDelivery(
        id=uuid4(),
        order_id=uuid4(),
        trigger_audit_event_id=uuid4(),
        channel=NotificationChannel.GMAIL,
        kind=NotificationKind.ORDER_APPROVED,
        payload={"message_id": "gmail-message-1", "body": "Approved for processing."},
        status=NotificationStatus.PENDING,
        attempt_count=0,
        claim_token=None,
        claim_expires_at=None,
        next_attempt_at=now,
        provider_reference=None,
        last_failure_code=None,
        created_at=now,
        updated_at=now,
    )


def test_notification_mapper_round_trips_delivery_and_copies_json_payload() -> None:
    delivery = _delivery()

    row = notification_delivery_to_model(delivery)
    restored = notification_delivery_from_model(row)
    row.payload["body"] = "changed"

    assert restored == delivery
    assert row.payload == {
        "message_id": "gmail-message-1",
        "body": "changed",
    }
    assert delivery.payload["body"] == "Approved for processing."


def test_notification_mapper_rejects_wrong_model_and_malformed_payload() -> None:
    with pytest.raises(DomainValidationError, match="NotificationDeliveryModel"):
        notification_delivery_from_model(object())  # type: ignore[arg-type]

    row = notification_delivery_to_model(_delivery())
    row.payload = ["not", "an", "object"]

    with pytest.raises(DomainValidationError):
        notification_delivery_from_model(row)


def test_notification_mapper_rejects_naive_persisted_timestamp() -> None:
    row = notification_delivery_to_model(_delivery())
    row.created_at = datetime(2026, 9, 25, 12, 0)

    with pytest.raises(DomainValidationError):
        notification_delivery_from_model(row)


def test_notification_model_is_registered_in_shared_metadata() -> None:
    assert NotificationDeliveryModel.__tablename__ == "notification_deliveries"

"""Immutable notification delivery contracts and payload bounds."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from opsflow.notifications.contracts import (
    NotificationChannel,
    NotificationDelivery,
    NotificationFailureCode,
    NotificationKind,
    NotificationOutcome,
    NotificationOutcomeKind,
    NotificationStatus,
)


def _delivery(payload: object) -> NotificationDelivery:
    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    return NotificationDelivery(
        id=uuid4(),
        order_id=uuid4(),
        trigger_audit_event_id=uuid4(),
        channel=NotificationChannel.SLACK,
        kind=NotificationKind.REVIEW_REQUIRED,
        payload=payload,
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


def test_notification_enum_values_match_phase8_contract() -> None:
    assert [value.value for value in NotificationChannel] == ["SLACK", "GMAIL"]
    assert [value.value for value in NotificationKind] == [
        "REVIEW_REQUIRED",
        "APPROVAL_READY",
        "PROCESSING_FAILED",
        "ORDER_APPROVED",
    ]
    assert [value.value for value in NotificationStatus] == [
        "PENDING",
        "CLAIMED",
        "DELIVERED",
        "FAILED_FINAL",
    ]
    assert [value.value for value in NotificationOutcomeKind] == ["DELIVERED", "FAILED"]
    assert [value.value for value in NotificationFailureCode] == [
        "RATE_LIMITED",
        "AUTHENTICATION_FAILED",
        "PERMISSION_DENIED",
        "TARGET_NOT_FOUND",
        "PROVIDER_UNAVAILABLE",
        "TIMEOUT",
        "DELIVERY_REJECTED",
        "UNKNOWN_FAILURE",
    ]


def test_notification_records_are_frozen() -> None:
    delivery = _delivery({"text": "safe"})
    outcome = NotificationOutcome(
        claim_token=uuid4(),
        kind=NotificationOutcomeKind.DELIVERED,
        provider_reference="provider-message-1",
    )

    with pytest.raises(FrozenInstanceError):
        delivery.attempt_count = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        outcome.kind = NotificationOutcomeKind.FAILED  # type: ignore[misc]


def test_notification_payload_accepts_a_json_object_and_copies_it() -> None:
    payload = {"text": "safe", "nested": {"count": 2}}

    delivery = _delivery(payload)
    payload["text"] = "changed"
    payload["nested"]["count"] = 3

    assert delivery.payload == {"text": "safe", "nested": {"count": 2}}


@pytest.mark.parametrize("payload", [[], ["x"], "text", 3, None])
def test_notification_payload_rejects_non_object_json(payload: object) -> None:
    with pytest.raises(ValueError):
        _delivery(payload)


def test_notification_payload_enforces_compact_utf8_limit_at_exact_boundary() -> None:
    exact_payload = {"x": "a" * (16 * 1024 - 8)}
    over_payload = {"x": "a" * (16 * 1024 - 7)}

    assert len(b'{"x":"' + b"a" * (16 * 1024 - 8) + b'"}') == 16 * 1024
    assert _delivery(exact_payload).payload == exact_payload
    with pytest.raises(ValueError, match="16 KiB"):
        _delivery(over_payload)


def test_notification_payload_counts_utf8_bytes_not_codepoints() -> None:
    payload = {"x": "é" * 100}

    delivery = _delivery(payload)

    assert delivery.payload == payload
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    assert len(encoded.encode("utf-8")) > len(encoded)

"""Strict transport contracts for the durable notification API."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from opsflow.api.notification_schemas import (
    NotificationClaimResponse,
    NotificationOutcomeRequest,
    NotificationOutcomeResponse,
)


def _delivered(**overrides: object) -> dict[str, object]:
    return {"claim_token": str(UUID(int=1)), "outcome": "DELIVERED", **overrides}


def _failed(**overrides: object) -> dict[str, object]:
    return {
        "claim_token": str(UUID(int=1)),
        "outcome": "FAILED",
        "failure_code": "TIMEOUT",
        **overrides,
    }


def test_outcome_schema_accepts_the_two_bounded_shapes() -> None:
    delivered = NotificationOutcomeRequest.model_validate(
        _delivered(provider_reference="provider-123")
    )
    failed = NotificationOutcomeRequest.model_validate(_failed(retry_after_seconds=120))

    assert delivered.outcome == "DELIVERED"
    assert delivered.provider_reference == "provider-123"
    assert failed.failure_code == "TIMEOUT"
    assert failed.retry_after_seconds == 120


@pytest.mark.parametrize(
    "payload",
    [
        _delivered(failure_code="TIMEOUT"),
        _delivered(retry_after_seconds=10),
        _failed(provider_reference="must-not-be-accepted"),
        {"claim_token": str(UUID(int=1)), "outcome": "FAILED"},
        _failed(failure_code="raw provider error"),
        _delivered(provider_error="secret provider body"),
        _failed(provider_body={"message": "secret"}),
    ],
)
def test_outcome_schema_rejects_wrong_shape_unknown_fields_and_provider_bodies(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        NotificationOutcomeRequest.model_validate(payload)


@pytest.mark.parametrize("value", [True, 1.0, "1", -1, 301])
def test_retry_after_is_a_strict_integer_bounded_to_five_minutes(value: object) -> None:
    with pytest.raises(ValidationError):
        NotificationOutcomeRequest.model_validate(_failed(retry_after_seconds=value))


def test_all_allowlisted_failure_codes_are_accepted() -> None:
    codes = (
        "RATE_LIMITED",
        "AUTHENTICATION_FAILED",
        "PERMISSION_DENIED",
        "TARGET_NOT_FOUND",
        "PROVIDER_UNAVAILABLE",
        "TIMEOUT",
        "DELIVERY_REJECTED",
        "UNKNOWN_FAILURE",
    )

    for code in codes:
        request = NotificationOutcomeRequest.model_validate(_failed(failure_code=code))
        assert request.failure_code == code


def test_claim_and_outcome_responses_have_only_the_approved_fields() -> None:
    expires = datetime(2030, 1, 1, tzinfo=UTC)
    claim = NotificationClaimResponse(
        notification_id=UUID(int=2),
        channel="SLACK",
        kind="REVIEW_REQUIRED",
        payload={"text": "safe"},
        attempt_number=1,
        claim_token=UUID(int=3),
        claim_expires_at=expires,
    )
    outcome = NotificationOutcomeResponse(
        notification_id=UUID(int=2),
        status="DELIVERED",
        attempt_count=1,
        next_attempt_at=expires,
        provider_reference="provider-123",
        failure_code=None,
    )

    assert set(claim.model_dump()) == {
        "notification_id",
        "channel",
        "kind",
        "payload",
        "attempt_number",
        "claim_token",
        "claim_expires_at",
    }
    assert set(outcome.model_dump()) == {
        "notification_id",
        "status",
        "attempt_count",
        "next_attempt_at",
        "provider_reference",
        "failure_code",
    }
    with pytest.raises(ValidationError):
        NotificationClaimResponse.model_validate({**claim.model_dump(), "provider_error": "x"})

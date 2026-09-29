"""Immutable contracts for persisted notification delivery and service outcomes."""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

_MAX_PAYLOAD_BYTES = 16 * 1024
_MAX_PROVIDER_REFERENCE_LENGTH = 256
_MAX_RETRY_AFTER_SECONDS = 300


class NotificationChannel(StrEnum):
    """External delivery channel selected by backend policy."""

    SLACK = "SLACK"
    GMAIL = "GMAIL"


class NotificationKind(StrEnum):
    """Supported business-event notification kinds."""

    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVAL_READY = "APPROVAL_READY"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    ORDER_APPROVED = "ORDER_APPROVED"


class NotificationStatus(StrEnum):
    """Durable state of one notification intent."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    FAILED_FINAL = "FAILED_FINAL"


class NotificationOutcomeKind(StrEnum):
    """Bounded result reported by a transport worker."""

    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class NotificationFailureCode(StrEnum):
    """Allowlisted provider outcome with no provider diagnostics."""

    RATE_LIMITED = "RATE_LIMITED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    DELIVERY_REJECTED = "DELIVERY_REJECTED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


@dataclass(frozen=True, slots=True)
class NotificationDelivery:
    """Immutable application representation of one persisted notification intent."""

    id: UUID
    order_id: UUID
    trigger_audit_event_id: UUID
    channel: NotificationChannel
    kind: NotificationKind
    payload: dict[str, object]
    status: NotificationStatus
    attempt_count: int
    claim_token: UUID | None
    claim_expires_at: datetime | None
    next_attempt_at: datetime
    provider_reference: str | None
    last_failure_code: NotificationFailureCode | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_uuid(self.order_id, "order_id")
        _require_uuid(self.trigger_audit_event_id, "trigger_audit_event_id")
        if not isinstance(self.channel, NotificationChannel):
            raise ValueError("channel must be a NotificationChannel")
        if not isinstance(self.kind, NotificationKind):
            raise ValueError("kind must be a NotificationKind")
        if not isinstance(self.status, NotificationStatus):
            raise ValueError("status must be a NotificationStatus")
        if type(self.attempt_count) is not int or not 0 <= self.attempt_count <= 3:
            raise ValueError("attempt_count must be an integer from 0 through 3")
        if self.status is NotificationStatus.CLAIMED:
            if not isinstance(self.claim_token, UUID) or self.claim_expires_at is None:
                raise ValueError("CLAIMED delivery requires both claim fields")
            _require_aware(self.claim_expires_at, "claim_expires_at")
            if self.attempt_count == 0:
                raise ValueError("CLAIMED delivery must have at least one attempt")
        elif self.claim_token is not None or self.claim_expires_at is not None:
            raise ValueError("non-CLAIMED delivery must clear both claim fields")
        _require_aware(self.next_attempt_at, "next_attempt_at")
        _require_aware(self.created_at, "created_at")
        _require_aware(self.updated_at, "updated_at")
        if self.provider_reference is not None:
            _require_bounded_string(
                self.provider_reference,
                "provider_reference",
                _MAX_PROVIDER_REFERENCE_LENGTH,
            )
        if self.last_failure_code is not None and not isinstance(
            self.last_failure_code, NotificationFailureCode
        ):
            raise ValueError("last_failure_code must be an allowlisted NotificationFailureCode")
        object.__setattr__(self, "payload", _copy_payload(self.payload))


@dataclass(frozen=True, slots=True)
class NotificationClaim:
    """Single lease generation returned to the authenticated transport worker."""

    notification_id: UUID
    channel: NotificationChannel
    kind: NotificationKind
    payload: dict[str, object]
    attempt_number: int
    claim_token: UUID
    claim_expires_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.notification_id, "notification_id")
        _require_uuid(self.claim_token, "claim_token")
        if not isinstance(self.channel, NotificationChannel):
            raise ValueError("channel must be a NotificationChannel")
        if not isinstance(self.kind, NotificationKind):
            raise ValueError("kind must be a NotificationKind")
        if type(self.attempt_number) is not int or not 1 <= self.attempt_number <= 3:
            raise ValueError("attempt_number must be an integer from 1 through 3")
        _require_aware(self.claim_expires_at, "claim_expires_at")
        object.__setattr__(self, "payload", _copy_payload(self.payload))


@dataclass(frozen=True, slots=True)
class NotificationOutcome:
    """Strict transport result accepted for the current claim token only."""

    claim_token: UUID
    kind: NotificationOutcomeKind
    provider_reference: str | None = None
    failure_code: NotificationFailureCode | None = None
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.claim_token, "claim_token")
        if not isinstance(self.kind, NotificationOutcomeKind):
            raise ValueError("kind must be a NotificationOutcomeKind")
        if self.kind is NotificationOutcomeKind.DELIVERED:
            if self.failure_code is not None or self.retry_after_seconds is not None:
                raise ValueError("DELIVERED outcome cannot contain failure fields")
            if self.provider_reference is not None:
                _require_bounded_string(
                    self.provider_reference,
                    "provider_reference",
                    _MAX_PROVIDER_REFERENCE_LENGTH,
                )
        else:
            if self.provider_reference is not None:
                raise ValueError("FAILED outcome cannot contain a provider reference")
            if not isinstance(self.failure_code, NotificationFailureCode):
                raise ValueError("FAILED outcome requires an allowlisted failure_code")
            if self.retry_after_seconds is not None and (
                type(self.retry_after_seconds) is not int
                or not 0 <= self.retry_after_seconds <= _MAX_RETRY_AFTER_SECONDS
            ):
                raise ValueError("retry_after_seconds must be an integer from 0 through 300")


@dataclass(frozen=True, slots=True)
class NotificationOutcomeResult:
    """Bounded persisted delivery state returned after a valid outcome."""

    notification_id: UUID
    status: NotificationStatus
    attempt_count: int
    next_attempt_at: datetime
    provider_reference: str | None
    last_failure_code: NotificationFailureCode | None

    def __post_init__(self) -> None:
        _require_uuid(self.notification_id, "notification_id")
        if not isinstance(self.status, NotificationStatus):
            raise ValueError("status must be a NotificationStatus")
        if type(self.attempt_count) is not int or not 1 <= self.attempt_count <= 3:
            raise ValueError("attempt_count must be an integer from 1 through 3")
        _require_aware(self.next_attempt_at, "next_attempt_at")
        if self.provider_reference is not None:
            _require_bounded_string(
                self.provider_reference,
                "provider_reference",
                _MAX_PROVIDER_REFERENCE_LENGTH,
            )
        if self.last_failure_code is not None and not isinstance(
            self.last_failure_code, NotificationFailureCode
        ):
            raise ValueError("last_failure_code must be an allowlisted failure code")


def _copy_payload(payload: object) -> dict[str, object]:
    """Validate and defensively copy a compact UTF-8 JSON object."""

    if not isinstance(payload, dict):
        raise ValueError("notification payload must be a JSON object")
    _validate_json_value(payload, "payload")
    try:
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        size = len(serialized.encode("utf-8"))
        if size > _MAX_PAYLOAD_BYTES:
            raise ValueError("notification payload exceeds the 16 KiB limit")
        normalized = json.loads(serialized)
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        if isinstance(error, ValueError) and "16 KiB" in str(error):
            raise
        raise ValueError("notification payload must contain only finite JSON values") from error
    if not isinstance(normalized, dict):
        raise ValueError("notification payload must be a JSON object")
    return normalized


def _validate_json_value(value: object, field_name: str) -> None:
    if value is None or type(value) in (str, int, bool):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains a non-finite JSON number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, field_name)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"{field_name} contains a non-string JSON key")
        for item in value.values():
            _validate_json_value(item, field_name)
        return
    raise ValueError(f"{field_name} contains a non-JSON value")


def _require_uuid(value: object, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{field_name} must be a UUID")


def _require_aware(value: object, field_name: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_bounded_string(value: object, field_name: str, maximum: int) -> None:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{field_name} must be a string of at most {maximum} characters")

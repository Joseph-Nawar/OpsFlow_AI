"""Strict, bounded request and response schemas for notification delivery."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from opsflow.notifications.contracts import (
    NotificationChannel,
    NotificationFailureCode,
    NotificationKind,
    NotificationOutcomeKind,
    NotificationStatus,
)


class NotificationClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: UUID
    channel: NotificationChannel
    kind: NotificationKind
    payload: dict[str, Any]
    attempt_number: int = Field(ge=1, le=3)
    claim_token: UUID
    claim_expires_at: datetime


class NotificationOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_token: UUID
    outcome: NotificationOutcomeKind
    provider_reference: str | None = Field(default=None, max_length=256)
    failure_code: NotificationFailureCode | None = None
    retry_after_seconds: StrictInt | None = Field(default=None, ge=0, le=300)

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> "NotificationOutcomeRequest":
        if self.outcome is NotificationOutcomeKind.DELIVERED:
            if self.failure_code is not None or self.retry_after_seconds is not None:
                raise ValueError("DELIVERED outcome cannot contain failure fields")
        else:
            if self.provider_reference is not None:
                raise ValueError("FAILED outcome cannot contain a provider reference")
            if self.failure_code is None:
                raise ValueError("FAILED outcome requires a failure code")
        return self


class NotificationOutcomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: UUID
    status: NotificationStatus
    attempt_count: int = Field(ge=1, le=3)
    next_attempt_at: datetime
    provider_reference: str | None = Field(max_length=256)
    failure_code: NotificationFailureCode | None

"""Focused strong review ETag generation and If-Match parsing."""

import hashlib
import re
from uuid import UUID

from opsflow.application.errors import (
    ReviewPreconditionFailedError,
    ReviewPreconditionRequiredError,
)
from opsflow.domain import OrderState

_STRONG_REVIEW_ETAG = re.compile(r'"[0-9a-f]{64}"', flags=re.ASCII)


def compute_review_etag(
    order_id: UUID,
    current_state: OrderState,
    failure_origin: OrderState | None,
    latest_review_revision_number: int | None,
    latest_review_revision_id: UUID | None,
    latest_audit_event_id: UUID | None,
) -> str:
    """Hash the canonical mutation generation into a quoted strong entity tag."""

    if not isinstance(order_id, UUID):
        raise ValueError("order_id must be a UUID")
    if not isinstance(current_state, OrderState):
        raise ValueError("current_state must be an OrderState")
    if failure_origin is not None and not isinstance(failure_origin, OrderState):
        raise ValueError("failure_origin must be an OrderState or None")
    if latest_review_revision_number is not None and (
        type(latest_review_revision_number) is not int or latest_review_revision_number <= 0
    ):
        raise ValueError("latest review revision number must be positive or None")
    if (latest_review_revision_number is None) != (latest_review_revision_id is None):
        raise ValueError("latest review revision number and ID must be jointly present or absent")
    if latest_review_revision_id is not None and not isinstance(latest_review_revision_id, UUID):
        raise ValueError("latest review revision ID must be a UUID or None")
    if latest_audit_event_id is not None and not isinstance(latest_audit_event_id, UUID):
        raise ValueError("latest audit event ID must be a UUID or None")

    canonical = " | ".join(
        (
            "review-state-v1",
            str(order_id),
            current_state.value,
            failure_origin.value if failure_origin is not None else "null",
            (
                str(latest_review_revision_number)
                if latest_review_revision_number is not None
                else "null"
            ),
            str(latest_review_revision_id) if latest_review_revision_id is not None else "null",
            str(latest_audit_event_id) if latest_audit_event_id is not None else "null",
        )
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f'"{digest}"'


def require_if_match(supplied: str | None, current: str) -> None:
    """Require exactly one current strong review validator."""

    if supplied is None:
        raise ReviewPreconditionRequiredError
    if (
        not isinstance(supplied, str)
        or _STRONG_REVIEW_ETAG.fullmatch(supplied) is None
        or _STRONG_REVIEW_ETAG.fullmatch(current) is None
        or supplied != current
    ):
        raise ReviewPreconditionFailedError

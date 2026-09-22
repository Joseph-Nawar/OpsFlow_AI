"""Strong review ETag and precondition contract tests."""

import hashlib
import inspect
import re
from uuid import UUID

import pytest

from opsflow.application.errors import (
    ReviewPreconditionFailedError,
    ReviewPreconditionRequiredError,
)
from opsflow.domain import OrderState
from opsflow.review.concurrency import compute_review_etag, require_if_match

ORDER_ID = UUID("11111111-1111-4111-8111-111111111111")
REVISION_ID = UUID("22222222-2222-4222-8222-222222222222")
AUDIT_ID = UUID("33333333-3333-4333-8333-333333333333")


def _etag(
    *,
    state: OrderState = OrderState.NEEDS_REVIEW,
    failure_origin: OrderState | None = None,
    revision_number: int | None = 1,
    revision_id: UUID | None = REVISION_ID,
    audit_id: UUID | None = AUDIT_ID,
) -> str:
    return compute_review_etag(
        ORDER_ID, state, failure_origin, revision_number, revision_id, audit_id
    )


def test_etag_is_quoted_lowercase_sha256_of_exact_canonical_input() -> None:
    canonical = (
        "review-state-v1 | 11111111-1111-4111-8111-111111111111 | NEEDS_REVIEW | null | "
        "1 | 22222222-2222-4222-8222-222222222222 | "
        "33333333-3333-4333-8333-333333333333"
    )

    result = _etag()

    assert result == f'"{hashlib.sha256(canonical.encode("utf-8")).hexdigest()}"'
    assert re.fullmatch(r'"[0-9a-f]{64}"', result)


def test_etag_uses_explicit_null_spelling_for_absent_generation_fields() -> None:
    canonical = (
        "review-state-v1 | 11111111-1111-4111-8111-111111111111 | FAILED_RETRYABLE | "
        "EXTRACTED | null | null | null"
    )

    result = compute_review_etag(
        ORDER_ID,
        OrderState.FAILED_RETRYABLE,
        OrderState.EXTRACTED,
        None,
        None,
        None,
    )

    assert result == f'"{hashlib.sha256(canonical.encode("utf-8")).hexdigest()}"'


@pytest.mark.parametrize(
    "changed",
    [
        {"revision_number": 2},
        {"revision_id": UUID("44444444-4444-4444-8444-444444444444")},
        {"audit_id": UUID("55555555-5555-4555-8555-555555555555")},
    ],
)
def test_persisted_review_mutation_generation_changes_etag(changed: dict[str, object]) -> None:
    values: dict[str, object] = {
        "state": OrderState.NEEDS_REVIEW,
        "failure_origin": None,
        "revision_number": 1,
        "revision_id": REVISION_ID,
        "audit_id": AUDIT_ID,
    }
    values.update(changed)

    updated = compute_review_etag(
        ORDER_ID,
        values["state"],  # type: ignore[arg-type]
        values["failure_origin"],  # type: ignore[arg-type]
        values["revision_number"],  # type: ignore[arg-type]
        values["revision_id"],  # type: ignore[arg-type]
        values["audit_id"],  # type: ignore[arg-type]
    )

    assert updated != _etag()


def test_approve_reject_and_retry_generations_invalidate_prior_etags() -> None:
    ready = compute_review_etag(
        ORDER_ID,
        OrderState.READY_FOR_APPROVAL,
        None,
        1,
        REVISION_ID,
        AUDIT_ID,
    )
    approved = compute_review_etag(
        ORDER_ID,
        OrderState.APPROVED,
        None,
        1,
        REVISION_ID,
        UUID("44444444-4444-4444-8444-444444444444"),
    )
    rejected = compute_review_etag(
        ORDER_ID,
        OrderState.REJECTED,
        None,
        1,
        REVISION_ID,
        UUID("55555555-5555-4555-8555-555555555555"),
    )
    failed = compute_review_etag(
        ORDER_ID,
        OrderState.FAILED_RETRYABLE,
        OrderState.EXTRACTED,
        None,
        None,
        AUDIT_ID,
    )
    retried = compute_review_etag(
        ORDER_ID,
        OrderState.EXTRACTED,
        None,
        None,
        None,
        UUID("66666666-6666-4666-8666-666666666666"),
    )

    assert approved != ready
    assert rejected != ready
    assert retried != failed


def test_retry_state_aba_cannot_revive_old_etag_after_new_audit_generation() -> None:
    old = compute_review_etag(
        ORDER_ID,
        OrderState.FAILED_RETRYABLE,
        OrderState.EXTRACTED,
        None,
        None,
        AUDIT_ID,
    )
    new_failure_audit_id = UUID("55555555-5555-4555-8555-555555555555")
    restored_state = compute_review_etag(
        ORDER_ID,
        OrderState.FAILED_RETRYABLE,
        OrderState.EXTRACTED,
        None,
        None,
        new_failure_audit_id,
    )

    assert restored_state != old
    with pytest.raises(ReviewPreconditionFailedError):
        require_if_match(old, restored_state)


@pytest.mark.parametrize("supplied", ['W/"weak"', "*", '"one", "two"', "bare", ""])
def test_if_match_rejects_weak_wildcard_multiple_and_malformed_values(supplied: str) -> None:
    with pytest.raises(ReviewPreconditionFailedError):
        require_if_match(supplied, _etag())


def test_if_match_distinguishes_missing_from_stale_and_accepts_exact_strong_match() -> None:
    current = _etag()

    with pytest.raises(ReviewPreconditionRequiredError):
        require_if_match(None, current)
    with pytest.raises(ReviewPreconditionFailedError):
        require_if_match('"' + "0" * 64 + '"', current)
    require_if_match(current, current)


def test_volatile_reference_data_is_not_an_etag_input() -> None:
    assert len(inspect.signature(compute_review_etag).parameters) == 6
    first_reference_data = {"catalogue_price": "10"}
    second_reference_data = {"catalogue_price": "25"}

    assert first_reference_data != second_reference_data
    assert _etag() == _etag()

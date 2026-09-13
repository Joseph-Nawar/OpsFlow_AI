from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from opsflow.domain import (
    DomainValidationError,
    InvalidStateTransitionError,
    Order,
    OrderLine,
    OrderState,
    SourceDocument,
    SourceDocumentType,
)

ORDER_ID = UUID(int=30)
LINE_ID = UUID(int=31)
DOCUMENT_ID = UUID(int=32)
SHA256 = "c" * 64
NON_LIFECYCLE_FIELDS = (
    "id",
    "customer_reference",
    "po_number",
    "order_date",
    "requested_delivery_date",
    "currency",
    "lines",
    "source_documents",
)


def make_order() -> Order:
    return Order.received(
        id=ORDER_ID,
        customer_reference="CUST-001",
        po_number="PO-001",
        order_date=date(2026, 9, 13),
        requested_delivery_date=date(2026, 10, 1),
        currency="ZZZ",
        lines=(
            OrderLine(
                LINE_ID,
                "SKU-001",
                "Widget",
                Decimal("2"),
                Decimal("10.00"),
                None,
            ),
        ),
        source_documents=(
            SourceDocument(
                DOCUMENT_ID,
                SourceDocumentType.PDF,
                "purchase-order.pdf",
                "application/pdf",
                SHA256,
                None,
                None,
                (),
            ),
        ),
    )


def assert_non_lifecycle_data_preserved(previous: Order, current: Order) -> None:
    for field_name in NON_LIFECYCLE_FIELDS:
        assert getattr(current, field_name) == getattr(previous, field_name)


def advance(order: Order, target: OrderState) -> Order:
    previous_state = order.state
    previous_failure_origin = order.failure_origin
    result = order.transition_to(target)

    assert result is not order
    assert result.state is target
    assert result.failure_origin is None
    assert_non_lifecycle_data_preserved(order, result)
    assert order.state is previous_state
    assert order.failure_origin is previous_failure_origin
    return result


def test_happy_path_reaches_terminal_completed_snapshot() -> None:
    order = make_order()
    states = [
        OrderState.PROCESSING,
        OrderState.EXTRACTED,
        OrderState.VALIDATED,
        OrderState.READY_FOR_APPROVAL,
        OrderState.APPROVED,
        OrderState.SYNCING,
        OrderState.COMPLETED,
    ]

    snapshots = [order]
    for target in states:
        previous = snapshots[-1]
        snapshots.append(advance(previous, target))
        assert previous.failure_origin is None

    completed = snapshots[-1]
    assert completed.state is OrderState.COMPLETED
    for target in OrderState:
        with pytest.raises(InvalidStateTransitionError):
            completed.transition_to(target)
    with pytest.raises(InvalidStateTransitionError):
        completed.retry()
    with pytest.raises(InvalidStateTransitionError):
        completed.reopen()


def test_review_and_revalidation_path_preserves_order_data() -> None:
    processing = advance(make_order(), OrderState.PROCESSING)
    extracted = advance(processing, OrderState.EXTRACTED)
    validated = advance(extracted, OrderState.VALIDATED)

    needs_review = advance(validated, OrderState.NEEDS_REVIEW)
    revalidated = advance(needs_review, OrderState.VALIDATED)
    ready = advance(revalidated, OrderState.READY_FOR_APPROVAL)

    assert needs_review.state is OrderState.NEEDS_REVIEW
    assert revalidated.state is OrderState.VALIDATED
    assert ready.state is OrderState.READY_FOR_APPROVAL


def test_rejection_requires_explicit_reopen_for_recovery() -> None:
    ready = advance(
        advance(
            advance(
                advance(make_order(), OrderState.PROCESSING),
                OrderState.EXTRACTED,
            ),
            OrderState.VALIDATED,
        ),
        OrderState.READY_FOR_APPROVAL,
    )
    rejected = advance(ready, OrderState.REJECTED)

    for target in (OrderState.NEEDS_REVIEW, OrderState.VALIDATED):
        with pytest.raises(InvalidStateTransitionError):
            rejected.transition_to(target)

    reopened = rejected.reopen()
    assert reopened is not rejected
    assert reopened.state is OrderState.NEEDS_REVIEW
    assert reopened.failure_origin is None
    assert_non_lifecycle_data_preserved(rejected, reopened)
    assert rejected.state is OrderState.REJECTED
    assert rejected.failure_origin is None

    revalidated = advance(reopened, OrderState.VALIDATED)
    ready_again = advance(revalidated, OrderState.READY_FOR_APPROVAL)
    assert ready_again.state is OrderState.READY_FOR_APPROVAL


def test_processing_retry_resumes_processing_and_continues() -> None:
    processing = advance(make_order(), OrderState.PROCESSING)
    failed = processing.transition_to(OrderState.FAILED_RETRYABLE)

    assert failed.failure_origin is OrderState.PROCESSING
    assert_non_lifecycle_data_preserved(processing, failed)
    retried = failed.retry()

    assert retried.state is OrderState.PROCESSING
    assert retried.failure_origin is None
    assert failed.state is OrderState.FAILED_RETRYABLE
    assert failed.failure_origin is OrderState.PROCESSING
    extracted = advance(retried, OrderState.EXTRACTED)
    assert extracted.state is OrderState.EXTRACTED


def test_extracted_retry_resumes_extracted_and_continues() -> None:
    extracted = advance(advance(make_order(), OrderState.PROCESSING), OrderState.EXTRACTED)
    failed = extracted.transition_to(OrderState.FAILED_RETRYABLE)

    assert failed.failure_origin is OrderState.EXTRACTED
    retried = failed.retry()

    assert retried.state is OrderState.EXTRACTED
    assert retried.failure_origin is None
    assert failed.state is OrderState.FAILED_RETRYABLE
    validated = advance(retried, OrderState.VALIDATED)
    assert validated.state is OrderState.VALIDATED


def test_syncing_retry_resumes_syncing_and_completes() -> None:
    ready = advance(
        advance(
            advance(
                advance(make_order(), OrderState.PROCESSING),
                OrderState.EXTRACTED,
            ),
            OrderState.VALIDATED,
        ),
        OrderState.READY_FOR_APPROVAL,
    )
    approved = advance(ready, OrderState.APPROVED)
    syncing = advance(approved, OrderState.SYNCING)
    failed = syncing.transition_to(OrderState.FAILED_RETRYABLE)

    assert failed.failure_origin is OrderState.SYNCING
    retried = failed.retry()

    assert retried.state is OrderState.SYNCING
    assert retried.failure_origin is None
    assert failed.state is OrderState.FAILED_RETRYABLE
    completed = advance(retried, OrderState.COMPLETED)
    with pytest.raises(InvalidStateTransitionError):
        completed.retry()
    assert completed.state is OrderState.COMPLETED


@pytest.mark.parametrize(
    "origin",
    [OrderState.PROCESSING, OrderState.EXTRACTED, OrderState.SYNCING],
)
def test_final_failure_is_terminal_and_retains_origin(origin: OrderState) -> None:
    operational = make_order()
    operational = advance(operational, OrderState.PROCESSING)
    if origin in (OrderState.EXTRACTED, OrderState.SYNCING):
        operational = advance(operational, OrderState.EXTRACTED)
    if origin is OrderState.SYNCING:
        operational = advance(operational, OrderState.VALIDATED)
        operational = advance(operational, OrderState.READY_FOR_APPROVAL)
        operational = advance(operational, OrderState.APPROVED)
        operational = advance(operational, OrderState.SYNCING)

    failed = operational.transition_to(OrderState.FAILED_FINAL)
    assert failed.failure_origin is origin
    assert_non_lifecycle_data_preserved(operational, failed)
    assert operational.state is origin
    assert operational.failure_origin is None
    for target in OrderState:
        with pytest.raises(InvalidStateTransitionError):
            failed.transition_to(target)
    with pytest.raises(InvalidStateTransitionError):
        failed.retry()
    with pytest.raises(InvalidStateTransitionError):
        failed.reopen()


def test_non_order_state_transition_target_is_rejected_explicitly() -> None:
    order = make_order()

    with pytest.raises(InvalidStateTransitionError) as error:
        order.transition_to("SYNCING")  # type: ignore[arg-type]

    assert error.value.current_state is OrderState.RECEIVED
    assert error.value.requested_state == "SYNCING"
    assert error.value.operation == "transition_to"
    assert order.state is OrderState.RECEIVED


def test_invalid_transition_error_has_domain_hierarchy_and_context() -> None:
    assert issubclass(InvalidStateTransitionError, DomainValidationError)

    with pytest.raises(InvalidStateTransitionError) as error:
        make_order().transition_to(OrderState.SYNCING)

    assert str(error.value)
    assert "RECEIVED" in str(error.value)
    assert "SYNCING" in str(error.value)

from dataclasses import fields
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from opsflow.domain import (
    InvalidStateTransitionError,
    Order,
    OrderLine,
    OrderState,
    SourceDocument,
    SourceDocumentType,
)

ORDER_ID = UUID(int=20)
LINE_ID = UUID(int=21)
DOCUMENT_ID = UUID(int=22)
SHA256 = "b" * 64

EXPECTED_TRANSITIONS = {
    OrderState.RECEIVED: frozenset({OrderState.PROCESSING}),
    OrderState.PROCESSING: frozenset(
        {
            OrderState.EXTRACTED,
            OrderState.FAILED_RETRYABLE,
            OrderState.FAILED_FINAL,
        }
    ),
    OrderState.EXTRACTED: frozenset(
        {
            OrderState.VALIDATED,
            OrderState.FAILED_RETRYABLE,
            OrderState.FAILED_FINAL,
        }
    ),
    OrderState.VALIDATED: frozenset({OrderState.NEEDS_REVIEW, OrderState.READY_FOR_APPROVAL}),
    OrderState.NEEDS_REVIEW: frozenset({OrderState.VALIDATED, OrderState.REJECTED}),
    OrderState.READY_FOR_APPROVAL: frozenset({OrderState.APPROVED, OrderState.REJECTED}),
    OrderState.APPROVED: frozenset({OrderState.SYNCING}),
    OrderState.SYNCING: frozenset(
        {
            OrderState.COMPLETED,
            OrderState.FAILED_RETRYABLE,
            OrderState.FAILED_FINAL,
        }
    ),
    OrderState.COMPLETED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.FAILED_RETRYABLE: frozenset(),
    OrderState.FAILED_FINAL: frozenset(),
}


def make_order(state: OrderState) -> Order:
    line = OrderLine(
        LINE_ID,
        "SKU-001",
        "Widget",
        Decimal("2"),
        Decimal("10.00"),
        None,
    )
    document = SourceDocument(
        DOCUMENT_ID,
        SourceDocumentType.PDF,
        "purchase-order.pdf",
        "application/pdf",
        SHA256,
        None,
        None,
        (),
    )
    return Order(
        id=ORDER_ID,
        customer_reference="CUST-001",
        po_number="PO-001",
        order_date=date(2026, 9, 13),
        requested_delivery_date=date(2026, 10, 1),
        currency="ZZZ",
        lines=(line,),
        source_documents=(document,),
        state=state,
        failure_origin=OrderState.PROCESSING
        if state in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL)
        else None,
    )


def test_exhaustive_normal_transition_matrix() -> None:
    assert sum(len(targets) for targets in EXPECTED_TRANSITIONS.values()) == 17

    for current in OrderState:
        for target in OrderState:
            order = make_order(current)
            if target in EXPECTED_TRANSITIONS[current]:
                result = order.transition_to(target)

                assert result.state is target
                assert result.failure_origin is (
                    current
                    if target in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL)
                    else None
                )
                assert result is not order
                for field in fields(Order):
                    if field.name not in {"state", "failure_origin"}:
                        assert getattr(result, field.name) == getattr(order, field.name)
                assert order.state is current
                assert order.failure_origin is (
                    OrderState.PROCESSING
                    if current in (OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL)
                    else None
                )
            else:
                with pytest.raises(InvalidStateTransitionError) as error:
                    order.transition_to(target)

                assert error.value.current_state is current
                assert error.value.requested_state is target
                assert error.value.operation == "transition_to"


def test_only_approved_can_enter_syncing() -> None:
    for current in OrderState:
        order = make_order(current)
        if current is OrderState.APPROVED:
            assert order.transition_to(OrderState.SYNCING).state is OrderState.SYNCING
        else:
            with pytest.raises(InvalidStateTransitionError):
                order.transition_to(OrderState.SYNCING)


@pytest.mark.parametrize(
    ("origin", "failure_state"),
    [
        (OrderState.PROCESSING, OrderState.FAILED_RETRYABLE),
        (OrderState.EXTRACTED, OrderState.FAILED_RETRYABLE),
        (OrderState.SYNCING, OrderState.FAILED_RETRYABLE),
        (OrderState.PROCESSING, OrderState.FAILED_FINAL),
        (OrderState.EXTRACTED, OrderState.FAILED_FINAL),
        (OrderState.SYNCING, OrderState.FAILED_FINAL),
    ],
)
def test_failure_transitions_record_exact_origin(
    origin: OrderState, failure_state: OrderState
) -> None:
    result = make_order(origin).transition_to(failure_state)

    assert result.state is failure_state
    assert result.failure_origin is origin


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderState.RECEIVED, OrderState.PROCESSING),
        (OrderState.PROCESSING, OrderState.EXTRACTED),
        (OrderState.EXTRACTED, OrderState.VALIDATED),
        (OrderState.VALIDATED, OrderState.NEEDS_REVIEW),
        (OrderState.NEEDS_REVIEW, OrderState.REJECTED),
        (OrderState.READY_FOR_APPROVAL, OrderState.APPROVED),
        (OrderState.APPROVED, OrderState.SYNCING),
        (OrderState.SYNCING, OrderState.COMPLETED),
    ],
)
def test_successful_non_failure_transitions_clear_origin(
    current: OrderState, target: OrderState
) -> None:
    result = make_order(current).transition_to(target)

    assert result.state is target
    assert result.failure_origin is None


@pytest.mark.parametrize(
    "origin",
    [OrderState.PROCESSING, OrderState.EXTRACTED, OrderState.SYNCING],
)
def test_retry_restores_exact_origin_and_clears_it(origin: OrderState) -> None:
    failed = make_order(origin).transition_to(OrderState.FAILED_RETRYABLE)

    result = failed.retry()

    assert result is not failed
    assert result.state is origin
    assert result.failure_origin is None
    assert failed.state is OrderState.FAILED_RETRYABLE
    assert failed.failure_origin is origin
    assert result.id == failed.id
    assert result.lines == failed.lines
    assert result.source_documents == failed.source_documents


@pytest.mark.parametrize(
    "state",
    [
        OrderState.RECEIVED,
        OrderState.PROCESSING,
        OrderState.EXTRACTED,
        OrderState.VALIDATED,
        OrderState.NEEDS_REVIEW,
        OrderState.READY_FOR_APPROVAL,
        OrderState.APPROVED,
        OrderState.SYNCING,
        OrderState.COMPLETED,
        OrderState.REJECTED,
        OrderState.FAILED_FINAL,
    ],
)
def test_retry_is_invalid_from_every_non_retryable_state(
    state: OrderState,
) -> None:
    with pytest.raises(InvalidStateTransitionError) as error:
        make_order(state).retry()

    assert error.value.current_state is state
    assert error.value.requested_state is None
    assert error.value.operation == "retry"


def test_retry_does_not_accept_a_destination() -> None:
    failed = make_order(OrderState.PROCESSING).transition_to(OrderState.FAILED_RETRYABLE)

    with pytest.raises(TypeError):
        failed.retry(OrderState.PROCESSING)  # type: ignore[call-arg]


def test_reopen_returns_needs_review_and_leaves_original_unchanged() -> None:
    rejected = make_order(OrderState.REJECTED)

    result = rejected.reopen()

    assert result is not rejected
    assert result.state is OrderState.NEEDS_REVIEW
    assert result.failure_origin is None
    assert result.id == rejected.id
    assert result.customer_reference == rejected.customer_reference
    assert result.lines == rejected.lines
    assert result.source_documents == rejected.source_documents
    assert rejected.state is OrderState.REJECTED
    assert rejected.failure_origin is None


@pytest.mark.parametrize(
    "state",
    [
        OrderState.RECEIVED,
        OrderState.PROCESSING,
        OrderState.EXTRACTED,
        OrderState.VALIDATED,
        OrderState.NEEDS_REVIEW,
        OrderState.READY_FOR_APPROVAL,
        OrderState.APPROVED,
        OrderState.SYNCING,
        OrderState.COMPLETED,
        OrderState.FAILED_RETRYABLE,
        OrderState.FAILED_FINAL,
    ],
)
def test_reopen_is_invalid_from_every_non_rejected_state(
    state: OrderState,
) -> None:
    with pytest.raises(InvalidStateTransitionError) as error:
        make_order(state).reopen()

    assert error.value.current_state is state
    assert error.value.requested_state is None
    assert error.value.operation == "reopen"


def test_reopen_does_not_accept_a_destination() -> None:
    rejected = make_order(OrderState.REJECTED)

    with pytest.raises(TypeError):
        rejected.reopen(OrderState.NEEDS_REVIEW)  # type: ignore[call-arg]


@pytest.mark.parametrize("state", [OrderState.COMPLETED, OrderState.FAILED_FINAL])
def test_terminal_states_have_no_normal_outgoing_transitions(
    state: OrderState,
) -> None:
    order = make_order(state)

    for target in OrderState:
        with pytest.raises(InvalidStateTransitionError):
            order.transition_to(target)

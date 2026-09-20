"""Unit tests for application-layer errors."""

import inspect
from uuid import UUID

import pytest

from opsflow.application.errors import (
    BusinessDataProviderError,
    ForbiddenError,
    IdempotencyConflictError,
    InvalidRejectionReasonError,
    InvalidReviewStateError,
    InvalidTrustedDataError,
    NoReviewChangesError,
    OrderNotFoundError,
    OrderValidationStateError,
    ReviewCaseUnavailableError,
    ReviewDraftUnavailableError,
    ReviewPersistenceConflictError,
    ReviewPreconditionFailedError,
    ReviewPreconditionRequiredError,
    SnapshotConflictError,
    SnapshotReplayError,
    SourceDocumentNotFoundError,
    SourceIdentityMismatchError,
    SourceOwnershipError,
    UnauthenticatedError,
    ValidationFactsChangedError,
)
from opsflow.domain import OrderState


def test_order_not_found_error_is_http_independent() -> None:
    assert issubclass(OrderNotFoundError, Exception)
    assert "fastapi" not in inspect.getsource(OrderNotFoundError).lower()
    assert "http" not in inspect.getsource(OrderNotFoundError).lower()


def test_idempotency_conflict_error_keeps_key_without_http_dependency() -> None:
    error = IdempotencyConflictError("opaque-key")

    assert error.idempotency_key == "opaque-key"
    assert "fastapi" not in inspect.getsource(IdempotencyConflictError).lower()
    assert "http" not in inspect.getsource(IdempotencyConflictError).lower()


@pytest.mark.parametrize(
    "error_type",
    [
        SourceDocumentNotFoundError,
        SourceOwnershipError,
        SourceIdentityMismatchError,
        OrderValidationStateError,
        SnapshotReplayError,
        SnapshotConflictError,
        ValidationFactsChangedError,
        InvalidTrustedDataError,
        BusinessDataProviderError,
    ],
)
def test_phase5_errors_are_transport_independent_and_safe(error_type: type[Exception]) -> None:
    assert issubclass(error_type, Exception)
    source = inspect.getsource(error_type).lower()
    assert "fastapi" not in source
    assert "http" not in source
    assert "sql" not in source


def test_phase5_errors_expose_only_safe_structured_context() -> None:
    order_id = UUID(int=1)
    source_id = UUID(int=2)

    not_found = SourceDocumentNotFoundError(source_id)
    ownership = SourceOwnershipError(order_id, source_id)
    identity = SourceIdentityMismatchError(order_id, source_id)
    state = OrderValidationStateError(order_id, OrderState.READY_FOR_APPROVAL)
    replay = SnapshotReplayError(order_id, source_id)
    conflict = SnapshotConflictError(order_id, source_id)
    facts = ValidationFactsChangedError(order_id)

    assert not_found.source_document_id == source_id
    assert ownership.order_id == order_id
    assert ownership.source_document_id == source_id
    assert identity.order_id == order_id
    assert identity.source_document_id == source_id
    assert state.order_id == order_id
    assert state.current_state is OrderState.READY_FOR_APPROVAL
    assert replay.order_id == order_id
    assert replay.source_document_id == source_id
    assert conflict.order_id == order_id
    assert conflict.source_document_id == source_id
    assert facts.order_id == order_id


def test_provider_and_trusted_data_errors_do_not_leak_details() -> None:
    provider = BusinessDataProviderError()
    trusted = InvalidTrustedDataError()

    assert str(provider) == "Business data provider operation failed."
    assert str(trusted) == "Trusted business data failed contract validation."
    assert "provider detail" not in str(provider)
    assert "malformed payload" not in str(trusted)


@pytest.mark.parametrize(
    "error_type",
    [
        UnauthenticatedError,
        ForbiddenError,
        ReviewCaseUnavailableError,
        InvalidReviewStateError,
        ReviewPreconditionRequiredError,
        ReviewPreconditionFailedError,
        NoReviewChangesError,
        ReviewDraftUnavailableError,
        InvalidRejectionReasonError,
        ReviewPersistenceConflictError,
    ],
)
def test_phase6_errors_are_transport_independent_and_safe(error_type: type[Exception]) -> None:
    assert issubclass(error_type, Exception)
    source = inspect.getsource(error_type).lower()
    assert "fastapi" not in source
    assert "http" not in source
    assert "sql" not in source


def test_phase6_safe_errors_never_include_supplied_credentials_or_private_details() -> None:
    safe_errors = (
        UnauthenticatedError(),
        ForbiddenError(),
        ReviewCaseUnavailableError(),
        InvalidReviewStateError(),
        ReviewPreconditionRequiredError(),
        ReviewPreconditionFailedError(),
        NoReviewChangesError(),
        ReviewDraftUnavailableError(),
        InvalidRejectionReasonError(),
        ReviewPersistenceConflictError(),
        BusinessDataProviderError(),
        InvalidTrustedDataError(),
        ValidationFactsChangedError(UUID(int=1)),
    )

    for error in safe_errors:
        assert len(str(error)) <= 160
        assert "fake-credential" not in str(error)
        assert "provider payload" not in str(error)
        assert "SELECT" not in str(error)

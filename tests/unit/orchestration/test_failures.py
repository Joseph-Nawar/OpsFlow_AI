"""Pure tests for Phase 7 operational failure classification."""

from dataclasses import FrozenInstanceError, fields
from uuid import uuid4

import pytest

from opsflow.application.errors import (
    BusinessDataProviderError,
    InvalidTrustedDataError,
    ValidationFactsChangedError,
)
from opsflow.documents.errors import (
    DocumentLimitError,
    DocumentParseError,
    DocumentProcessingError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from opsflow.domain import OrderState
from opsflow.extraction.errors import (
    ExtractionResponseError,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from opsflow.orchestration.failures import (
    FailureClassification,
    FailureDisposition,
    classify_extracted_failure,
    classify_processing_failure,
)
from opsflow.validation.models import ValidationRoute

SENSITIVE_DETAIL = "SYNTHETIC-SENSITIVE-PROVIDER-DIAGNOSTIC"
PROCESSING_DESCRIPTION = "Orchestration processing stopped with a persisted operational failure."
EXTRACTED_DESCRIPTION = (
    "Deterministic validation could not complete; a persisted operational failure was recorded."
)


def _with_sensitive_detail(error: BaseException) -> BaseException:
    error.args = (SENSITIVE_DETAIL,)
    return error


def _make_error(error_type: type[BaseException]) -> BaseException:
    if error_type is ValidationFactsChangedError:
        return ValidationFactsChangedError(uuid4())
    return error_type()


def _assert_safe_classification(
    classification: FailureClassification,
    *,
    disposition: FailureDisposition,
    origin: OrderState,
    target: OrderState,
    event_type: str,
    description: str,
) -> None:
    assert classification.disposition is disposition
    assert classification.origin is origin
    assert classification.target is target
    assert classification.event_type == event_type
    assert classification.description == description
    assert SENSITIVE_DETAIL not in classification.description
    assert SENSITIVE_DETAIL not in repr(classification)


def test_failure_disposition_has_exact_values() -> None:
    assert [(member.name, member.value) for member in FailureDisposition] == [
        ("RETRYABLE", "RETRYABLE"),
        ("FINAL", "FINAL"),
    ]


def test_failure_classification_is_frozen_and_slotted() -> None:
    classification = FailureClassification(
        FailureDisposition.FINAL,
        OrderState.PROCESSING,
        OrderState.FAILED_FINAL,
        "ORDER_PROCESSING_FAILED",
        PROCESSING_DESCRIPTION,
    )

    assert not hasattr(classification, "__dict__")
    assert [field.name for field in fields(classification)] == [
        "disposition",
        "origin",
        "target",
        "event_type",
        "description",
    ]
    with pytest.raises(FrozenInstanceError):
        classification.target = OrderState.FAILED_RETRYABLE  # type: ignore[misc]


@pytest.mark.parametrize(
    ("error_type", "disposition", "target"),
    [
        (ProviderTimeoutError, FailureDisposition.RETRYABLE, OrderState.FAILED_RETRYABLE),
        (ProviderUnavailableError, FailureDisposition.RETRYABLE, OrderState.FAILED_RETRYABLE),
        (ExtractionResponseError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
        (ProviderError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
        (DocumentValidationError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
        (DocumentLimitError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
        (DocumentParseError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
        (UnsupportedDocumentTypeError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
        (DocumentProcessingError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
        (RuntimeError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
    ],
)
def test_processing_failure_matrix_is_type_based(
    error_type: type[BaseException],
    disposition: FailureDisposition,
    target: OrderState,
) -> None:
    error = _with_sensitive_detail(_make_error(error_type))

    classification = classify_processing_failure(error)

    _assert_safe_classification(
        classification,
        disposition=disposition,
        origin=OrderState.PROCESSING,
        target=target,
        event_type="ORDER_PROCESSING_FAILED",
        description=PROCESSING_DESCRIPTION,
    )


@pytest.mark.parametrize(
    ("error_type", "disposition", "target"),
    [
        (BusinessDataProviderError, FailureDisposition.RETRYABLE, OrderState.FAILED_RETRYABLE),
        (ValidationFactsChangedError, FailureDisposition.RETRYABLE, OrderState.FAILED_RETRYABLE),
        (InvalidTrustedDataError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
        (RuntimeError, FailureDisposition.FINAL, OrderState.FAILED_FINAL),
    ],
)
def test_extracted_failure_matrix_is_type_based(
    error_type: type[BaseException],
    disposition: FailureDisposition,
    target: OrderState,
) -> None:
    error = _with_sensitive_detail(_make_error(error_type))

    classification = classify_extracted_failure(error)

    _assert_safe_classification(
        classification,
        disposition=disposition,
        origin=OrderState.EXTRACTED,
        target=target,
        event_type="ORDER_VALIDATION_FAILED",
        description=EXTRACTED_DESCRIPTION,
    )


def test_business_validation_routes_remain_successful_outcomes() -> None:
    assert {route.value for route in ValidationRoute} == {
        "NEEDS_REVIEW",
        "READY_FOR_APPROVAL",
    }
    assert {route.value for route in ValidationRoute}.isdisjoint(
        {state.value for state in OrderState if state.name.startswith("FAILED_")}
    )

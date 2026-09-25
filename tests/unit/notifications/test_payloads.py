"""Deterministic, low-disclosure Phase 8 notification rendering tests."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from opsflow.domain import (
    Order,
    OrderLine,
    OrderState,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.notifications.contracts import NotificationKind
from opsflow.notifications.payloads import (
    build_review_url,
    render_gmail_approval_payload,
    render_slack_payload,
)

ORDER_ID = UUID("12345678-1234-5678-9abc-def012345678")
REVIEW_BASE = "http://localhost:5173"


def _order(state: OrderState) -> Order:
    return Order(
        id=ORDER_ID,
        customer_reference="UNTRUSTED-CUSTOMER-REFERENCE",
        po_number="UNTRUSTED-PO-REFERENCE",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 1, 10),
        currency="USD",
        lines=(
            OrderLine(
                id=UUID(int=2),
                sku="UNTRUSTED-SKU",
                description="RAW-EXTRACTION-TEXT",
                quantity=Decimal("1"),
                submitted_price=Decimal("3"),
                trusted_catalogue_price=Decimal("3"),
            ),
        ),
        source_documents=(
            SourceDocument(
                id=UUID(int=3),
                document_type=SourceDocumentType.EMAIL_BODY,
                name="email.txt",
                mime_type="text/plain",
                sha256="a" * 64,
                message_id="RAW-EMAIL-MESSAGE-ID",
                storage_reference=None,
                metadata=(),
            ),
        ),
        state=state,
        failure_origin=OrderState.PROCESSING
        if state in {OrderState.FAILED_RETRYABLE, OrderState.FAILED_FINAL}
        else None,
    )


def _issue(explanation: str = "RAW-EXTRACTION-SECRET") -> ValidationIssue:
    return ValidationIssue(
        rule_code="PRIVATE-RULE-CODE",
        severity=ValidationSeverity.ERROR,
        field="private-field",
        expected="PRIVATE-EXPECTED",
        actual="PRIVATE-ACTUAL",
        explanation=explanation,
    )


def test_build_review_url_appends_one_canonical_review_path() -> None:
    assert build_review_url(f"{REVIEW_BASE}/", ORDER_ID) == (f"{REVIEW_BASE}/review/{ORDER_ID}")


def test_review_required_payload_uses_only_issue_count_and_server_reference() -> None:
    payload = render_slack_payload(
        NotificationKind.REVIEW_REQUIRED,
        _order(OrderState.NEEDS_REVIEW),
        (_issue(), _issue("PRIVATE-PROVIDER-DIAGNOSTIC")),
        REVIEW_BASE,
    )

    assert payload == {
        "text": (
            "2 validation issue(s) require review. Order 12345678-1234-5678-9abc-"
            "def012345678; state NEEDS_REVIEW. "
            "http://localhost:5173/review/12345678-1234-5678-9abc-def012345678"
        ),
        "order_id": str(ORDER_ID),
        "state": "NEEDS_REVIEW",
        "summary": "2 validation issue(s) require review.",
        "review_url": f"{REVIEW_BASE}/review/{ORDER_ID}",
    }
    _assert_no_untrusted_source_data(payload)


def test_approval_ready_payload_has_fixed_truthful_summary() -> None:
    payload = render_slack_payload(
        NotificationKind.APPROVAL_READY,
        _order(OrderState.READY_FOR_APPROVAL),
        (),
        REVIEW_BASE,
    )

    assert payload["summary"] == "Order is ready for approval."
    assert payload["state"] == "READY_FOR_APPROVAL"
    assert "synchron" not in str(payload["text"]).lower()
    _assert_no_untrusted_source_data(payload)


def test_processing_failed_payload_has_fixed_safe_summary() -> None:
    payload = render_slack_payload(
        NotificationKind.PROCESSING_FAILED,
        _order(OrderState.FAILED_RETRYABLE),
        (),
        REVIEW_BASE,
    )

    assert payload["summary"] == "Order processing failed; operator review may be required."
    assert payload["state"] == "FAILED_RETRYABLE"
    _assert_no_untrusted_source_data(payload)


def test_slack_order_approved_payload_is_truthful() -> None:
    payload = render_slack_payload(
        NotificationKind.ORDER_APPROVED,
        _order(OrderState.APPROVED),
        (),
        REVIEW_BASE,
    )

    assert payload["summary"] == "Order approved for processing."
    assert payload["state"] == "APPROVED"
    assert "ERP" not in str(payload).upper()
    assert "complete" not in str(payload).lower()
    _assert_no_untrusted_source_data(payload)


def test_gmail_approval_payload_contains_raw_message_id_and_exact_body() -> None:
    payload = render_gmail_approval_payload(_order(OrderState.APPROVED), "gmail-id-raw")

    assert payload == {
        "message_id": "gmail-id-raw",
        "body": "Your purchase order has been approved for processing.",
    }


def test_slack_top_level_text_is_bounded_by_unicode_code_points() -> None:
    payload = render_slack_payload(
        NotificationKind.REVIEW_REQUIRED,
        _order(OrderState.NEEDS_REVIEW),
        (_issue(),),
        "https://example.test/" + "é" * 5_000,
    )

    assert len(payload["text"]) == 4_000
    assert payload["text"].endswith("…")


def _assert_no_untrusted_source_data(payload: dict[str, object]) -> None:
    rendered = str(payload)
    for secret in (
        "UNTRUSTED-CUSTOMER-REFERENCE",
        "UNTRUSTED-PO-REFERENCE",
        "UNTRUSTED-SKU",
        "RAW-EXTRACTION-TEXT",
        "RAW-EMAIL-MESSAGE-ID",
        "RAW-EXTRACTION-SECRET",
        "PRIVATE-PROVIDER-DIAGNOSTIC",
    ):
        assert secret not in rendered

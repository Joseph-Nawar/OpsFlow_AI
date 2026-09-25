"""Deterministic, low-disclosure notification payload rendering."""

from collections.abc import Sequence
from uuid import UUID

from pydantic import AnyHttpUrl

from opsflow.domain import Order, ValidationIssue
from opsflow.notifications.contracts import NotificationKind

_GMAIL_APPROVAL_BODY = "Your purchase order has been approved for processing."
_SLACK_SUMMARIES = {
    NotificationKind.REVIEW_REQUIRED: None,
    NotificationKind.APPROVAL_READY: "Order is ready for approval.",
    NotificationKind.PROCESSING_FAILED: "Order processing failed; operator review may be required.",
    NotificationKind.ORDER_APPROVED: "Order approved for processing.",
}


def build_review_url(base_url: AnyHttpUrl | str, order_id: UUID) -> str:
    """Append the current review route to an explicitly supplied validated base URL."""

    normalized_base = str(base_url).rstrip("/")
    return f"{normalized_base}/review/{order_id}"


def render_slack_payload(
    kind: NotificationKind,
    order: Order,
    issues: Sequence[ValidationIssue],
    review_base_url: AnyHttpUrl | str,
) -> dict[str, object]:
    """Render only the safe server order ID, current state, fixed summary, and URL."""

    if kind is NotificationKind.REVIEW_REQUIRED:
        summary = f"{len(issues)} validation issue(s) require review."
    else:
        fixed_summary = _SLACK_SUMMARIES[kind]
        if fixed_summary is None:
            raise ValueError("notification kind does not have a Slack summary")
        summary = fixed_summary

    review_url = build_review_url(review_base_url, order.id)
    text = f"{summary} Order {order.id}; state {order.state.value}. {review_url}"
    if len(text) > 4_000:
        text = text[:3_999] + "…"
    return {
        "text": text,
        "order_id": str(order.id),
        "state": order.state.value,
        "summary": summary,
        "review_url": review_url,
    }


def render_gmail_approval_payload(order: Order, raw_message_id: str) -> dict[str, object]:
    """Render the approved, deliberately narrow Gmail reply contract."""

    del order
    if not isinstance(raw_message_id, str) or not raw_message_id.strip():
        raise ValueError("Gmail approval payload requires a nonblank message ID")
    return {"message_id": raw_message_id, "body": _GMAIL_APPROVAL_BODY}

"""HTTP and PostgreSQL integration coverage for human review revalidation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from opsflow.api.orders import get_session
from opsflow.application import review_revalidation as revalidation_service
from opsflow.domain import (
    AuditEvent,
    Order,
    OrderLine,
    OrderState,
    SourceDocument,
    SourceDocumentType,
    ValidationIssue,
    ValidationSeverity,
)
from opsflow.extraction.models import Evidence, ExtractedLine, ExtractionDraft
from opsflow.main import create_app
from opsflow.persistence.mappers import (
    PersistedExtractionSnapshot,
    extraction_draft_to_payload,
)
from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    NotificationDeliveryModel,
    OrderLineModel,
    OrderModel,
    ReviewRevisionModel,
    SourceDocumentModel,
    ValidationIssueModel,
)
from opsflow.persistence.repositories import (
    get_audit_events,
    get_order,
    get_review_revision_history,
    insert_audit_event,
    insert_extraction_snapshot,
    insert_order_graph,
    insert_review_revision,
    replace_validation_issues,
    update_order_snapshot,
)
from opsflow.review import (
    OperatorContext,
    OperatorRole,
    ReviewChange,
    ReviewDraft,
    ReviewLine,
    ReviewRevision,
)
from opsflow.review.composition import ReviewRuntime
from opsflow.settings import DevelopmentOperatorConfig, Settings
from opsflow.validation import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
    ValidationFacts,
)
from opsflow.validation.policy import ValidationPolicy

REPOSITORY_ROOT = Path(__file__).parents[2]
PHASE_6_REVISION = "0004_phase6_review_revisions"
PHASE_8_HEAD = "0005_phase8_notification_deliveries"
REVIEWER_TOKEN = "synthetic-reviewer-integration-credential"
APPROVER_TOKEN = "synthetic-approver-integration-credential"
REVIEWER = OperatorContext("reviewer-integration", OperatorRole.REVIEWER)
POLICY = ValidationPolicy(("USD",), Decimal("0.05"), Decimal("1000"))
RECORDED_AT = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
EVALUATION_DATE = date(2030, 1, 2)


def test_openapi_exposes_exact_phase6_review_surface() -> None:
    openapi = create_app(_settings()).openapi()
    paths = openapi["paths"]
    review_paths = {path: value for path, value in paths.items() if path.startswith("/v1/review/")}

    assert set(review_paths) == {
        "/v1/review/orders",
        "/v1/review/orders/{order_id}",
        "/v1/review/orders/{order_id}/reference-data",
        "/v1/review/orders/{order_id}/draft",
        "/v1/review/orders/{order_id}/approve",
        "/v1/review/orders/{order_id}/reject",
        "/v1/review/orders/{order_id}/retry",
    }
    assert set(review_paths["/v1/review/orders"]) == {"get"}
    assert set(review_paths["/v1/review/orders/{order_id}"]) == {"get"}
    assert set(review_paths["/v1/review/orders/{order_id}/reference-data"]) == {"get"}
    draft_operation = review_paths["/v1/review/orders/{order_id}/draft"]["put"]
    assert set(review_paths["/v1/review/orders/{order_id}/draft"]) == {"put"}
    assert set(review_paths["/v1/review/orders/{order_id}/approve"]) == {"post"}
    assert set(review_paths["/v1/review/orders/{order_id}/reject"]) == {"post"}
    assert set(review_paths["/v1/review/orders/{order_id}/retry"]) == {"post"}
    if_match = next(
        parameter for parameter in draft_operation["parameters"] if parameter["name"] == "If-Match"
    )
    assert if_match["required"] is True
    assert "Required strong review ETag" in if_match["description"]
    assert {"412", "428"} <= set(draft_operation["responses"])
    request_schema = draft_operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/ReviewDraftRequest")
    draft_model = openapi["components"]["schemas"]["ReviewDraftRequest"]
    assert set(draft_model["required"]) == {
        "customer_name",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "lines",
    }
    assert draft_model["additionalProperties"] is False
    line_schema = draft_model["properties"]["lines"]["items"]
    assert line_schema["$ref"].endswith("/ReviewLineRequest")
    assert openapi["components"]["schemas"]["ReviewLineRequest"]["additionalProperties"] is False


def test_review_revalidation_authentication_fails_closed_without_database_access() -> None:
    asyncio.run(_assert_authentication_fails_closed())


def test_review_draft_request_rejects_every_noneditable_authority_field() -> None:
    asyncio.run(_assert_request_rejects_noneditable_fields())


async def _assert_authentication_fails_closed() -> None:
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            missing = await client.put(f"/v1/review/orders/{uuid4()}/draft", json=_draft_body())
            unknown = await client.put(
                f"/v1/review/orders/{uuid4()}/draft",
                json=_draft_body(),
                headers={"Authorization": "Bearer unknown-credential"},
            )
    for response in (missing, unknown):
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "UNAUTHENTICATED"
        assert REVIEWER_TOKEN not in response.text


async def _assert_request_rejects_noneditable_fields() -> None:
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for field in (
                "actor",
                "role",
                "revision_number",
                "old_values",
                "state",
                "source_sha256",
                "evidence",
                "changes",
                "trusted_catalogue_price",
            ):
                body = _draft_body()
                body[field] = "client-claim"
                response = await client.put(
                    f"/v1/review/orders/{uuid4()}/draft",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {REVIEWER_TOKEN}",
                        "If-Match": '"' + "a" * 64 + '"',
                    },
                )
                assert response.status_code == 422
                assert response.json()["detail"]["code"] == "INVALID_REVIEW_DRAFT"
                assert "client-claim" not in response.text

            line_body = _draft_body()
            line_body["lines"][0]["trusted_catalogue_price"] = "99"
            line_response = await client.put(
                f"/v1/review/orders/{uuid4()}/draft",
                json=line_body,
                headers={
                    "Authorization": f"Bearer {REVIEWER_TOKEN}",
                    "If-Match": '"' + "a" * 64 + '"',
                },
            )
            invalid_contract = await client.put(
                f"/v1/review/orders/{uuid4()}/draft",
                json=_draft_body(customer_name=""),
                headers={
                    "Authorization": f"Bearer {REVIEWER_TOKEN}",
                    "If-Match": '"' + "a" * 64 + '"',
                },
            )
    assert line_response.status_code == 422
    assert line_response.json()["detail"]["code"] == "INVALID_REVIEW_DRAFT"
    assert invalid_contract.status_code == 422
    assert invalid_contract.json()["detail"]["code"] == "INVALID_REVIEW_DRAFT"


def _draft_body(
    *,
    customer_name: str | None = "Acme Industries",
    customer_reference: str | None = "CUST-001",
    po_number: str | None = "PO-101",
    order_date: str | None = "2030-01-01",
    requested_delivery_date: str | None = "2030-02-01",
    currency: str | None = "USD",
    sku: str | None = "SKU-001",
    description: str | None = "Widget",
    quantity: str | None = "2",
    submitted_price: str | None = "10",
) -> dict[str, object]:
    return {
        "customer_name": customer_name,
        "customer_reference": customer_reference,
        "po_number": po_number,
        "order_date": order_date,
        "requested_delivery_date": requested_delivery_date,
        "currency": currency,
        "lines": [
            {
                "sku": sku,
                "description": description,
                "quantity": quantity,
                "submitted_price": submitted_price,
            }
        ],
    }


def _review_draft(po_number: str) -> ReviewDraft:
    return ReviewDraft(
        customer_name="Acme Industries",
        customer_reference="CUST-001",
        po_number=po_number,
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 2, 1),
        currency="USD",
        lines=(ReviewLine("SKU-001", "Widget", Decimal("2"), Decimal("10")),),
    )


def _settings(role: OperatorRole = OperatorRole.REVIEWER) -> Settings:
    return Settings(
        review_dev_operators=(
            DevelopmentOperatorConfig(
                token=REVIEWER_TOKEN,
                actor="reviewer-integration",
                role=role,
            ),
        )
    )


class FixedDateProvider:
    def current_date(self) -> date:
        return EVALUATION_DATE


class StaticProvider:
    def __init__(
        self,
        data: TrustedBusinessData | None = None,
        on_call: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.data = data
        self.on_call = on_call
        self.calls: list[BusinessDataLookupRequest] = []
        self.session: AsyncSession | None = None

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        if self.session is not None:
            assert self.session.in_transaction() is False
        self.calls.append(request)
        if self.on_call is not None:
            await self.on_call()
        if self.data is not None:
            return self.data
        products = {
            "SKU-001": TrustedProduct(
                "SKU-001", "Widget", True, "USD", Decimal("10"), Decimal("100")
            ),
            "SKU-HV": TrustedProduct(
                "SKU-HV", "High-value Widget", True, "USD", Decimal("25"), Decimal("100")
            ),
        }
        return TrustedBusinessData(
            customer_candidates=(
                (TrustedCustomer("CUST-001", "Acme Industries", True),)
                if request.customer_reference == "CUST-001"
                or request.customer_name == "Acme Industries"
                else ()
            ),
            products_by_line=tuple(products.get(sku) for sku in request.skus),
        )


@asynccontextmanager
async def _case_client(
    case: ReviewCase,
    provider: StaticProvider,
    *,
    role: OperatorRole = OperatorRole.REVIEWER,
    with_snapshot: bool = True,
    snapshot_sha: str | None = None,
    extra_source_count: int = 0,
    additional_order_ids: tuple[UUID, ...] = (),
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], object, object]]:
    """Create isolated test data and a real PostgreSQL-backed review HTTP app."""

    _run_alembic("upgrade", "head")
    assert PHASE_8_HEAD in _run_alembic("current")
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    await _seed_case(
        session_factory,
        case,
        with_snapshot=with_snapshot,
        snapshot_sha=snapshot_sha,
        extra_source_count=extra_source_count,
    )
    app = create_app(_settings(role))
    app.state.review_runtime = _runtime(provider)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            provider.session = session
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                yield client, session_factory, engine, app
    finally:
        await _clean_up(engine, (case.order_id, *additional_order_ids))
        await engine.dispose()


async def _get_detail_etag(client: httpx.AsyncClient, order_id: UUID) -> tuple[dict, str]:
    response = await client.get(
        f"/v1/review/orders/{order_id}",
        headers={"Authorization": f"Bearer {REVIEWER_TOKEN}"},
    )
    assert response.status_code == 200, response.text
    return response.json(), response.headers["etag"]


def _headers(etag: str | None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {REVIEWER_TOKEN}"}
    if etag is not None:
        headers["If-Match"] = etag
    return headers


def _runtime(provider: StaticProvider) -> ReviewRuntime:
    return ReviewRuntime(POLICY, provider, FixedDateProvider())


@dataclass(frozen=True, slots=True)
class ReviewCase:
    order_id: UUID
    source_id: UUID
    snapshot_id: UUID
    source_sha256: str
    original_draft: ExtractionDraft
    order: Order


def _make_case() -> ReviewCase:
    order_id, source_id, snapshot_id, line_id = (uuid4() for _ in range(4))
    source_sha256 = uuid4().hex * 2
    source = SourceDocument(
        id=source_id,
        document_type=SourceDocumentType.PDF,
        name="purchase-order.pdf",
        mime_type="application/pdf",
        sha256=source_sha256,
        message_id="synthetic-message",
        storage_reference="synthetic://phase6-test.pdf",
        metadata=(("source", "phase6-test"),),
    )
    trusted_line = OrderLine(
        id=line_id,
        sku="SKU-OLD",
        description="Previously trusted widget",
        quantity=Decimal("1"),
        submitted_price=Decimal("5"),
        trusted_catalogue_price=Decimal("5"),
    )
    order = Order(
        id=order_id,
        customer_reference="TRUSTED-OLD",
        po_number="TRUSTED-OLD-PO",
        order_date=date(2029, 12, 1),
        requested_delivery_date=date(2029, 12, 20),
        currency="USD",
        lines=(trusted_line,),
        source_documents=(source,),
        state=OrderState.NEEDS_REVIEW,
    )
    draft = ExtractionDraft(
        source_sha256=source_sha256,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Acme Industries",
        customer_reference="CUST-001",
        po_number="PO-100",
        order_date=date(2030, 1, 1),
        requested_delivery_date=date(2030, 2, 1),
        currency="USD",
        lines=(ExtractedLine("SKU-001", "Widget", Decimal("2"), Decimal("10")),),
        notes="Original untrusted note",
        evidence=(Evidence("po_number", "page 1", "PO-100"),),
    )
    return ReviewCase(order_id, source_id, snapshot_id, source_sha256, draft, order)


async def _seed_case(
    session_factory: async_sessionmaker[AsyncSession],
    case: ReviewCase,
    *,
    with_snapshot: bool = True,
    snapshot_sha: str | None = None,
    extra_source_count: int = 0,
) -> None:
    created_at = datetime(2029, 1, 1, tzinfo=UTC)
    initial_audit_at = datetime(2000, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        order = case.order
        if extra_source_count:
            extra_documents = tuple(
                SourceDocument(
                    id=uuid4(),
                    document_type=SourceDocumentType.PDF,
                    name=f"extra-{position}.pdf",
                    mime_type="application/pdf",
                    sha256=(str(position + 1) * 64),
                    message_id=None,
                    storage_reference=None,
                    metadata=(),
                )
                for position in range(extra_source_count)
            )
            order = Order(
                id=order.id,
                customer_reference=order.customer_reference,
                po_number=order.po_number,
                order_date=order.order_date,
                requested_delivery_date=order.requested_delivery_date,
                currency=order.currency,
                lines=order.lines,
                source_documents=(*order.source_documents, *extra_documents),
                state=order.state,
            )
        await insert_order_graph(session, order, created_at)
        if with_snapshot:
            snapshot = PersistedExtractionSnapshot(
                id=case.snapshot_id,
                order_id=case.order_id,
                source_document_id=case.source_id,
                source_sha256=case.original_draft.source_sha256
                if snapshot_sha is None
                else snapshot_sha,
                source_document_type=case.original_draft.source_document_type,
                draft=(
                    case.original_draft
                    if snapshot_sha is None
                    else ExtractionDraft(
                        source_sha256=snapshot_sha,
                        source_document_type=case.original_draft.source_document_type,
                        customer_name=case.original_draft.customer_name,
                        customer_reference=case.original_draft.customer_reference,
                        po_number=case.original_draft.po_number,
                        order_date=case.original_draft.order_date,
                        requested_delivery_date=case.original_draft.requested_delivery_date,
                        currency=case.original_draft.currency,
                        lines=case.original_draft.lines,
                        notes=case.original_draft.notes,
                        evidence=case.original_draft.evidence,
                    )
                ),
                created_at=created_at,
            )
            await insert_extraction_snapshot(session, snapshot)
            for position, document in enumerate(order.source_documents[1 : 1 + extra_source_count]):
                other_draft = replace_source_sha(case.original_draft, document.sha256)
                await insert_extraction_snapshot(
                    session,
                    PersistedExtractionSnapshot(
                        id=uuid4(),
                        order_id=case.order_id,
                        source_document_id=document.id,
                        source_sha256=other_draft.source_sha256,
                        source_document_type=other_draft.source_document_type,
                        draft=other_draft,
                        created_at=created_at.replace(day=position + 2),
                    ),
                )
        await replace_validation_issues(
            session,
            case.order_id,
            (
                ValidationIssue(
                    "INITIAL_REVIEW_REQUIRED",
                    ValidationSeverity.ERROR,
                    "customer_reference",
                    "trusted customer",
                    "unresolved",
                    "Initial deterministic review required.",
                ),
            ),
        )
        await insert_audit_event(
            session,
            AuditEvent(
                id=uuid4(),
                order_id=case.order_id,
                event_type="ORDER_NEEDS_REVIEW",
                actor="system",
                occurred_at=initial_audit_at,
                description="Initial deterministic review required.",
            ),
        )
        await session.commit()


def replace_source_sha(draft: ExtractionDraft, source_sha: str) -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256=source_sha,
        source_document_type=draft.source_document_type,
        customer_name=draft.customer_name,
        customer_reference=draft.customer_reference,
        po_number=draft.po_number,
        order_date=draft.order_date,
        requested_delivery_date=draft.requested_delivery_date,
        currency=draft.currency,
        lines=draft.lines,
        notes=draft.notes,
        evidence=draft.evidence,
    )


async def _read_case_state(
    session_factory: async_sessionmaker[AsyncSession], order_id: UUID
) -> tuple[
    Order | None,
    tuple[ValidationIssue, ...],
    tuple[ReviewRevision, ...],
    tuple[AuditEvent, ...],
]:
    async with session_factory() as session:
        persisted = await get_order(session, order_id)
        revisions = await get_review_revision_history(session, order_id)
        audits = await get_audit_events(session, order_id)
    return (
        persisted.order if persisted is not None else None,
        persisted.validation_issues if persisted is not None else (),
        revisions,
        audits,
    )


async def _read_raw_state(
    session_factory: async_sessionmaker[AsyncSession], order_id: UUID
) -> dict[str, object]:
    async with session_factory() as session:
        line_rows = (
            await session.scalars(
                select(OrderLineModel)
                .where(OrderLineModel.order_id == order_id)
                .order_by(OrderLineModel.position.asc())
            )
        ).all()
        snapshots = (
            await session.scalars(
                select(ExtractionSnapshotModel).where(ExtractionSnapshotModel.order_id == order_id)
            )
        ).all()
        revision_count = await session.scalar(
            select(func.count())
            .select_from(ReviewRevisionModel)
            .where(ReviewRevisionModel.order_id == order_id)
        )
        issue_codes = tuple(
            await session.scalars(
                select(ValidationIssueModel.rule_code)
                .where(ValidationIssueModel.order_id == order_id)
                .order_by(ValidationIssueModel.position.asc())
            )
        )
        audit_types = tuple(
            await session.scalars(
                select(AuditEventModel.event_type)
                .where(AuditEventModel.order_id == order_id)
                .order_by(AuditEventModel.occurred_at.asc(), AuditEventModel.id.asc())
            )
        )
        return {
            "lines": tuple(
                (
                    row.id,
                    row.position,
                    row.sku,
                    row.description,
                    row.quantity,
                    row.submitted_price,
                    row.trusted_catalogue_price,
                )
                for row in line_rows
            ),
            "snapshots": tuple((row.id, row.source_sha256, row.payload) for row in snapshots),
            "revision_count": revision_count,
            "issue_codes": issue_codes,
            "audit_types": audit_types,
        }


async def _clean_up(engine, order_ids: tuple[UUID, ...]) -> None:
    async with engine.begin() as connection:
        await connection.execute(delete(OrderModel).where(OrderModel.id.in_(order_ids)))


def _run_alembic(*arguments: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=REPOSITORY_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
    return f"{result.stdout}\n{result.stderr}"


def test_invalid_correction_persists_revision_issues_and_audit_without_trusted_promotion() -> None:
    asyncio.run(_assert_invalid_correction_is_untrusted())


async def _assert_invalid_correction_is_untrusted() -> None:
    case = _make_case()
    provider = StaticProvider()
    async with _case_client(case, provider) as (client, session_factory, _, _):
        _, etag = await _get_detail_etag(client, case.order_id)
        original_order, _, _, original_audits = await _read_case_state(
            session_factory, case.order_id
        )
        raw_before = await _read_raw_state(session_factory, case.order_id)
        response = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(po_number="PO-101", sku="SKU-MISSING"),
            headers=_headers(etag),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert response.headers["etag"] == body["etag"]
        assert body["order"]["state"] == "NEEDS_REVIEW"
        assert body["original_extraction"]["notes"] == "Original untrusted note"
        assert body["original_extraction"]["evidence"] == [
            {"field_path": "po_number", "source_location": "page 1", "quote": "PO-100"}
        ]
        assert body["effective_draft"]["po_number"] == "PO-101"
        assert body["source_snapshot"]["source_sha256"] == case.source_sha256
        assert [item["rule_code"] for item in body["validation_issues"]] == ["UNKNOWN_SKU"]
        assert len(body["revisions"]) == 1
        assert body["latest_revision"]["actor"] == REVIEWER.actor
        assert body["latest_revision"]["revision_number"] == 1
        changes = body["latest_revision"]["changes"]
        assert [change["field_path"] for change in changes] == ["po_number", "lines"]
        assert (changes[0]["old_value"], changes[0]["new_value"]) == ("PO-100", "PO-101")
        assert changes[1]["old_value"][0]["sku"] == "SKU-001"
        assert changes[1]["new_value"][0]["sku"] == "SKU-MISSING"
        assert provider.calls == [BusinessDataLookupRequest("CUST-001", None, ("SKU-MISSING",))]

        final_order, final_issues, revisions, audits = await _read_case_state(
            session_factory, case.order_id
        )
        assert original_order is not None and final_order is not None
        assert final_order == original_order
        assert len(final_issues) == 1 and final_issues[0].rule_code == "UNKNOWN_SKU"
        assert len(revisions) == 1
        assert len(audits) == len(original_audits) + 3
        assert [event.event_type for event in audits[-3:]] == [
            "REVIEW_REVISION_RECORDED",
            "REVIEW_REVALIDATION_COMPLETED",
            "ORDER_REMAINS_NEEDS_REVIEW",
        ]
        async with session_factory() as session:
            delivery = await session.scalar(
                select(NotificationDeliveryModel).where(
                    NotificationDeliveryModel.order_id == case.order_id
                )
            )
        assert delivery is not None
        assert delivery.trigger_audit_event_id == audits[-1].id
        assert (delivery.channel, delivery.kind) == ("SLACK", "REVIEW_REQUIRED")
        assert {event.actor for event in audits[-3:]} == {REVIEWER.actor}
        assert provider.session is not None and provider.session.in_transaction() is False
        raw_after = await _read_raw_state(session_factory, case.order_id)
        assert raw_after["lines"] == raw_before["lines"]
        assert (
            raw_after["snapshots"]
            == raw_before["snapshots"]
            == (
                (
                    case.snapshot_id,
                    case.source_sha256,
                    extraction_draft_to_payload(case.original_draft),
                ),
            )
        )
        assert raw_after["revision_count"] == 1
        assert raw_after["issue_codes"] == ("UNKNOWN_SKU",)
        assert len(raw_after["audit_types"]) == len(raw_before["audit_types"]) + 3


def test_clean_high_value_correction_promotes_trusted_graph_and_returns_fresh_etag(
    monkeypatch,
) -> None:
    asyncio.run(_assert_clean_high_value_correction_promotes_trusted_values(monkeypatch))


async def _assert_clean_high_value_correction_promotes_trusted_values(monkeypatch) -> None:
    case = _make_case()
    provider = StaticProvider()
    original_validate = revalidation_service.validation_engine.validate
    engine_calls = 0

    def assert_engine_outside_transaction(*args, **kwargs):
        nonlocal engine_calls
        engine_calls += 1
        assert provider.session is not None and provider.session.in_transaction() is False
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(
        revalidation_service.validation_engine, "validate", assert_engine_outside_transaction
    )
    async with _case_client(case, provider) as (client, session_factory, _, _):
        _, etag = await _get_detail_etag(client, case.order_id)
        response = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(
                po_number="PO-HIGH-VALUE",
                sku="SKU-HV",
                description="High-value Widget",
                quantity="50",
                submitted_price="25",
            ),
            headers=_headers(etag),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert response.headers["etag"] == body["etag"]
        assert body["etag"] != etag
        assert body["order"]["state"] == "READY_FOR_APPROVAL"
        assert body["order"]["customer_reference"] == "CUST-001"
        assert body["order"]["po_number"] == "PO-HIGH-VALUE"
        assert body["operator"] == {"actor": REVIEWER.actor, "role": "REVIEWER"}
        assert body["order"]["lines"] == [
            {
                "id": body["order"]["lines"][0]["id"],
                "sku": "SKU-HV",
                "description": "High-value Widget",
                "quantity": "50",
                "submitted_price": "25",
                "trusted_catalogue_price": "25",
            }
        ]
        assert "HIGH_VALUE_APPROVAL_REQUIRED" in {
            item["rule_code"] for item in body["validation_issues"]
        }
        assert body["latest_revision"]["actor"] == REVIEWER.actor
        assert body["latest_revision"]["revision_number"] == 1
        assert [change["field_path"] for change in body["latest_revision"]["changes"]] == [
            "po_number",
            "lines",
        ]
        assert provider.calls == [BusinessDataLookupRequest("CUST-001", None, ("SKU-HV",))]
        assert engine_calls == 1
        persisted, issues, revisions, audits = await _read_case_state(
            session_factory, case.order_id
        )
        assert persisted is not None
        assert persisted.state is OrderState.READY_FOR_APPROVAL
        assert persisted.po_number == "PO-HIGH-VALUE"
        assert persisted.lines[0].trusted_catalogue_price == Decimal("25")
        assert persisted.lines[0].id != case.order.lines[0].id
        assert any(issue.rule_code == "HIGH_VALUE_APPROVAL_REQUIRED" for issue in issues)
        assert len(revisions) == 1
        assert [event.event_type for event in audits[-3:]] == [
            "REVIEW_REVISION_RECORDED",
            "REVIEW_REVALIDATION_COMPLETED",
            "ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION",
        ]
        async with session_factory() as session:
            delivery = await session.scalar(
                select(NotificationDeliveryModel).where(
                    NotificationDeliveryModel.order_id == case.order_id
                )
            )
        assert delivery is not None
        assert delivery.trigger_audit_event_id == audits[-1].id
        assert (delivery.channel, delivery.kind) == ("SLACK", "APPROVAL_READY")
        refreshed = await client.get(
            f"/v1/review/orders/{case.order_id}",
            headers={"Authorization": f"Bearer {REVIEWER_TOKEN}"},
        )
        assert refreshed.status_code == 200
        assert refreshed.headers["etag"] == response.headers["etag"]
        stale_retry = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(po_number="PO-TOO-LATE"),
            headers=_headers(etag),
        )
        assert stale_retry.status_code == 412
        assert stale_retry.json()["detail"]["code"] == "PRECONDITION_FAILED"
        assert len(provider.calls) == 1


def test_noop_missing_malformed_and_stale_preconditions_stop_before_provider() -> None:
    asyncio.run(_assert_preflight_errors_do_not_call_provider())


async def _assert_preflight_errors_do_not_call_provider() -> None:
    case = _make_case()
    provider = StaticProvider()
    async with _case_client(case, provider) as (client, session_factory, _, _):
        _, etag = await _get_detail_etag(client, case.order_id)
        before_order, before_issues, before_revisions, before_audits = await _read_case_state(
            session_factory, case.order_id
        )
        no_op = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(po_number="PO-100"),
            headers=_headers(etag),
        )
        assert no_op.status_code == 409
        assert no_op.json()["detail"]["code"] == "NO_REVIEW_CHANGES"
        for supplied, status, code in (
            (None, 428, "PRECONDITION_REQUIRED"),
            ("W/" + etag, 412, "PRECONDITION_FAILED"),
            ('"' + "0" * 64 + '"', 412, "PRECONDITION_FAILED"),
        ):
            response = await client.put(
                f"/v1/review/orders/{case.order_id}/draft",
                json=_draft_body(po_number="PO-101"),
                headers=_headers(supplied),
            )
            assert response.status_code == status
            assert response.json()["detail"]["code"] == code
        assert provider.calls == []
        persisted, issues, revisions, audits = await _read_case_state(
            session_factory, case.order_id
        )
        assert persisted == before_order == case.order
        assert issues == before_issues
        assert revisions == before_revisions == ()
        assert audits == before_audits and len(audits) == 1


def test_approver_cannot_save_review_draft() -> None:
    asyncio.run(_assert_nonreviewer_is_forbidden())


async def _assert_nonreviewer_is_forbidden() -> None:
    case = _make_case()
    provider = StaticProvider()
    async with _case_client(case, provider, role=OperatorRole.APPROVER) as (client, _, _, _):
        response = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(po_number="PO-101"),
            headers=_headers('"' + "1" * 64 + '"'),
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FORBIDDEN"
        assert provider.calls == []


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    (
        ("unavailable", "REFERENCE_DATA_UNAVAILABLE"),
        ("invalid", "REFERENCE_DATA_INVALID"),
    ),
)
def test_provider_failures_return_safe_retryable_http_errors(
    failure_kind: str, expected_code: str
) -> None:
    asyncio.run(_assert_provider_failure(failure_kind, expected_code))


async def _assert_provider_failure(failure_kind: str, expected_code: str) -> None:
    case = _make_case()

    async def unavailable() -> None:
        raise RuntimeError("synthetic provider-private detail")

    if failure_kind == "unavailable":
        provider = StaticProvider(on_call=unavailable)
    else:
        invalid_data = TrustedBusinessData(
            customer_candidates=(TrustedCustomer("CUST-999", "Other Customer", True),),
            products_by_line=(
                TrustedProduct("SKU-001", "Widget", True, "USD", Decimal("10"), Decimal("100")),
            ),
        )
        provider = StaticProvider(invalid_data)

    async with _case_client(case, provider) as (client, session_factory, _, _):
        _, etag = await _get_detail_etag(client, case.order_id)
        response = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(po_number="PO-101"),
            headers=_headers(etag),
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == expected_code
        assert "synthetic provider-private detail" not in response.text
        assert REVIEWER_TOKEN not in response.text
        persisted, _, revisions, audits = await _read_case_state(session_factory, case.order_id)
        assert persisted == case.order
        assert revisions == ()
        assert len(audits) == 1
        assert len(provider.calls) == 1


def test_missing_order_maps_to_safe_not_found_without_provider_work() -> None:
    asyncio.run(_assert_missing_order_maps_to_not_found())


async def _assert_missing_order_maps_to_not_found() -> None:
    case = _make_case()
    provider = StaticProvider()
    async with _case_client(case, provider) as (client, _, _, _):
        response = await client.put(
            f"/v1/review/orders/{uuid4()}/draft",
            json=_draft_body(po_number="PO-101"),
            headers=_headers('"' + "2" * 64 + '"'),
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "ORDER_NOT_FOUND"
        assert provider.calls == []


@pytest.mark.parametrize(
    ("with_snapshot", "snapshot_sha", "extra_source_count"),
    ((False, None, 0), (True, "b" * 64, 0), (True, None, 1)),
    ids=("missing", "identity-mismatch", "multiple"),
)
def test_missing_wrong_or_multiple_snapshot_is_safe_conflict(
    with_snapshot: bool, snapshot_sha: str | None, extra_source_count: int
) -> None:
    asyncio.run(
        _assert_bad_snapshot_case(
            with_snapshot=with_snapshot,
            snapshot_sha=snapshot_sha,
            extra_source_count=extra_source_count,
        )
    )


async def _assert_bad_snapshot_case(
    *, with_snapshot: bool, snapshot_sha: str | None, extra_source_count: int
) -> None:
    case = _make_case()
    provider = StaticProvider()
    async with _case_client(
        case,
        provider,
        with_snapshot=with_snapshot,
        snapshot_sha=snapshot_sha,
        extra_source_count=extra_source_count,
    ) as (client, session_factory, _, _):
        response = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(po_number="PO-101"),
            headers=_headers('"' + "a" * 64 + '"'),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "REVIEW_CASE_UNAVAILABLE"
        assert provider.calls == []
        _, _, revisions, audits = await _read_case_state(session_factory, case.order_id)
        assert revisions == ()
        assert len(audits) == 1


def test_locked_rechecks_reject_stale_revision_audit_state_and_source() -> None:
    asyncio.run(_assert_locked_rechecks())


async def _assert_locked_rechecks() -> None:
    for kind, expected_status, expected_code in (
        ("revision", 412, "PRECONDITION_FAILED"),
        ("audit", 412, "PRECONDITION_FAILED"),
        ("state", 409, "INVALID_REVIEW_STATE"),
        ("source", 409, "REVIEW_CASE_UNAVAILABLE"),
    ):
        case = _make_case()
        session_factory_box: list[async_sessionmaker[AsyncSession]] = []
        provider = StaticProvider(
            on_call=_make_concurrent_mutation(kind, case, session_factory_box)
        )
        async with _case_client(case, provider) as (client, session_factory, _, _):
            session_factory_box.append(session_factory)
            _, etag = await _get_detail_etag(client, case.order_id)
            response = await client.put(
                f"/v1/review/orders/{case.order_id}/draft",
                json=_draft_body(po_number="PO-101"),
                headers=_headers(etag),
            )
            assert response.status_code == expected_status, response.text
            assert response.json()["detail"]["code"] == expected_code
            assert len(provider.calls) == 1
            order, _, revisions, audits = await _read_case_state(session_factory, case.order_id)
            assert order is not None
            assert len(revisions) == (1 if kind == "revision" else 0)
            assert len(audits) == (2 if kind == "audit" else 1)


def _make_concurrent_mutation(
    kind: str,
    case: ReviewCase,
    factory_box: list[async_sessionmaker[AsyncSession]],
) -> Callable[[], Awaitable[None]]:
    async def concurrent_mutation() -> None:
        async with factory_box[0]() as session:
            if kind == "revision":
                payload = _review_draft("PO-RACED")
                await insert_review_revision(
                    session,
                    ReviewRevision(
                        id=uuid4(),
                        order_id=case.order_id,
                        extraction_snapshot_id=case.snapshot_id,
                        revision_number=1,
                        payload=payload,
                        changes=(ReviewChange("po_number", "PO-100", "PO-RACED"),),
                        actor="concurrent-reviewer",
                        created_at=RECORDED_AT,
                    ),
                )
            elif kind == "audit":
                await insert_audit_event(
                    session,
                    AuditEvent(
                        id=uuid4(),
                        order_id=case.order_id,
                        event_type="CONCURRENT_REVIEW_GENERATION",
                        actor="concurrent-reviewer",
                        occurred_at=RECORDED_AT,
                        description="Concurrent test generation.",
                    ),
                )
            elif kind == "state":
                persisted = await get_order(session, case.order_id)
                assert persisted is not None
                await update_order_snapshot(
                    session, persisted.order.transition_to(OrderState.VALIDATED)
                )
            else:
                await session.execute(
                    update(SourceDocumentModel)
                    .where(SourceDocumentModel.id == case.source_id)
                    .values(sha256="b" * 64)
                )
            await session.commit()

    return concurrent_mutation


def test_validation_facts_staleness_rolls_back_without_replaying_engine(monkeypatch) -> None:
    asyncio.run(_assert_facts_staleness_rolls_back(monkeypatch))


async def _assert_facts_staleness_rolls_back(monkeypatch) -> None:
    case = _make_case()
    duplicate_id = uuid4()
    provider = StaticProvider()
    original_build_facts = revalidation_service.build_validation_facts
    facts_reads = 0
    facts_values: list[ValidationFacts] = []
    engine_calls = 0
    original_validate = revalidation_service.validation_engine.validate

    async def build_facts_then_insert_competitor(*args, **kwargs):
        nonlocal facts_reads
        result = await original_build_facts(*args, **kwargs)
        facts_reads += 1
        facts_values.append(result)
        if facts_reads == 1:
            async with factory_box[0]() as session:
                competitor = Order(
                    id=duplicate_id,
                    customer_reference="CUST-001",
                    po_number="PO-101",
                    order_date=date(2030, 1, 1),
                    requested_delivery_date=date(2030, 2, 1),
                    currency="USD",
                    lines=(),
                    source_documents=(),
                    state=OrderState.RECEIVED,
                )
                await insert_order_graph(session, competitor, RECORDED_AT)
                await session.commit()
        return result

    def count_engine(*args, **kwargs):
        nonlocal engine_calls
        engine_calls += 1
        assert provider.session is not None and provider.session.in_transaction() is False
        return original_validate(*args, **kwargs)

    factory_box: list[async_sessionmaker[AsyncSession]] = []
    monkeypatch.setattr(
        revalidation_service, "build_validation_facts", build_facts_then_insert_competitor
    )
    monkeypatch.setattr(revalidation_service.validation_engine, "validate", count_engine)
    async with _case_client(case, provider, additional_order_ids=(duplicate_id,)) as (
        client,
        session_factory,
        _,
        _,
    ):
        factory_box.append(session_factory)
        before_order, before_issues, _, before_audits = await _read_case_state(
            session_factory, case.order_id
        )
        _, etag = await _get_detail_etag(client, case.order_id)
        response = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(po_number="PO-101"),
            headers=_headers(etag),
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "VALIDATION_FACTS_CHANGED"
        assert provider.calls and len(provider.calls) == 1
        assert facts_reads == 2
        assert facts_values[0] != facts_values[1]
        assert engine_calls == 1
        after_order, after_issues, revisions, audits = await _read_case_state(
            session_factory, case.order_id
        )
        assert after_order == before_order
        assert after_issues == before_issues
        assert revisions == ()
        assert audits == before_audits


def test_mixed_customer_candidates_keep_duplicate_identity_unresolved_across_boundary(
    monkeypatch,
) -> None:
    asyncio.run(_assert_ambiguous_customer_facts_agree(monkeypatch))


async def _assert_ambiguous_customer_facts_agree(monkeypatch) -> None:
    case = _make_case()
    duplicate_id = uuid4()
    provider_data = TrustedBusinessData(
        customer_candidates=(
            TrustedCustomer("CUST-001", "Acme Industries", True),
            TrustedCustomer("CUST-002", "Acme Industries", False),
        ),
        products_by_line=(
            TrustedProduct("SKU-001", "Widget", True, "USD", Decimal("10"), Decimal("100")),
        ),
    )
    provider = StaticProvider(provider_data)
    original_build_facts = revalidation_service.build_validation_facts
    facts_arguments: list[dict[str, object]] = []
    facts_values: list[ValidationFacts] = []
    original_validate = revalidation_service.validation_engine.validate
    engine_business_data: list[TrustedBusinessData] = []

    async def capture_facts(*args, **kwargs):
        facts_arguments.append(kwargs.copy())
        facts = await original_build_facts(*args, **kwargs)
        facts_values.append(facts)
        return facts

    def capture_engine(draft, trusted_data, facts, policy, context):
        engine_business_data.append(trusted_data)
        return original_validate(draft, trusted_data, facts, policy, context)

    monkeypatch.setattr(revalidation_service, "build_validation_facts", capture_facts)
    monkeypatch.setattr(revalidation_service.validation_engine, "validate", capture_engine)
    async with _case_client(case, provider, additional_order_ids=(duplicate_id,)) as (
        client,
        session_factory,
        _,
        _,
    ):
        async with session_factory() as session:
            competing = Order(
                id=duplicate_id,
                customer_reference="CUST-001",
                po_number="PO-AMBIGUOUS",
                order_date=date(2030, 1, 1),
                requested_delivery_date=date(2030, 2, 1),
                currency="USD",
                lines=(),
                source_documents=(),
                state=OrderState.RECEIVED,
            )
            await insert_order_graph(session, competing, RECORDED_AT)
            await session.commit()
        _, etag = await _get_detail_etag(client, case.order_id)
        response = await client.put(
            f"/v1/review/orders/{case.order_id}/draft",
            json=_draft_body(
                customer_name="Acme Industries",
                customer_reference=None,
                po_number="PO-AMBIGUOUS",
            ),
            headers=_headers(etag),
        )
        assert response.status_code == 200, response.text
        codes = {item["rule_code"] for item in response.json()["validation_issues"]}
        assert "AMBIGUOUS_CUSTOMER" in codes
        assert "DUPLICATE_CUSTOMER_PO" not in codes
        assert response.json()["order"]["state"] == "NEEDS_REVIEW"
        assert len(facts_arguments) == 2
        assert [facts["canonical_customer_reference"] for facts in facts_arguments] == [
            None,
            None,
        ]
        assert [facts["po_number"] for facts in facts_arguments] == [
            "PO-AMBIGUOUS",
            "PO-AMBIGUOUS",
        ]
        assert len(facts_values) == 2 and facts_values[0] == facts_values[1]
        assert facts_values[0] == ValidationFacts(False, False)
        assert len(engine_business_data) == 1
        assert engine_business_data[0] == provider_data
        assert len(provider.calls) == 1


class InjectedWriteFailure(Exception):
    pass


@pytest.mark.parametrize(
    ("stage", "candidate"),
    (
        ("insert_review_revision", _draft_body(po_number="PO-101", sku="SKU-MISSING")),
        ("replace_validation_issues", _draft_body(po_number="PO-101", sku="SKU-MISSING")),
        ("update_order_snapshot", _draft_body(po_number="PO-101", sku="SKU-MISSING")),
        ("insert_audit_event", _draft_body(po_number="PO-101", sku="SKU-MISSING")),
        (
            "replace_order_graph",
            _draft_body(po_number="PO-HIGH", sku="SKU-HV", quantity="50", submitted_price="25"),
        ),
    ),
)
def test_each_final_write_stage_rolls_back_atomically(monkeypatch, stage, candidate) -> None:
    asyncio.run(_assert_final_write_stage_rolls_back(monkeypatch, stage, candidate))


async def _assert_final_write_stage_rolls_back(monkeypatch, stage, candidate) -> None:
    case = _make_case()
    provider = StaticProvider()
    original_write = getattr(revalidation_service, stage)
    called = False

    async def fail_after_write(*args, **kwargs):
        nonlocal called
        called = True
        await original_write(*args, **kwargs)
        raise InjectedWriteFailure(stage)

    monkeypatch.setattr(revalidation_service, stage, fail_after_write)
    async with _case_client(case, provider) as (client, session_factory, _, _):
        before_order, before_issues, before_revisions, before_audits = await _read_case_state(
            session_factory, case.order_id
        )
        _, etag = await _get_detail_etag(client, case.order_id)
        with pytest.raises(InjectedWriteFailure, match=stage):
            await client.put(
                f"/v1/review/orders/{case.order_id}/draft",
                json=candidate,
                headers=_headers(etag),
            )
        assert called
        after_order, after_issues, after_revisions, after_audits = await _read_case_state(
            session_factory, case.order_id
        )
        assert after_order == before_order
        assert after_issues == before_issues
        assert after_revisions == before_revisions
        assert after_audits == before_audits
        async with session_factory() as session:
            notification_count = await session.scalar(
                select(func.count())
                .select_from(NotificationDeliveryModel)
                .where(NotificationDeliveryModel.order_id == case.order_id)
            )
        assert notification_count == 0

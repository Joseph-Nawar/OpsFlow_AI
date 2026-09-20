"""HTTP and PostgreSQL integration coverage for Phase 6 review reads."""

import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from opsflow.domain import SourceDocumentType
from opsflow.extraction.models import Evidence, ExtractedLine, ExtractionDraft
from opsflow.main import create_app
from opsflow.persistence.mappers import (
    extraction_draft_to_payload,
    review_revision_to_model,
)
from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    OrderModel,
    SourceDocumentModel,
    ValidationIssueModel,
)
from opsflow.review import ReviewChange, ReviewDraft, ReviewLine, ReviewRevision
from opsflow.settings import DevelopmentOperatorConfig, Settings
from opsflow.validation import BusinessDataLookupRequest, TrustedBusinessData

REPOSITORY_ROOT = Path(__file__).parents[2]
PHASE_6_REVISION = "0004_phase6_review_revisions"
_TOKEN = "test-review-reader-credential"


def test_openapi_exposes_only_the_three_review_read_routes() -> None:
    openapi_paths = create_app(_settings()).openapi()["paths"]
    paths = set(openapi_paths)
    review_paths = {path for path in paths if path.startswith("/v1/review/")}
    assert review_paths == {
        "/v1/review/orders",
        "/v1/review/orders/{order_id}",
        "/v1/review/orders/{order_id}/reference-data",
    }
    assert not any(path.endswith(("/draft", "/approve", "/reject", "/retry")) for path in paths)
    assert all(set(openapi_paths[path]) == {"get"} for path in review_paths)


def test_review_http_authentication_fails_closed_without_database_access() -> None:
    asyncio.run(_assert_authentication_fails_closed())


def test_review_queue_detail_and_reference_data_http_contracts() -> None:
    asyncio.run(_assert_review_read_contracts())


def test_reference_data_missing_draft_and_integrity_failures_are_distinct() -> None:
    asyncio.run(_assert_missing_draft_and_integrity_failures())


async def _assert_authentication_fails_closed() -> None:
    app = create_app(_settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            missing = await client.get("/v1/review/orders")
            unknown = await client.get(
                "/v1/review/orders", headers={"Authorization": "Bearer unknown-credential"}
            )
    for response in (missing, unknown):
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "UNAUTHENTICATED"
        assert _TOKEN not in response.text


async def _assert_review_read_contracts() -> None:
    _run_alembic("upgrade", "head")
    assert PHASE_6_REVISION in _run_alembic("current")
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    order_id, source_id, snapshot_id, revision_id, audit_id = (uuid4() for _ in range(5))
    preextract_id = uuid4()
    queue_ids = tuple(sorted((uuid4(), uuid4()), key=str))
    created_at = datetime(2090, 1, 1, tzinfo=UTC)
    queue_created_at = datetime.now(UTC).replace(year=9998)
    draft = _extraction_draft()
    human_draft = ReviewDraft(
        "Acme corrected",
        "CUST-001",
        "PO-READ-1",
        date(2026, 9, 1),
        date(2026, 10, 1),
        "USD",
        (ReviewLine("SKU-001", "Widget corrected", Decimal("2"), Decimal("10")),),
    )
    revision = ReviewRevision(
        revision_id,
        order_id,
        snapshot_id,
        1,
        human_draft,
        (ReviewChange("customer_name", "Acme", "Acme corrected"),),
        "reviewer-demo",
        created_at,
    )
    try:
        async with session_factory() as session:
            before_queue_total = await session.scalar(
                select(func.count())
                .select_from(OrderModel)
                .where(OrderModel.state == "NEEDS_REVIEW")
            )
            session.add_all(
                [
                    OrderModel(
                        id=order_id,
                        customer_reference=None,
                        po_number=None,
                        order_date=None,
                        requested_delivery_date=None,
                        currency=None,
                        state="NEEDS_REVIEW",
                        failure_origin=None,
                        created_at=created_at,
                    ),
                    SourceDocumentModel(
                        id=source_id,
                        order_id=order_id,
                        position=0,
                        document_type="PDF",
                        name="purchase-order.pdf",
                        mime_type="application/pdf",
                        sha256="a" * 64,
                        message_id="message-demo",
                        storage_reference="synthetic://purchase-order.pdf",
                        metadata_=[["source", "test"]],
                    ),
                    ExtractionSnapshotModel(
                        id=snapshot_id,
                        order_id=order_id,
                        source_document_id=source_id,
                        source_sha256="a" * 64,
                        source_document_type="PDF",
                        payload=extraction_draft_to_payload(draft),
                        created_at=created_at,
                    ),
                    ValidationIssueModel(
                        order_id=order_id,
                        position=0,
                        rule_code="HIGH_VALUE_APPROVAL_REQUIRED",
                        severity="WARNING",
                        field=None,
                        expected=None,
                        actual=None,
                        explanation="Elevated approval is required.",
                    ),
                    AuditEventModel(
                        id=audit_id,
                        order_id=order_id,
                        event_type="ORDER_NEEDS_REVIEW",
                        actor="system",
                        occurred_at=created_at,
                        description="Deterministic review required.",
                    ),
                    review_revision_to_model(revision),
                    OrderModel(
                        id=preextract_id,
                        customer_reference=None,
                        po_number=None,
                        order_date=None,
                        requested_delivery_date=None,
                        currency=None,
                        state="FAILED_RETRYABLE",
                        failure_origin="PROCESSING",
                        created_at=created_at,
                    ),
                    *[
                        OrderModel(
                            id=queue_id,
                            customer_reference=f"queue-{position}",
                            po_number=f"PO-QUEUE-{position}",
                            order_date=None,
                            requested_delivery_date=None,
                            currency=None,
                            state="NEEDS_REVIEW",
                            failure_origin=None,
                            created_at=queue_created_at,
                        )
                        for position, queue_id in enumerate(queue_ids)
                    ],
                    ValidationIssueModel(
                        order_id=queue_ids[0],
                        position=0,
                        rule_code="HIGH_VALUE_APPROVAL_REQUIRED",
                        severity="WARNING",
                        field=None,
                        expected=None,
                        actual=None,
                        explanation="Elevated approval is required.",
                    ),
                    ValidationIssueModel(
                        order_id=queue_ids[0],
                        position=1,
                        rule_code="MISSING_CUSTOMER_REFERENCE",
                        severity="ERROR",
                        field="customer_reference",
                        expected="trusted customer reference",
                        actual=None,
                        explanation="The customer is unresolved.",
                    ),
                    ValidationIssueModel(
                        order_id=queue_ids[1],
                        position=0,
                        rule_code="OPTIONAL_NOTE",
                        severity="INFO",
                        field=None,
                        expected=None,
                        actual=None,
                        explanation="Informational only.",
                    ),
                ]
            )
            await session.commit()

        app = create_app(_settings())
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                headers = {"Authorization": f"Bearer {_TOKEN}"}
                queue = await client.get(
                    "/v1/review/orders?states=NEEDS_REVIEW&limit=100", headers=headers
                )
                default_queue = await client.get("/v1/review/orders", headers=headers)
                detail = await client.get(f"/v1/review/orders/{order_id}", headers=headers)
                reference = await client.get(
                    f"/v1/review/orders/{order_id}/reference-data", headers=headers
                )
                audit = await client.get(f"/v1/orders/{order_id}/audit", headers=headers)
                preextract_detail = await client.get(
                    f"/v1/review/orders/{preextract_id}", headers=headers
                )
                first_new = await client.get(
                    "/v1/review/orders?states=NEEDS_REVIEW&limit=1"
                    f"&offset={int(before_queue_total or 0) + 1}",
                    headers=headers,
                )
                second_new = await client.get(
                    "/v1/review/orders?states=NEEDS_REVIEW&limit=1"
                    f"&offset={int(before_queue_total or 0) + 2}",
                    headers=headers,
                )

        assert queue.status_code == 200
        assert default_queue.status_code == 200
        assert default_queue.json()["states"] == [
            "NEEDS_REVIEW",
            "READY_FOR_APPROVAL",
            "FAILED_RETRYABLE",
        ]
        queue_item = next(item for item in queue.json()["items"] if item["id"] == str(order_id))
        assert queue_item["validation_issue_count"] == 1
        assert queue_item["high_value_approval_required"] is True
        assert queue.json()["states"] == ["NEEDS_REVIEW"]

        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail.headers["etag"] == detail_body["etag"]
        assert detail_body["effective_draft"]["customer_name"] == "Acme corrected"
        assert detail_body["original_extraction"]["customer_name"] == "Acme"
        assert detail_body["original_extraction"]["evidence"][0]["quote"] == "Acme"
        assert detail_body["operator"] == {"actor": "reviewer-demo", "role": "REVIEWER"}
        assert detail_body["actions"]["can_edit"] is True
        assert detail_body["actions"]["can_approve"] is False
        assert "audit_events" not in detail_body
        assert "token" not in detail_body and "prompt" not in detail_body

        assert reference.status_code == 200
        assert reference.json()["customer_candidates"] == [
            {"reference": "CUST-001", "name": "Acme Industries", "active": True}
        ]
        assert reference.json()["products_by_line"][0]["sku"] == "SKU-001"
        assert audit.status_code == 200
        assert isinstance(audit.json()["items"], list)
        assert preextract_detail.status_code == 200
        assert preextract_detail.json()["source_snapshot"] is None
        assert preextract_detail.json()["effective_draft"] is None
        assert first_new.status_code == second_new.status_code == 200
        assert first_new.json()["total"] == int(before_queue_total or 0) + 3
        assert first_new.json()["items"][0]["id"] == str(queue_ids[0])
        assert second_new.json()["items"][0]["id"] == str(queue_ids[1])
        assert first_new.json()["items"][0]["validation_issue_count"] == 2
        assert first_new.json()["items"][0]["high_value_approval_required"] is True
        assert second_new.json()["items"][0]["validation_issue_count"] == 1
        assert second_new.json()["items"][0]["high_value_approval_required"] is False

        unavailable_app = create_app(_settings())
        unavailable_app.state.review_runtime = replace(
            unavailable_app.state.review_runtime,
            provider=UnavailableProvider(),
        )
        async with unavailable_app.router.lifespan_context(unavailable_app):
            transport = httpx.ASGITransport(app=unavailable_app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                unavailable = await client.get(
                    f"/v1/review/orders/{order_id}/reference-data", headers=headers
                )
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "REFERENCE_DATA_UNAVAILABLE"
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(OrderModel).where(OrderModel.id.in_((order_id, preextract_id, *queue_ids)))
            )
        await engine.dispose()


async def _assert_missing_draft_and_integrity_failures() -> None:
    _run_alembic("upgrade", "head")
    assert PHASE_6_REVISION in _run_alembic("current")
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    no_snapshot_id = uuid4()
    invalid_review_id = uuid4()
    multiple_snapshot_id = uuid4()
    all_order_ids = (no_snapshot_id, invalid_review_id, multiple_snapshot_id)
    try:
        async with session_factory() as session:
            session.add_all(
                [
                    OrderModel(
                        id=no_snapshot_id,
                        state="FAILED_RETRYABLE",
                        failure_origin="PROCESSING",
                        created_at=datetime(2027, 1, 1, tzinfo=UTC),
                    ),
                    OrderModel(
                        id=invalid_review_id,
                        state="NEEDS_REVIEW",
                        failure_origin=None,
                        created_at=datetime(2027, 1, 2, tzinfo=UTC),
                    ),
                    OrderModel(
                        id=multiple_snapshot_id,
                        state="NEEDS_REVIEW",
                        failure_origin=None,
                        created_at=datetime(2027, 1, 3, tzinfo=UTC),
                    ),
                ]
            )
            for order_id, suffix in ((multiple_snapshot_id, "one"), (multiple_snapshot_id, "two")):
                source_id = uuid4()
                session.add(
                    SourceDocumentModel(
                        id=source_id,
                        order_id=order_id,
                        position=0 if suffix == "one" else 1,
                        document_type="PDF",
                        name=f"{suffix}.pdf",
                        mime_type="application/pdf",
                        sha256=("b" if suffix == "one" else "c") * 64,
                        message_id=None,
                        storage_reference=None,
                        metadata_=[],
                    )
                )
                snapshot_draft = _extraction_draft(("b" if suffix == "one" else "c") * 64)
                session.add(
                    ExtractionSnapshotModel(
                        id=uuid4(),
                        order_id=order_id,
                        source_document_id=source_id,
                        source_sha256=snapshot_draft.source_sha256,
                        source_document_type="PDF",
                        payload=extraction_draft_to_payload(snapshot_draft),
                        created_at=datetime(2027, 1, 3, tzinfo=UTC),
                    )
                )
            await session.commit()

        app = create_app(_settings())
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                headers = {"Authorization": f"Bearer {_TOKEN}"}
                no_draft = await client.get(
                    f"/v1/review/orders/{no_snapshot_id}/reference-data", headers=headers
                )
                missing_case = await client.get(
                    f"/v1/review/orders/{invalid_review_id}", headers=headers
                )
                multiple_case = await client.get(
                    f"/v1/review/orders/{multiple_snapshot_id}", headers=headers
                )
        assert no_draft.status_code == 409
        assert no_draft.json()["detail"]["code"] == "REVIEW_DRAFT_UNAVAILABLE"
        assert missing_case.status_code == 409
        assert missing_case.json()["detail"]["code"] == "REVIEW_CASE_UNAVAILABLE"
        assert multiple_case.status_code == 409
        assert multiple_case.json()["detail"]["code"] == "REVIEW_CASE_UNAVAILABLE"
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(OrderModel).where(OrderModel.id.in_(all_order_ids)))
        await engine.dispose()


def _settings() -> Settings:
    return Settings(
        review_dev_operators=(
            DevelopmentOperatorConfig(token=_TOKEN, actor="reviewer-demo", role="REVIEWER"),
        )
    )


class UnavailableProvider:
    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        del request
        raise RuntimeError("synthetic provider outage")


def _extraction_draft(source_sha: str = "a" * 64) -> ExtractionDraft:
    return ExtractionDraft(
        source_sha256=source_sha,
        source_document_type=SourceDocumentType.PDF,
        customer_name="Acme",
        customer_reference="CUST-001",
        po_number="PO-READ-1",
        order_date=date(2026, 9, 1),
        requested_delivery_date=date(2026, 10, 1),
        currency="USD",
        lines=(ExtractedLine("SKU-001", "Widget", Decimal("1"), Decimal("10")),),
        notes="Original note",
        evidence=(Evidence("customer_name", "page 1", "Acme"),),
    )


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

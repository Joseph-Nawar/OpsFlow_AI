"""End-to-end PostgreSQL and HTTP proofs for the Phase 7 intake pipeline."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import opsflow.application.orchestration as orchestration_module
import opsflow.main as main_module
from opsflow.application.errors import BusinessDataProviderError
from opsflow.application.review_commands import approve_order, retry_order
from opsflow.domain import AuditEvent, OrderState
from opsflow.extraction.errors import ProviderUnavailableError
from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.provider import StructuredGenerationResult
from opsflow.orchestration.composition import build_orchestration_runtime
from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    OrderCreationIdempotencyModel,
    OrderLineModel,
    OrderModel,
    ReviewRevisionModel,
    SourceDocumentModel,
    ValidationIssueModel,
)
from opsflow.persistence.repositories import (
    get_latest_audit_event_id,
    get_order_for_update,
    insert_audit_event,
    update_order_snapshot,
)
from opsflow.review import OperatorContext, OperatorRole
from opsflow.review.composition import build_demo_review_runtime
from opsflow.review.concurrency import compute_review_etag
from opsflow.settings import Settings
from opsflow.validation import BusinessDataLookupRequest, TrustedBusinessData

ORCHESTRATION_TOKEN = "synthetic-orchestration-service-credential"
INTAKE_PATH = "/v1/orchestration/intakes"
DOCUMENT = b"synthetic purchase order fixture\n"
KEY_PREFIX = "task9-pipeline-"
PROVIDER_PAYLOAD = {
    "customer_name": "Acme Industries",
    "customer_reference": "CUST-001",
    "po_number": "PO-SYNTHETIC",
    "order_date": "2025-01-01",
    "requested_delivery_date": "2025-01-08",
    "currency": "USD",
    "lines": [
        {
            "sku": "SKU-001",
            "description": "Widget",
            "quantity": "1",
            "submitted_price": "10",
        }
    ],
    "notes": None,
    "evidence": [],
}


@dataclass(frozen=True, slots=True)
class FixedReviewDateProvider:
    value: date

    def current_date(self) -> date:
        return self.value


class UnavailableProvider:
    async def generate_structured(self, request: object) -> StructuredGenerationResult:
        del request
        raise ProviderUnavailableError("synthetic provider outage")


class BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_structured(self, request: object) -> StructuredGenerationResult:
        del request
        self.started.set()
        await self.release.wait()
        return StructuredGenerationResult(payload=deepcopy(PROVIDER_PAYLOAD))


class SequenceProviderFactory:
    def __init__(self, providers: list[object]) -> None:
        self.providers = providers
        self.calls = 0

    def __call__(self) -> object:
        provider = self.providers[self.calls]
        self.calls += 1
        return provider


class TransientBusinessDataProvider:
    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.calls = 0

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        self.calls += 1
        if self.calls == 1:
            raise BusinessDataProviderError()
        return await self.delegate.get_validation_data(request)


def test_real_http_pipeline_reaches_ready_for_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_real_http_pipeline_reaches_ready_for_approval(monkeypatch))


async def _assert_real_http_pipeline_reaches_ready_for_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"{KEY_PREFIX}ready"
    app = _build_test_app(monkeypatch, date(2025, 1, 1))
    order_id: UUID | None = None
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(
                INTAKE_PATH,
                data={"document_type": "EMAIL_BODY", "message_id": "task9-ready"},
                files={"document": ("purchase-order.txt", DOCUMENT, "text/plain")},
                headers={
                    "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                    "Idempotency-Key": key,
                },
            )
        assert response.status_code == 201
        assert response.json()["state"] == "READY_FOR_APPROVAL"
        assert response.json()["idempotent_replay"] is False
        assert response.json()["failure_origin"] is None

        order_id, counts, event_types = await _read_order_evidence(key)
        assert counts == {"orders": 1, "sources": 1, "idempotency": 1, "snapshots": 1}
        message_id, source_metadata = await _read_source_provenance(order_id)
        assert message_id == "task9-ready"
        assert source_metadata == []
        assert event_types == [
            "ORDER_RECEIVED",
            "ORDER_PROCESSING_STARTED",
            "ORDER_EXTRACTION_COMPLETED",
            "EXTRACTION_SNAPSHOT_RECORDED",
            "ORDER_VALIDATED",
            "ORDER_READY_FOR_APPROVAL",
        ]
    finally:
        await _delete_orders((order_id,) if order_id is not None else ())


def test_real_handler_rejects_malformed_mime_before_phase2_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_malformed_mime_has_no_rows(monkeypatch))


async def _assert_malformed_mime_has_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}malformed-mime"
    before = await _table_counts()
    app = _build_test_app(monkeypatch, date(2025, 1, 1))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.post(
            INTAKE_PATH,
            data={"document_type": "EMAIL_BODY", "message_id": "task9-bad-mime"},
            files={"document": ("purchase-order.txt", DOCUMENT, "text/plain; broken")},
            headers={
                "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
                "Idempotency-Key": key,
            },
        )
    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "INVALID_ORCHESTRATION_INTAKE",
            "message": "The orchestration intake request is invalid.",
        }
    }
    assert "broken" not in response.text
    assert await _table_counts() == before


def test_real_http_pipeline_routes_deterministic_business_issue_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_business_issue_route(monkeypatch))


async def _assert_business_issue_route(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}review"
    app = _build_test_app(monkeypatch, date(2025, 1, 9))
    order_id: UUID | None = None
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await _post_intake(client, key)
    assert response.status_code == 201
    assert response.json()["state"] == OrderState.NEEDS_REVIEW.value
    assert response.json()["idempotent_replay"] is False
    order_id, counts, event_types = await _read_order_evidence(key)
    try:
        assert counts["snapshots"] == 1
        assert event_types[-1] == "ORDER_NEEDS_REVIEW"
        state, issue_count = await _read_state_and_issue_count(order_id)
        assert state is OrderState.NEEDS_REVIEW
        assert issue_count > 0
        assert "ORDER_PROCESSING_FAILED" not in event_types
        assert "ORDER_VALIDATION_FAILED" not in event_types
    finally:
        await _delete_orders((order_id,))


def test_terminal_replay_is_200_without_second_provider_or_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_terminal_replay(monkeypatch))


async def _assert_terminal_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}replay"
    factory = CountingProviderFactory()
    app = _build_test_app(monkeypatch, date(2025, 1, 1), factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
        second = await _post_intake(client, key)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["order_id"] == first.json()["order_id"]
    assert second.json()["idempotent_replay"] is True
    assert second.json()["state"] == "READY_FOR_APPROVAL"
    assert factory.calls == 1
    order_id, counts, event_types = await _read_order_evidence(key)
    try:
        assert counts == {"orders": 1, "sources": 1, "idempotency": 1, "snapshots": 1}
        assert event_types.count("ORDER_PROCESSING_STARTED") == 1
        assert event_types.count("ORDER_EXTRACTION_COMPLETED") == 1
    finally:
        await _delete_orders((order_id,))


def test_real_fingerprint_conflict_is_bounded_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_fingerprint_conflict(monkeypatch))


async def _assert_fingerprint_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}conflict"
    app = _build_test_app(monkeypatch, date(2025, 1, 1))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
        conflict = await _post_intake(client, key, content=b"changed source bytes\n")
    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert b"changed source bytes".decode() not in conflict.text
    order_id, counts, _ = await _read_order_evidence(key)
    try:
        assert counts["orders"] == 1
    finally:
        await _delete_orders((order_id,))


async def _assert_gmail_provenance_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    message_id = "phase8-gmail-valid-message"
    key = f"gmail:{message_id}"
    app = _build_test_app(monkeypatch, date(2025, 1, 1))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(
            client,
            key,
            source_system="GMAIL",
            message_id=message_id,
        )
        replay = await _post_intake(
            client,
            key,
            source_system="GMAIL",
            message_id=message_id,
        )
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["order_id"] == first.json()["order_id"]
    assert replay.json()["idempotent_replay"] is True
    order_id, counts, _ = await _read_order_evidence(key)
    try:
        assert counts["orders"] == 1
        assert counts["sources"] == 1
        persisted_message_id, source_metadata = await _read_source_provenance(order_id)
        assert persisted_message_id == message_id
        assert source_metadata == [["source_system", "GMAIL"]]
    finally:
        await _delete_orders((order_id,))


async def _assert_gmail_changed_bytes_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    message_id = "phase8-gmail-changed-message"
    key = f"gmail:{message_id}"
    app = _build_test_app(monkeypatch, date(2025, 1, 1))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(
            client,
            key,
            source_system="GMAIL",
            message_id=message_id,
        )
        conflict = await _post_intake(
            client,
            key,
            content=b"changed Gmail source bytes\n",
            source_system="GMAIL",
            message_id=message_id,
        )
    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert "changed Gmail source bytes" not in conflict.text
    order_id, counts, _ = await _read_order_evidence(key)
    try:
        assert counts["orders"] == 1
        assert counts["sources"] == 1
    finally:
        await _delete_orders((order_id,))


async def _assert_invalid_gmail_provenance_has_no_database_effect(
    monkeypatch: pytest.MonkeyPatch,
    source_system: str,
    message_id: str | None,
    key: str,
) -> None:
    before = await _table_counts()
    app = _build_test_app(monkeypatch, date(2025, 1, 1))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await _post_intake(
            client,
            key,
            source_system=source_system,
            message_id=message_id,
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_ORCHESTRATION_INTAKE"
    assert await _table_counts() == before


def test_processing_failure_is_retryable_and_reviewer_retry_resumes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_processing_retry(monkeypatch))


async def _assert_processing_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}processing-retry"
    factory = SequenceProviderFactory(
        [
            UnavailableProvider(),
            FakeProvider((StructuredGenerationResult(payload=deepcopy(PROVIDER_PAYLOAD)),)),
        ]
    )
    app = _build_test_app(monkeypatch, date(2025, 1, 1), factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
    assert first.status_code == 201
    assert first.json()["state"] == "FAILED_RETRYABLE"
    assert first.json()["failure_origin"] == "PROCESSING"
    order_id, _, _ = await _read_order_evidence(key)
    try:
        await _reviewer_retry(order_id)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            resumed = await _post_intake(client, key)
            consumed = await _post_intake(client, key)
        assert resumed.status_code == 200
        assert resumed.json()["idempotent_replay"] is True
        assert resumed.json()["state"] == "READY_FOR_APPROVAL"
        assert consumed.status_code == 200
        assert consumed.json()["state"] == "READY_FOR_APPROVAL"
        _, _, event_types = await _read_order_evidence(key)
        assert event_types.count("ORDER_PROCESSING_FAILED") == 1
        assert event_types.count("ORDER_PROCESSING_RESUMED") == 1
        assert event_types.count("ORDER_PROCESSING_STARTED") == 1
        assert factory.calls == 2
    finally:
        await _delete_orders((order_id,))


def test_concurrent_processing_retry_redelivery_has_one_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_concurrent_processing_retry(monkeypatch))


async def _assert_concurrent_processing_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}processing-concurrent"
    blocking = BlockingProvider()
    factory = SequenceProviderFactory([UnavailableProvider(), blocking])
    app = _build_test_app(monkeypatch, date(2025, 1, 1), factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
    assert first.json()["state"] == "FAILED_RETRYABLE"
    order_id, _, _ = await _read_order_evidence(key)
    try:
        await _reviewer_retry(order_id)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            owner_task = asyncio.create_task(_post_intake(client, key))
            await blocking.started.wait()
            loser = await _post_intake(client, key)
            blocking.release.set()
            owner = await owner_task
        assert loser.status_code == 202
        assert loser.json()["state"] == "PROCESSING"
        assert owner.status_code == 200
        assert owner.json()["state"] == "READY_FOR_APPROVAL"
        assert factory.calls == 2
        _, _, event_types = await _read_order_evidence(key)
        assert event_types.count("ORDER_PROCESSING_RESUMED") == 1
    finally:
        await _delete_orders((order_id,))


def test_simultaneous_same_key_http_execution_has_one_provider_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_simultaneous_same_key_http_execution(monkeypatch))


async def _assert_simultaneous_same_key_http_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"{KEY_PREFIX}same-key-concurrent"
    blocking = BlockingProvider()
    factory = SequenceProviderFactory([blocking])
    app = _build_test_app(monkeypatch, date(2025, 1, 1), factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first_task = asyncio.create_task(_post_intake(client, key))
        await blocking.started.wait()
        second = await _post_intake(client, key)
        assert second.status_code == 202
        blocking.release.set()
        first = await first_task
    assert first.status_code in {200, 201}
    assert {first.json()["idempotent_replay"], second.json()["idempotent_replay"]} == {
        False,
        True,
    }
    assert factory.calls == 1
    order_id, counts, event_types = await _read_order_evidence(key)
    try:
        assert counts == {"orders": 1, "sources": 1, "idempotency": 1, "snapshots": 1}
        assert event_types.count("ORDER_PROCESSING_STARTED") == 1
    finally:
        await _delete_orders((order_id,))


def test_extracted_retry_reconstructs_document_without_second_extraction_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_extracted_reconstruction(monkeypatch))


async def _assert_extracted_reconstruction(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}extracted-retry"
    business_provider = TransientBusinessDataProvider(build_demo_review_runtime().provider)
    factory = SequenceProviderFactory(
        [
            FakeProvider((StructuredGenerationResult(payload=deepcopy(PROVIDER_PAYLOAD)),)),
            FakeProvider((StructuredGenerationResult(payload=deepcopy(PROVIDER_PAYLOAD)),)),
        ]
    )
    app = _build_test_app(
        monkeypatch,
        date(2025, 1, 1),
        factory,
        business_data_provider=business_provider,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
    assert first.json()["state"] == "FAILED_RETRYABLE"
    assert first.json()["failure_origin"] == "EXTRACTED"
    order_id, _, _ = await _read_order_evidence(key)
    try:
        await _reviewer_retry(order_id)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            resumed = await _post_intake(client, key)
        assert resumed.status_code == 200
        assert resumed.json()["state"] == "READY_FOR_APPROVAL"
        assert business_provider.calls == 2
        assert factory.calls == 2
        _, counts, event_types = await _read_order_evidence(key)
        assert counts["snapshots"] == 1
        assert event_types.count("ORDER_EXTRACTION_COMPLETED") == 1
        assert event_types.count("ORDER_EXTRACTION_RESUMED") == 1
        assert event_types.count("ORDER_VALIDATION_FAILED") == 1
    finally:
        await _delete_orders((order_id,))


def test_source_identity_conflict_is_bounded_and_does_not_consume_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_source_identity_conflict(monkeypatch))


async def _assert_source_identity_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}source-conflict"
    factory = CountingProviderFactory()
    app = _build_test_app(monkeypatch, date(2025, 1, 1), factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
    assert first.status_code == 201
    order_id, _, event_types_before = await _read_order_evidence(key)
    try:
        await _corrupt_source_sha(order_id)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            conflict = await _post_intake(client, key)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "SOURCE_IDENTITY_CONFLICT"
        assert factory.calls == 1
        _, _, event_types_after = await _read_order_evidence(key)
        assert event_types_after == event_types_before
    finally:
        await _delete_orders((order_id,))


def test_post_claim_persistence_failure_is_visible_and_not_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_post_claim_failure_is_not_reclaimed(monkeypatch))


async def _assert_post_claim_failure_is_not_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"{KEY_PREFIX}post-claim"
    factory = CountingProviderFactory()
    app = _build_test_app(monkeypatch, date(2025, 1, 1), factory)

    async def fail_extraction_persistence(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SQLAlchemyError("synthetic persistence outage")

    original_extraction_persistence = orchestration_module._persist_extraction_completed
    monkeypatch.setattr(
        orchestration_module,
        "_persist_extraction_completed",
        fail_extraction_persistence,
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
    assert first.status_code == 503
    assert first.json()["detail"]["code"] == "ORCHESTRATION_UNAVAILABLE"
    order_id, _, event_types = await _read_order_evidence(key)
    assert event_types == ["ORDER_RECEIVED", "ORDER_PROCESSING_STARTED"]

    monkeypatch.setattr(
        orchestration_module,
        "_persist_extraction_completed",
        original_extraction_persistence,
    )
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            duplicate = await _post_intake(client, key)
        assert duplicate.status_code == 202
        assert duplicate.json()["state"] == "PROCESSING"
        assert factory.calls == 1
    finally:
        await _delete_orders((order_id,))


def test_resumed_post_claim_persistence_failure_consumes_resume_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_resumed_post_claim_failure(monkeypatch))


async def _assert_resumed_post_claim_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}resumed-post-claim"
    factory = SequenceProviderFactory(
        [
            UnavailableProvider(),
            FakeProvider((StructuredGenerationResult(payload=deepcopy(PROVIDER_PAYLOAD)),)),
        ]
    )
    app = _build_test_app(monkeypatch, date(2025, 1, 1), factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
    assert first.json()["state"] == "FAILED_RETRYABLE"
    order_id, _, _ = await _read_order_evidence(key)
    original_extraction_persistence = orchestration_module._persist_extraction_completed

    async def fail_resumed_persistence(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SQLAlchemyError("synthetic resumed persistence outage")

    try:
        await _reviewer_retry(order_id)
        monkeypatch.setattr(
            orchestration_module,
            "_persist_extraction_completed",
            fail_resumed_persistence,
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            failed_resume = await _post_intake(client, key)
        assert failed_resume.status_code == 503
        monkeypatch.setattr(
            orchestration_module,
            "_persist_extraction_completed",
            original_extraction_persistence,
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            duplicate = await _post_intake(client, key)
        assert duplicate.status_code == 202
        assert duplicate.json()["state"] == "PROCESSING"
        assert factory.calls == 2
        _, _, event_types = await _read_order_evidence(key)
        assert event_types.count("ORDER_PROCESSING_RESUMED") == 1
    finally:
        await _delete_orders((order_id,))


def test_restored_syncing_redelivery_stands_down_without_provider_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_assert_restored_syncing_stand_down(monkeypatch))


async def _assert_restored_syncing_stand_down(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"{KEY_PREFIX}syncing"
    factory = CountingProviderFactory()
    app = _build_test_app(monkeypatch, date(2025, 1, 1), factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        first = await _post_intake(client, key)
    assert first.status_code == 201
    order_id, _, _ = await _read_order_evidence(key)
    try:
        await _approve_order(order_id)
        await _persist_syncing_retryable_failure(order_id)
        await _reviewer_retry(order_id)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            response = await _post_intake(client, key)
        assert response.status_code == 200
        assert response.json()["state"] == "SYNCING"
        assert response.json()["idempotent_replay"] is True
        assert factory.calls == 1
        _, _, event_types = await _read_order_evidence(key)
        assert "ORDER_PROCESSING_RESUMED" not in event_types
        assert "ORDER_EXTRACTION_RESUMED" not in event_types
    finally:
        await _delete_orders((order_id,))


def _build_test_app(
    monkeypatch: pytest.MonkeyPatch,
    review_date: date,
    extraction_provider_factory: Callable[[], object] | None = None,
    business_data_provider: object | None = None,
):
    review_runtime = replace(
        build_demo_review_runtime(),
        date_provider=FixedReviewDateProvider(review_date),
    )
    if business_data_provider is not None:
        review_runtime = replace(review_runtime, provider=business_data_provider)
    monkeypatch.setattr(main_module, "build_demo_review_runtime", lambda: review_runtime)

    def build_runtime(settings: Settings, *, review_runtime=None):
        return build_orchestration_runtime(
            settings,
            extraction_provider_factory=extraction_provider_factory,
            review_runtime=review_runtime,
        )

    monkeypatch.setattr(main_module, "build_orchestration_runtime", build_runtime)
    return main_module.create_app(Settings(orchestration_token=ORCHESTRATION_TOKEN))


async def _read_order_evidence(
    idempotency_key: str,
) -> tuple[UUID, dict[str, int], list[str]]:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            order_id = await session.scalar(
                select(OrderCreationIdempotencyModel.order_id).where(
                    OrderCreationIdempotencyModel.idempotency_key == idempotency_key
                )
            )
            assert order_id is not None
            counts = {
                "orders": await session.scalar(
                    select(OrderModel.id).where(OrderModel.id == order_id)
                )
                is not None,
                "sources": len(
                    (
                        await session.scalars(
                            select(SourceDocumentModel).where(
                                SourceDocumentModel.order_id == order_id
                            )
                        )
                    ).all()
                ),
                "idempotency": len(
                    (
                        await session.scalars(
                            select(OrderCreationIdempotencyModel).where(
                                OrderCreationIdempotencyModel.order_id == order_id
                            )
                        )
                    ).all()
                ),
                "snapshots": len(
                    (
                        await session.scalars(
                            select(ExtractionSnapshotModel).where(
                                ExtractionSnapshotModel.order_id == order_id
                            )
                        )
                    ).all()
                ),
            }
            events = (
                await session.scalars(
                    select(AuditEventModel)
                    .where(AuditEventModel.order_id == order_id)
                    .order_by(AuditEventModel.occurred_at, AuditEventModel.id)
                )
            ).all()
            return (
                order_id,
                {key: int(value) for key, value in counts.items()},
                [event.event_type for event in events],
            )
    finally:
        await engine.dispose()


async def _read_state_and_issue_count(order_id: UUID) -> tuple[OrderState, int]:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            order = await session.get(OrderModel, order_id)
            assert order is not None
            issues = (
                await session.scalars(
                    select(ValidationIssueModel).where(ValidationIssueModel.order_id == order_id)
                )
            ).all()
            return OrderState(order.state), len(issues)
    finally:
        await engine.dispose()


async def _read_source_provenance(order_id: UUID) -> tuple[str | None, list[list[str]]]:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            source = await session.scalar(
                select(SourceDocumentModel).where(SourceDocumentModel.order_id == order_id)
            )
            assert source is not None
            return source.message_id, source.metadata_
    finally:
        await engine.dispose()


async def _corrupt_source_sha(order_id: UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                update(SourceDocumentModel)
                .where(SourceDocumentModel.order_id == order_id)
                .values(sha256="f" * 64)
            )
    finally:
        await engine.dispose()


async def _table_counts() -> dict[str, int]:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            return {
                "orders": len((await session.scalars(select(OrderModel))).all()),
                "sources": len((await session.scalars(select(SourceDocumentModel))).all()),
                "idempotency": len(
                    (await session.scalars(select(OrderCreationIdempotencyModel))).all()
                ),
                "audits": len((await session.scalars(select(AuditEventModel))).all()),
            }
    finally:
        await engine.dispose()


async def _post_intake(
    client: httpx.AsyncClient,
    key: str,
    *,
    content: bytes = DOCUMENT,
    mime_type: str = "text/plain",
    message_id: str | None = "task9-message",
    source_system: str | None = None,
) -> httpx.Response:
    form_data = {"document_type": "EMAIL_BODY"}
    if message_id is not None:
        form_data["message_id"] = message_id
    if source_system is not None:
        form_data["source_system"] = source_system
    return await client.post(
        INTAKE_PATH,
        data=form_data,
        files={"document": ("purchase-order.txt", content, mime_type)},
        headers={
            "Authorization": f"Bearer {ORCHESTRATION_TOKEN}",
            "Idempotency-Key": key,
        },
    )


class CountingProviderFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> FakeProvider:
        self.calls += 1
        return FakeProvider((StructuredGenerationResult(payload=deepcopy(PROVIDER_PAYLOAD)),))


async def _reviewer_retry(order_id: UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    operator = OperatorContext(actor="reviewer:task9", role=OperatorRole.REVIEWER)
    try:
        async with AsyncSession(engine) as session:
            persisted = await get_order_for_update(session, order_id)
            assert persisted is not None
            latest_audit_id = await get_latest_audit_event_id(session, order_id)
            await session.rollback()
            etag = compute_review_etag(
                order_id,
                persisted.order.state,
                persisted.order.failure_origin,
                None,
                None,
                latest_audit_id,
            )
            result = await retry_order(
                session,
                order_id,
                etag,
                operator,
                datetime(2030, 1, 1, tzinfo=UTC),
            )
            assert result.state in {
                OrderState.PROCESSING,
                OrderState.EXTRACTED,
                OrderState.SYNCING,
            }
    finally:
        await engine.dispose()


async def _approve_order(order_id: UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    operator = OperatorContext(actor="approver:task9", role=OperatorRole.APPROVER)
    try:
        async with AsyncSession(engine) as session:
            persisted = await get_order_for_update(session, order_id)
            assert persisted is not None
            latest_audit_id = await get_latest_audit_event_id(session, order_id)
            await session.rollback()
            etag = compute_review_etag(
                order_id,
                persisted.order.state,
                persisted.order.failure_origin,
                None,
                None,
                latest_audit_id,
            )
            result = await approve_order(
                session,
                order_id,
                etag,
                operator,
                datetime(2030, 1, 1, tzinfo=UTC),
                "http://localhost:5173",
            )
            assert result.state is OrderState.APPROVED
    finally:
        await engine.dispose()


async def _persist_syncing_retryable_failure(order_id: UUID) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with AsyncSession(engine) as session, session.begin():
            persisted = await get_order_for_update(session, order_id)
            assert persisted is not None
            syncing = persisted.order.transition_to(OrderState.SYNCING)
            await update_order_snapshot(session, syncing)
            await insert_audit_event(
                session,
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type="ORDER_SYNC_STARTED",
                    actor="system",
                    occurred_at=datetime(2030, 1, 1, 0, 0, 1, tzinfo=UTC),
                    description="Synthetic synchronization started.",
                ),
            )
            failed = syncing.transition_to(OrderState.FAILED_RETRYABLE)
            await update_order_snapshot(session, failed)
            await insert_audit_event(
                session,
                AuditEvent(
                    id=uuid4(),
                    order_id=order_id,
                    event_type="ORDER_SYNC_FAILED",
                    actor="system",
                    occurred_at=datetime(2030, 1, 1, 0, 0, 2, tzinfo=UTC),
                    description="Synthetic synchronization failure.",
                ),
            )
    finally:
        await engine.dispose()


async def _delete_orders(order_ids: tuple[UUID, ...]) -> None:
    if not order_ids:
        return
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as connection:
            for model in (
                ReviewRevisionModel,
                ExtractionSnapshotModel,
                ValidationIssueModel,
                AuditEventModel,
                OrderLineModel,
                SourceDocumentModel,
                OrderCreationIdempotencyModel,
            ):
                await connection.execute(delete(model).where(model.order_id.in_(order_ids)))
            await connection.execute(delete(OrderModel).where(OrderModel.id.in_(order_ids)))
    finally:
        await engine.dispose()

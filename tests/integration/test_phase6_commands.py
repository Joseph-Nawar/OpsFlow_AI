"""HTTP and PostgreSQL integration coverage for M6D review commands."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from opsflow.api import review as review_api
from opsflow.api.orders import get_session
from opsflow.application import review_commands
from opsflow.application.errors import (
    InvalidRejectionReasonError,
    InvalidReviewStateError,
    OrderNotFoundError,
    ReviewPersistenceConflictError,
    ReviewPreconditionFailedError,
    ReviewPreconditionRequiredError,
)
from opsflow.application.review_commands import ReviewCommandResult
from opsflow.domain import OrderState, SourceDocumentType
from opsflow.extraction.models import ExtractedLine, ExtractionDraft
from opsflow.main import create_app
from opsflow.persistence.mappers import extraction_draft_to_payload
from opsflow.persistence.models import (
    AuditEventModel,
    ExtractionSnapshotModel,
    OrderModel,
    SourceDocumentModel,
    ValidationIssueModel,
)
from opsflow.persistence.repositories import get_audit_events, get_order
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings
from opsflow.validation import (
    BusinessDataLookupRequest,
    TrustedBusinessData,
    TrustedCustomer,
    TrustedProduct,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
PHASE_6_REVISION = "0004_phase6_review_revisions"
REVIEWER_TOKEN = "synthetic-command-reviewer-credential"
APPROVER_TOKEN = "synthetic-command-approver-credential"
ELEVATED_TOKEN = "synthetic-command-elevated-credential"
ACTORS = {
    REVIEWER_TOKEN: "reviewer-test",
    APPROVER_TOKEN: "approver-test",
    ELEVATED_TOKEN: "elevated-test",
}


def test_openapi_exposes_only_the_approved_m6d_command_surface() -> None:
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
    assert {path: set(value) for path, value in review_paths.items()} == {
        "/v1/review/orders": {"get"},
        "/v1/review/orders/{order_id}": {"get"},
        "/v1/review/orders/{order_id}/reference-data": {"get"},
        "/v1/review/orders/{order_id}/draft": {"put"},
        "/v1/review/orders/{order_id}/approve": {"post"},
        "/v1/review/orders/{order_id}/reject": {"post"},
        "/v1/review/orders/{order_id}/retry": {"post"},
    }
    for endpoint in ("approve", "reject", "retry"):
        operation = review_paths[f"/v1/review/orders/{{order_id}}/{endpoint}"]["post"]
        if endpoint == "reject":
            request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
            assert request_schema["$ref"].endswith("/ReviewRejectRequest")
            reject_schema = openapi["components"]["schemas"]["ReviewRejectRequest"]
            assert set(reject_schema["required"]) == {"reason"}
            assert reject_schema["additionalProperties"] is False
        else:
            assert "requestBody" not in operation
        if_match = next(item for item in operation["parameters"] if item["name"] == "If-Match")
        assert if_match["required"] is True
        assert {"200", "403", "404", "409", "412", "422", "428"} <= set(operation["responses"])
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert response_schema["$ref"].endswith("/ReviewCommandResponse")


def test_command_authorization_matrix_switching_audit_and_retry_origins() -> None:
    asyncio.run(_assert_command_matrix())


def test_command_preconditions_and_rejection_body_are_bounded() -> None:
    asyncio.run(_assert_preconditions_and_rejection_body())


def test_command_write_failures_rollback_state_and_all_audit_events() -> None:
    asyncio.run(_assert_atomic_command_writes())


def test_preflight_state_or_audit_generation_race_is_rejected(monkeypatch) -> None:
    asyncio.run(_assert_preflight_generation_race(monkeypatch))


def test_retry_etag_cannot_be_reused_after_same_state_aba() -> None:
    asyncio.run(_assert_retry_aba_is_closed())


def test_volatile_reference_data_does_not_change_stable_review_etag() -> None:
    asyncio.run(_assert_reference_data_is_outside_etag())


def test_command_transport_maps_safe_errors_and_returns_narrow_etag_result(monkeypatch) -> None:
    asyncio.run(_assert_transport_mapping_without_database(monkeypatch))


@dataclass(frozen=True, slots=True)
class CommandCase:
    order_id: UUID
    source_id: UUID
    snapshot_id: UUID
    source_sha256: str
    state: OrderState
    failure_origin: OrderState | None
    high_value: bool


def _case(
    state: OrderState,
    *,
    failure_origin: OrderState | None = None,
    high_value: bool = False,
) -> CommandCase:
    return CommandCase(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4().hex * 2,
        state,
        failure_origin,
        high_value,
    )


@asynccontextmanager
async def _command_client(
    cases: tuple[CommandCase, ...],
) -> AsyncIterator[tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession], object]]:
    _run_alembic("upgrade", "head")
    assert PHASE_6_REVISION in _run_alembic("current")
    engine = create_async_engine(Settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    await _seed_cases(session_factory, cases)
    app = create_app(_settings())

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                yield client, session_factory, app
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(OrderModel).where(OrderModel.id.in_(tuple(case.order_id for case in cases)))
            )
        await engine.dispose()


async def _seed_cases(
    session_factory: async_sessionmaker[AsyncSession], cases: tuple[CommandCase, ...]
) -> None:
    created_at = datetime(2000, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        for case in cases:
            session.add(
                OrderModel(
                    id=case.order_id,
                    customer_reference="CUST-001",
                    po_number="PO-COMMAND",
                    order_date=date(2030, 1, 1),
                    requested_delivery_date=date(2030, 2, 1),
                    currency="USD",
                    state=case.state.value,
                    failure_origin=(
                        case.failure_origin.value if case.failure_origin is not None else None
                    ),
                    created_at=created_at,
                )
            )
            await session.flush()
            session.add(
                SourceDocumentModel(
                    id=case.source_id,
                    order_id=case.order_id,
                    position=0,
                    document_type="PDF",
                    name="command-order.pdf",
                    mime_type="application/pdf",
                    sha256=case.source_sha256,
                    message_id=None,
                    storage_reference=None,
                    metadata_=[],
                )
            )
            await session.flush()
            extraction = ExtractionDraft(
                source_sha256=case.source_sha256,
                source_document_type=SourceDocumentType.PDF,
                customer_name="Acme Industries",
                customer_reference="CUST-001",
                po_number="PO-COMMAND",
                order_date=date(2030, 1, 1),
                requested_delivery_date=date(2030, 2, 1),
                currency="USD",
                lines=(ExtractedLine("SKU-001", "Widget", Decimal("1"), Decimal("10")),),
                notes="Original extraction note",
                evidence=(),
            )
            has_extraction_snapshot = not (
                case.state is OrderState.FAILED_RETRYABLE
                and case.failure_origin in (OrderState.PROCESSING, OrderState.EXTRACTED)
            )
            if has_extraction_snapshot:
                session.add(
                    ExtractionSnapshotModel(
                        id=case.snapshot_id,
                        order_id=case.order_id,
                        source_document_id=case.source_id,
                        source_sha256=case.source_sha256,
                        source_document_type="PDF",
                        payload=extraction_draft_to_payload(extraction),
                        created_at=created_at,
                    )
                )
            if case.high_value:
                session.add(
                    ValidationIssueModel(
                        order_id=case.order_id,
                        position=0,
                        rule_code="HIGH_VALUE_APPROVAL_REQUIRED",
                        severity="WARNING",
                        field="order_total",
                        expected="1000",
                        actual="1200",
                        explanation="Elevated approval is required.",
                    )
                )
            session.add(
                AuditEventModel(
                    id=uuid4(),
                    order_id=case.order_id,
                    event_type="ORDER_READY_FOR_APPROVAL",
                    actor="system",
                    occurred_at=created_at,
                    description="Seeded review command case.",
                )
            )
            await session.flush()
        await session.commit()


async def _assert_command_matrix() -> None:
    ordinary = _case(OrderState.READY_FOR_APPROVAL)
    high_value = _case(OrderState.READY_FOR_APPROVAL, high_value=True)
    high_reject = _case(OrderState.READY_FOR_APPROVAL, high_value=True)
    elevated_high_reject = _case(OrderState.READY_FOR_APPROVAL, high_value=True)
    needs_reviewer = _case(OrderState.NEEDS_REVIEW)
    ready_reviewer = _case(OrderState.READY_FOR_APPROVAL)
    needs_approver = _case(OrderState.NEEDS_REVIEW)
    retries = tuple(
        _case(OrderState.FAILED_RETRYABLE, failure_origin=origin)
        for origin in (OrderState.PROCESSING, OrderState.EXTRACTED, OrderState.SYNCING)
    )
    cases = (
        ordinary,
        high_value,
        high_reject,
        elevated_high_reject,
        needs_reviewer,
        ready_reviewer,
        needs_approver,
        *retries,
    )
    async with _command_client(cases) as (client, session_factory, _):
        reviewer_detail = await _get_detail(client, ordinary.order_id, REVIEWER_TOKEN)
        assert reviewer_detail.json()["operator"] == {"actor": "reviewer-test", "role": "REVIEWER"}
        assert reviewer_detail.json()["actions"]["can_approve"] is False
        approver_detail = await _get_detail(client, ordinary.order_id, APPROVER_TOKEN)
        assert approver_detail.json()["operator"] == {"actor": "approver-test", "role": "APPROVER"}
        assert approver_detail.json()["actions"]["can_approve"] is True
        ordinary_etag = approver_detail.headers["etag"]

        reviewer_approval = await _post_command(
            client,
            "approve",
            ready_reviewer.order_id,
            REVIEWER_TOKEN,
            _etag_from_detail(await _get_detail(client, ready_reviewer.order_id, REVIEWER_TOKEN)),
        )
        assert reviewer_approval.status_code == 403
        assert reviewer_approval.json()["detail"]["code"] == "FORBIDDEN"

        approved = await _post_command(
            client, "approve", ordinary.order_id, APPROVER_TOKEN, ordinary_etag
        )
        assert approved.status_code == 200, approved.text
        _assert_command_response(approved, ordinary.order_id, "APPROVED", None)
        assert approved.headers["etag"] != ordinary_etag
        stale = await _post_command(
            client, "approve", ordinary.order_id, APPROVER_TOKEN, ordinary_etag
        )
        assert stale.status_code == 412
        assert stale.json()["detail"]["code"] == "PRECONDITION_FAILED"

        audit = await client.get(
            f"/v1/orders/{ordinary.order_id}/audit",
            headers=_headers(APPROVER_TOKEN),
        )
        assert audit.status_code == 200
        approval_events = [
            item for item in audit.json()["items"] if item["event_type"] == "ORDER_APPROVED"
        ]
        assert [(item["actor"], item["description"]) for item in approval_events] == [
            ("approver-test", "Order approved by operator.")
        ]
        detail_after_approval = await _get_detail(client, ordinary.order_id, APPROVER_TOKEN)
        assert "audit_events" not in detail_after_approval.json()

        high_detail = await _get_detail(client, high_value.order_id, APPROVER_TOKEN)
        high_etag = _etag_from_detail(high_detail)
        ordinary_high_approval = await _post_command(
            client, "approve", high_value.order_id, APPROVER_TOKEN, high_etag
        )
        assert ordinary_high_approval.status_code == 403
        elevated_detail = await _get_detail(client, high_value.order_id, ELEVATED_TOKEN)
        assert elevated_detail.json()["operator"] == {
            "actor": "elevated-test",
            "role": "ELEVATED_APPROVER",
        }
        assert elevated_detail.json()["actions"]["can_approve"] is True
        elevated_approval = await _post_command(
            client,
            "approve",
            high_value.order_id,
            ELEVATED_TOKEN,
            elevated_detail.headers["etag"],
        )
        assert elevated_approval.status_code == 200, elevated_approval.text
        _assert_command_response(elevated_approval, high_value.order_id, "APPROVED", None)
        async with session_factory() as session:
            persisted_high_value = await get_order(session, high_value.order_id)
            assert persisted_high_value is not None
            assert any(
                issue.rule_code == "HIGH_VALUE_APPROVAL_REQUIRED"
                and issue.severity.value == "WARNING"
                for issue in persisted_high_value.validation_issues
            )

        high_reject_detail = await _get_detail(client, high_reject.order_id, APPROVER_TOKEN)
        reject_etag = _etag_from_detail(high_reject_detail)
        rejected_high = await _post_command(
            client,
            "reject",
            high_reject.order_id,
            APPROVER_TOKEN,
            reject_etag,
            body={"reason": "  duplicate order  "},
        )
        assert rejected_high.status_code == 200, rejected_high.text
        _assert_command_response(rejected_high, high_reject.order_id, "REJECTED", None)
        high_reject_audits = await _audit_items(client, high_reject.order_id)
        high_reject_event = next(
            item for item in high_reject_audits if item["event_type"] == "ORDER_REJECTED"
        )
        assert high_reject_event["actor"] == "approver-test"
        assert high_reject_event["description"] == "Order rejected. Reason: duplicate order"
        rejected_with_stale = await _post_command(
            client,
            "reject",
            high_reject.order_id,
            APPROVER_TOKEN,
            reject_etag,
            body={"reason": "should not be applied twice"},
        )
        assert rejected_with_stale.status_code == 412
        elevated_reject_etag = _etag_from_detail(
            await _get_detail(client, elevated_high_reject.order_id, ELEVATED_TOKEN)
        )
        elevated_high_rejected = await _post_command(
            client,
            "reject",
            elevated_high_reject.order_id,
            ELEVATED_TOKEN,
            elevated_reject_etag,
            body={"reason": "elevated operator rejects"},
        )
        assert elevated_high_rejected.status_code == 200, elevated_high_rejected.text
        _assert_command_response(
            elevated_high_rejected, elevated_high_reject.order_id, "REJECTED", None
        )

        reviewer_detail = await _get_detail(client, needs_reviewer.order_id, REVIEWER_TOKEN)
        reviewer_etag = _etag_from_detail(reviewer_detail)
        reviewer_rejected = await _post_command(
            client,
            "reject",
            needs_reviewer.order_id,
            REVIEWER_TOKEN,
            reviewer_etag,
            body={"reason": "not a purchase order"},
        )
        assert reviewer_rejected.status_code == 200, reviewer_rejected.text
        _assert_command_response(reviewer_rejected, needs_reviewer.order_id, "REJECTED", None)

        ready_reject_etag = _etag_from_detail(
            await _get_detail(client, ready_reviewer.order_id, REVIEWER_TOKEN)
        )
        reviewer_ready_rejection = await _post_command(
            client,
            "reject",
            ready_reviewer.order_id,
            REVIEWER_TOKEN,
            ready_reject_etag,
            body={"reason": "not permitted"},
        )
        assert reviewer_ready_rejection.status_code == 403
        needs_reject_etag = _etag_from_detail(
            await _get_detail(client, needs_approver.order_id, APPROVER_TOKEN)
        )
        approver_needs_rejection = await _post_command(
            client,
            "reject",
            needs_approver.order_id,
            APPROVER_TOKEN,
            needs_reject_etag,
            body={"reason": "not permitted"},
        )
        assert approver_needs_rejection.status_code == 403
        invalid_state_approval = await _post_command(
            client,
            "approve",
            needs_approver.order_id,
            APPROVER_TOKEN,
            needs_reject_etag,
        )
        assert invalid_state_approval.status_code == 409
        assert invalid_state_approval.json()["detail"]["code"] == "INVALID_REVIEW_STATE"
        invalid_state_retry = await _post_command(
            client,
            "retry",
            needs_approver.order_id,
            REVIEWER_TOKEN,
            needs_reject_etag,
        )
        assert invalid_state_retry.status_code == 409
        assert invalid_state_retry.json()["detail"]["code"] == "INVALID_REVIEW_STATE"

        for case, origin in zip(
            retries,
            (OrderState.PROCESSING, OrderState.EXTRACTED, OrderState.SYNCING),
            strict=True,
        ):
            detail = await _get_detail(client, case.order_id, REVIEWER_TOKEN)
            if origin in (OrderState.PROCESSING, OrderState.EXTRACTED):
                assert detail.json()["source_snapshot"] is None
                assert detail.json()["effective_draft"] is None
            else:
                assert detail.json()["source_snapshot"] is not None
                assert detail.json()["effective_draft"] is not None
            retry_etag = _etag_from_detail(detail)
            retried = await _post_command(
                client, "retry", case.order_id, REVIEWER_TOKEN, retry_etag
            )
            assert retried.status_code == 200, retried.text
            _assert_command_response(retried, case.order_id, origin.value, None)
            assert retried.headers["etag"] != retry_etag
            retried_with_stale = await _post_command(
                client, "retry", case.order_id, REVIEWER_TOKEN, retry_etag
            )
            assert retried_with_stale.status_code == 412
            events = await _audit_items(client, case.order_id)
            retry_events = [
                item for item in events if item["event_type"].startswith("ORDER_RETRY_")
            ]
            assert [item["event_type"] for item in retry_events] == [
                "ORDER_RETRY_REQUESTED",
                "ORDER_RETRY_RESTORED",
            ]
            assert [item["description"] for item in retry_events] == [
                "Retry requested by operator.",
                "Retryable failure cleared; order restored to its recorded failure origin.",
            ]
            assert {item["actor"] for item in retry_events} == {"reviewer-test"}

        async with session_factory() as session:
            for case, origin in zip(
                retries,
                (OrderState.PROCESSING, OrderState.EXTRACTED, OrderState.SYNCING),
                strict=True,
            ):
                row = await session.get(OrderModel, case.order_id)
                assert row is not None
                assert row.state == origin.value
                assert row.failure_origin is None


async def _assert_preconditions_and_rejection_body() -> None:
    approve_case = _case(OrderState.READY_FOR_APPROVAL)
    reject_case = _case(OrderState.NEEDS_REVIEW)
    retry_case = _case(OrderState.FAILED_RETRYABLE, failure_origin=OrderState.EXTRACTED)
    cases = (approve_case, reject_case, retry_case)
    async with _command_client(cases) as (client, _, _):
        for action, case, token, body in (
            ("approve", approve_case, APPROVER_TOKEN, None),
            ("reject", reject_case, REVIEWER_TOKEN, {"reason": "valid reason"}),
            ("retry", retry_case, REVIEWER_TOKEN, None),
        ):
            current = _etag_from_detail(await _get_detail(client, case.order_id, token))
            for supplied, expected, code in (
                (None, 428, "PRECONDITION_REQUIRED"),
                ('W/"weak"', 412, "PRECONDITION_FAILED"),
                ('"' + "0" * 64 + '"', 412, "PRECONDITION_FAILED"),
            ):
                response = await _post_command(
                    client, action, case.order_id, token, supplied, body=body
                )
                assert response.status_code == expected
                assert response.json()["detail"]["code"] == code
            assert current != '"' + "0" * 64 + '"'

        reject_detail = await _get_detail(client, reject_case.order_id, REVIEWER_TOKEN)
        reject_etag = _etag_from_detail(reject_detail)
        for invalid_body in (
            {"reason": " 	\n "},
            {"reason": "é" * 501},
            {"reason": "valid", "actor": "not-authoritative"},
            {"reason": "valid", "role": "ELEVATED_APPROVER"},
        ):
            response = await client.post(
                f"/v1/review/orders/{reject_case.order_id}/reject",
                json=invalid_body,
                headers=_headers(REVIEWER_TOKEN, reject_etag),
            )
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == (
                "INVALID_REJECTION_REQUEST"
                if set(invalid_body) != {"reason"}
                else "INVALID_REJECTION_REASON"
            )
            assert "not-authoritative" not in response.text
            assert "ELEVATED_APPROVER" not in response.text

        for action in ("approve", "retry"):
            unexpected_body = await client.post(
                f"/v1/review/orders/{approve_case.order_id}/{action}",
                json={"actor": "forged"},
                headers=_headers(APPROVER_TOKEN, '"' + "a" * 64 + '"'),
            )
            assert unexpected_body.status_code == 422
            assert unexpected_body.json()["detail"]["code"] == "INVALID_COMMAND_REQUEST"
            assert "forged" not in unexpected_body.text

        missing = await client.post(
            f"/v1/review/orders/{uuid4()}/approve",
            headers=_headers(APPROVER_TOKEN, '"' + "a" * 64 + '"'),
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "ORDER_NOT_FOUND"


async def _assert_atomic_command_writes() -> None:
    cases = (
        _case(OrderState.READY_FOR_APPROVAL),
        _case(OrderState.NEEDS_REVIEW),
        _case(OrderState.FAILED_RETRYABLE, failure_origin=OrderState.SYNCING),
    )
    async with _command_client(cases) as (client, session_factory, _):
        for case, action, token, body, fail_on in zip(
            cases,
            ("approve", "reject", "retry"),
            (APPROVER_TOKEN, REVIEWER_TOKEN, REVIEWER_TOKEN),
            (None, {"reason": "atomic failure"}, None),
            (1, 1, 2),
            strict=True,
        ):
            etag = _etag_from_detail(await _get_detail(client, case.order_id, token))
            before_order, before_audits = await _read_order_and_audits(
                session_factory, case.order_id
            )
            real_insert = review_commands.insert_audit_event
            writes = 0

            async def fail_at_audit(session, event, *, fail_at=fail_on, insert=real_insert):
                nonlocal writes
                writes += 1
                if writes == fail_at:
                    raise IntegrityError("synthetic insert", {}, RuntimeError("private detail"))
                await insert(session, event)

            review_commands.insert_audit_event = fail_at_audit
            try:
                response = await _post_command(
                    client, action, case.order_id, token, etag, body=body
                )
            finally:
                review_commands.insert_audit_event = real_insert

            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "REVIEW_PERSISTENCE_CONFLICT"
            assert "private detail" not in response.text
            after_order, after_audits = await _read_order_and_audits(session_factory, case.order_id)
            assert after_order == before_order
            assert after_audits == before_audits
            assert writes == fail_on


async def _assert_preflight_generation_race(monkeypatch) -> None:
    for mutation in ("state", "audit"):
        case = _case(OrderState.READY_FOR_APPROVAL)
        async with _command_client((case,)) as (client, session_factory, _):
            etag = _etag_from_detail(await _get_detail(client, case.order_id, APPROVER_TOKEN))
            original_lock = review_commands.get_order_for_update
            injected = False

            async def mutate_then_lock(
                session, order_id, *, race=mutation, target=case, lock=original_lock
            ):
                nonlocal injected
                if not injected:
                    injected = True
                    async with session_factory() as concurrent:
                        if race == "state":
                            await concurrent.execute(
                                update(OrderModel)
                                .where(OrderModel.id == target.order_id)
                                .values(state="REJECTED")
                            )
                        else:
                            concurrent.add(
                                AuditEventModel(
                                    id=uuid4(),
                                    order_id=target.order_id,
                                    event_type="CONCURRENT_MUTATION",
                                    actor="other-operator",
                                    occurred_at=datetime(2031, 1, 1, tzinfo=UTC),
                                    description="Concurrent generation change.",
                                )
                            )
                        await concurrent.commit()
                return await lock(session, order_id)

            monkeypatch.setattr(review_commands, "get_order_for_update", mutate_then_lock)
            try:
                response = await _post_command(
                    client, "approve", case.order_id, APPROVER_TOKEN, etag
                )
            finally:
                monkeypatch.setattr(review_commands, "get_order_for_update", original_lock)
            assert injected is True
            assert response.status_code == 412
            assert response.json()["detail"]["code"] == "PRECONDITION_FAILED"
            async with session_factory() as session:
                row = await session.get(OrderModel, case.order_id)
                assert row is not None
                assert row.state == ("REJECTED" if mutation == "state" else "READY_FOR_APPROVAL")


async def _assert_retry_aba_is_closed() -> None:
    case = _case(OrderState.FAILED_RETRYABLE, failure_origin=OrderState.EXTRACTED)
    async with _command_client((case,)) as (client, session_factory, _):
        old_etag = _etag_from_detail(await _get_detail(client, case.order_id, REVIEWER_TOKEN))
        retried = await _post_command(client, "retry", case.order_id, REVIEWER_TOKEN, old_etag)
        assert retried.status_code == 200, retried.text
        async with session_factory() as session:
            await session.execute(
                update(OrderModel)
                .where(OrderModel.id == case.order_id)
                .values(state="FAILED_RETRYABLE", failure_origin="EXTRACTED")
            )
            session.add(
                AuditEventModel(
                    id=uuid4(),
                    order_id=case.order_id,
                    event_type="TEST_RESTORED_FAILURE_OCCURRENCE",
                    actor="test-setup",
                    occurred_at=datetime(2031, 1, 1, tzinfo=UTC),
                    description="Restore the same visible state with a new generation.",
                )
            )
            await session.commit()
        restored_detail = await _get_detail(client, case.order_id, REVIEWER_TOKEN)
        assert restored_detail.json()["order"]["state"] == "FAILED_RETRYABLE"
        assert restored_detail.json()["order"]["failure_origin"] == "EXTRACTED"
        assert restored_detail.headers["etag"] != old_etag
        replay = await _post_command(client, "retry", case.order_id, REVIEWER_TOKEN, old_etag)
        assert replay.status_code == 412
        assert replay.json()["detail"]["code"] == "PRECONDITION_FAILED"


async def _assert_reference_data_is_outside_etag() -> None:
    case = _case(OrderState.NEEDS_REVIEW)
    async with _command_client((case,)) as (client, _, app):
        provider = MutableReferenceProvider(Decimal("10"))
        app.state.review_runtime = replace(app.state.review_runtime, provider=provider)
        before = await _get_detail(client, case.order_id, REVIEWER_TOKEN)
        first_reference = await client.get(
            f"/v1/review/orders/{case.order_id}/reference-data",
            headers=_headers(REVIEWER_TOKEN),
        )
        provider.price = Decimal("11")
        second_reference = await client.get(
            f"/v1/review/orders/{case.order_id}/reference-data",
            headers=_headers(REVIEWER_TOKEN),
        )
        after = await _get_detail(client, case.order_id, REVIEWER_TOKEN)
        assert first_reference.status_code == second_reference.status_code == 200
        assert first_reference.json() != second_reference.json()
        assert before.headers["etag"] == after.headers["etag"]


async def _assert_transport_mapping_without_database(monkeypatch) -> None:
    order_id = uuid4()
    etag = '"' + "a" * 64 + '"'
    result = ReviewCommandResult(order_id, OrderState.APPROVED, None, etag)

    async def approved(*args, **kwargs):
        del args, kwargs
        return result

    app = create_app(_settings())
    monkeypatch.setattr(review_api, "approve_order", approved)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            success = await client.post(
                f"/v1/review/orders/{order_id}/approve",
                headers=_headers(APPROVER_TOKEN, etag),
            )
            empty_body = await client.post(
                f"/v1/review/orders/{order_id}/retry",
                json={"actor": "forged"},
                headers=_headers(REVIEWER_TOKEN, etag),
            )
            empty_approve_body = await client.post(
                f"/v1/review/orders/{order_id}/approve",
                json={"actor": "forged"},
                headers=_headers(APPROVER_TOKEN, etag),
            )

            async def missing_precondition(*args, **kwargs):
                del args, kwargs
                raise ReviewPreconditionRequiredError

            monkeypatch.setattr(review_api, "approve_order", missing_precondition)
            missing = await client.post(
                f"/v1/review/orders/{order_id}/approve",
                headers=_headers(APPROVER_TOKEN),
            )

            async def stale_precondition(*args, **kwargs):
                del args, kwargs
                raise ReviewPreconditionFailedError

            monkeypatch.setattr(review_api, "reject_order", stale_precondition)
            stale = await client.post(
                f"/v1/review/orders/{order_id}/reject",
                json={"reason": "valid reason"},
                headers=_headers(APPROVER_TOKEN, etag),
            )

            async def invalid_rejection(*args, **kwargs):
                del args, kwargs
                raise InvalidRejectionReasonError

            monkeypatch.setattr(review_api, "reject_order", invalid_rejection)
            invalid_reason = await client.post(
                f"/v1/review/orders/{order_id}/reject",
                json={"reason": "validly typed"},
                headers=_headers(APPROVER_TOKEN, etag),
            )

            async def invalid_state(*args, **kwargs):
                del args, kwargs
                raise InvalidReviewStateError

            monkeypatch.setattr(review_api, "approve_order", invalid_state)
            state_conflict = await client.post(
                f"/v1/review/orders/{order_id}/approve",
                headers=_headers(APPROVER_TOKEN, etag),
            )

            async def persistence_conflict(*args, **kwargs):
                del args, kwargs
                raise ReviewPersistenceConflictError

            monkeypatch.setattr(review_api, "retry_order", persistence_conflict)
            conflict = await client.post(
                f"/v1/review/orders/{order_id}/retry",
                headers=_headers(REVIEWER_TOKEN, etag),
            )

            async def missing_order(*args, **kwargs):
                del args, kwargs
                raise OrderNotFoundError(order_id)

            monkeypatch.setattr(review_api, "retry_order", missing_order)
            not_found = await client.post(
                f"/v1/review/orders/{order_id}/retry",
                headers=_headers(REVIEWER_TOKEN, etag),
            )

    assert success.status_code == 200
    assert success.json() == {
        "order_id": str(order_id),
        "state": "APPROVED",
        "failure_origin": None,
        "etag": etag,
    }
    assert success.headers["etag"] == etag
    assert empty_body.status_code == 422
    assert empty_body.json()["detail"]["code"] == "INVALID_COMMAND_REQUEST"
    assert "forged" not in empty_body.text
    assert empty_approve_body.status_code == 422
    assert empty_approve_body.json()["detail"]["code"] == "INVALID_COMMAND_REQUEST"
    assert "forged" not in empty_approve_body.text
    assert missing.status_code == 428
    assert missing.json()["detail"]["code"] == "PRECONDITION_REQUIRED"
    assert stale.status_code == 412
    assert stale.json()["detail"]["code"] == "PRECONDITION_FAILED"
    assert invalid_reason.status_code == 422
    assert invalid_reason.json()["detail"]["code"] == "INVALID_REJECTION_REASON"
    assert state_conflict.status_code == 409
    assert state_conflict.json()["detail"]["code"] == "INVALID_REVIEW_STATE"
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "REVIEW_PERSISTENCE_CONFLICT"
    assert not_found.status_code == 404
    assert not_found.json()["detail"]["code"] == "ORDER_NOT_FOUND"


class MutableReferenceProvider:
    def __init__(self, price: Decimal) -> None:
        self.price = price

    async def get_validation_data(self, request: BusinessDataLookupRequest) -> TrustedBusinessData:
        del request
        return TrustedBusinessData(
            customer_candidates=(TrustedCustomer("CUST-001", "Acme Industries", True),),
            products_by_line=(
                TrustedProduct("SKU-001", "Widget", True, "USD", self.price, Decimal("100")),
            ),
        )


async def _get_detail(client: httpx.AsyncClient, order_id: UUID, token: str) -> httpx.Response:
    response = await client.get(f"/v1/review/orders/{order_id}", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response


def _etag_from_detail(response: httpx.Response) -> str:
    assert response.headers["etag"] == response.json()["etag"]
    return response.headers["etag"]


async def _post_command(
    client: httpx.AsyncClient,
    action: str,
    order_id: UUID,
    token: str,
    etag: str | None,
    *,
    body: dict[str, str] | None = None,
) -> httpx.Response:
    kwargs: dict[str, object] = {"headers": _headers(token, etag)}
    if body is not None:
        kwargs["json"] = body
    return await client.post(f"/v1/review/orders/{order_id}/{action}", **kwargs)


def _assert_command_response(
    response: httpx.Response,
    order_id: UUID,
    state: str,
    failure_origin: str | None,
) -> None:
    body = response.json()
    assert set(body) == {"order_id", "state", "failure_origin", "etag"}
    assert body["order_id"] == str(order_id)
    assert body["state"] == state
    assert body["failure_origin"] == failure_origin
    assert response.headers["etag"] == body["etag"]


def _headers(token: str, etag: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if etag is not None:
        headers["If-Match"] = etag
    return headers


async def _audit_items(client: httpx.AsyncClient, order_id: UUID) -> list[dict[str, object]]:
    response = await client.get(f"/v1/orders/{order_id}/audit", headers=_headers(APPROVER_TOKEN))
    assert response.status_code == 200
    return response.json()["items"]


async def _read_order_and_audits(
    session_factory: async_sessionmaker[AsyncSession], order_id: UUID
) -> tuple[object, tuple[object, ...]]:
    async with session_factory() as session:
        persisted = await get_order(session, order_id)
        audits = await get_audit_events(session, order_id)
    assert persisted is not None
    return persisted.order, audits


def _settings() -> Settings:
    return Settings(
        review_dev_operators=(
            DevelopmentOperatorConfig(
                token=REVIEWER_TOKEN, actor=ACTORS[REVIEWER_TOKEN], role=OperatorRole.REVIEWER
            ),
            DevelopmentOperatorConfig(
                token=APPROVER_TOKEN, actor=ACTORS[APPROVER_TOKEN], role=OperatorRole.APPROVER
            ),
            DevelopmentOperatorConfig(
                token=ELEVATED_TOKEN,
                actor=ACTORS[ELEVATED_TOKEN],
                role=OperatorRole.ELEVATED_APPROVER,
            ),
        )
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

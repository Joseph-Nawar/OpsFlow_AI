"""HTTP integration tests for the Phase 2 order API."""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest

from opsflow.main import create_app
from opsflow.settings import Settings


def test_openapi_exposes_only_the_approved_business_routes() -> None:
    app = create_app(Settings())
    openapi_paths = app.openapi()["paths"]
    paths = set(openapi_paths)

    assert {
        "/v1/orders",
        "/v1/orders/{order_id}",
        "/v1/orders/{order_id}/audit",
        "/health",
        "/ready",
    } <= paths
    assert {path for path in paths if path.startswith("/v1/orders")} == {
        "/v1/orders",
        "/v1/orders/{order_id}",
        "/v1/orders/{order_id}/audit",
    }
    review_paths = {path for path in paths if path.startswith("/v1/review/")}
    assert review_paths == {
        "/v1/review/orders",
        "/v1/review/orders/{order_id}",
        "/v1/review/orders/{order_id}/reference-data",
        "/v1/review/orders/{order_id}/draft",
    }
    assert {path: set(openapi_paths[path]) for path in review_paths} == {
        "/v1/review/orders": {"get"},
        "/v1/review/orders/{order_id}": {"get"},
        "/v1/review/orders/{order_id}/reference-data": {"get"},
        "/v1/review/orders/{order_id}/draft": {"put"},
    }
    assert not any(term in path for path in paths for term in ("transition", "upload"))
    assert {path for path in paths if path.startswith("/v1/")} == {
        "/v1/orders",
        "/v1/orders/{order_id}",
        "/v1/orders/{order_id}/audit",
        *review_paths,
    }


def test_minimal_create_returns_received_order() -> None:
    response = asyncio.run(_post_order({}))

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert body["state"] == "RECEIVED"
    assert body["failure_origin"] is None
    assert body["created_at"]
    assert body["lines"] == []
    assert body["source_documents"] == []
    assert body["validation_issues"] == []


def test_populated_create_returns_generated_children_and_ordered_metadata() -> None:
    response = asyncio.run(_post_order(_populated_payload()))

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["lines"][0]["id"])
    assert UUID(body["source_documents"][0]["id"])
    assert body["lines"][0]["quantity"] == "2.50"
    assert body["source_documents"][0]["metadata"] == [
        {"key": "source", "value": "form"},
        {"key": "source", "value": "archive"},
    ]


def test_same_key_same_body_replays_original_resource_without_duplicates() -> None:
    asyncio.run(_assert_replay())


def test_same_key_different_body_returns_safe_conflict() -> None:
    asyncio.run(_assert_conflict())


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({}, 422),
        ({"Idempotency-Key": " "}, 422),
        ({"Idempotency-Key": "\t\n"}, 422),
        ({"Idempotency-Key": "x" * 129}, 422),
    ],
)
def test_invalid_idempotency_header_returns_422(
    headers: dict[str, str], expected_status: int
) -> None:
    response = asyncio.run(_post_order({}, headers=headers))

    assert response.status_code == expected_status
    assert "idempotency" not in response.text.lower() or expected_status == 422


def test_extra_request_fields_are_rejected_at_every_nested_level() -> None:
    payload = _populated_payload()
    payload["unexpected"] = True
    response = asyncio.run(_post_order(payload))
    assert response.status_code == 422

    nested = _populated_payload()
    nested["lines"][0]["unexpected"] = True
    response = asyncio.run(_post_order(nested))
    assert response.status_code == 422

    document = _populated_payload()
    document["source_documents"][0]["unexpected"] = True
    response = asyncio.run(_post_order(document))
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"id": str(uuid4())},
        {"state": "APPROVED"},
        {"failure_origin": "PROCESSING"},
        {"created_at": "2030-01-01T00:00:00Z"},
        {"validation_issues": []},
        {"audit_events": []},
        {"currency": "usd"},
        {
            "lines": [
                {"sku": "SKU-1", "quantity": "0"},
            ]
        },
        {
            "lines": [
                {"quantity": "1"},
            ]
        },
        {
            "source_documents": [
                {
                    "document_type": "FORM",
                    "name": "form",
                    "mime_type": "application/json",
                    "sha256": "not-a-sha",
                }
            ]
        },
        {
            "source_documents": [
                {
                    "document_type": "DOCX",
                    "name": "document",
                    "mime_type": "application/octet-stream",
                    "sha256": "a" * 64,
                }
            ]
        },
    ],
)
def test_invalid_shape_or_domain_structure_returns_422(payload: dict[str, object]) -> None:
    response = asyncio.run(_post_order(payload))

    assert response.status_code == 422


def test_detail_returns_full_order_and_audit_stays_separate() -> None:
    asyncio.run(_assert_detail_and_audit())


def test_missing_detail_and_audit_return_structured_404() -> None:
    asyncio.run(_assert_missing_reads())


def test_list_returns_paginated_lightweight_summaries() -> None:
    asyncio.run(_assert_list())


async def _post_order(
    payload: dict[str, object], *, headers: dict[str, str] | None = None
) -> httpx.Response:
    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            request_headers = {"Idempotency-Key": f"api-test-{uuid4()}"}
            if headers is not None:
                request_headers = headers
            return await client.post("/v1/orders", json=payload, headers=request_headers)


async def _assert_replay() -> None:
    key = f"api-replay-{uuid4()}"
    payload = _populated_payload()
    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            before = (await client.get("/v1/orders")).json()["total"]
            first = await client.post("/v1/orders", json=payload, headers={"Idempotency-Key": key})
            second = await client.post("/v1/orders", json=payload, headers={"Idempotency-Key": key})
            after = (await client.get("/v1/orders")).json()["total"]
            audit = await client.get(f"/v1/orders/{first.json()['id']}/audit")

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert after == before + 1
    assert len(audit.json()["items"]) == 1


async def _assert_conflict() -> None:
    key = f"api-conflict-{uuid4()}"
    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first = await client.post("/v1/orders", json={}, headers={"Idempotency-Key": key})
            conflict = await client.post(
                "/v1/orders",
                json={"customer_reference": "different"},
                headers={"Idempotency-Key": key},
            )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json() == {
        "detail": {
            "code": "IDEMPOTENCY_CONFLICT",
            "message": "Idempotency key was already used for a different request.",
        }
    }
    assert key not in conflict.text


async def _assert_detail_and_audit() -> None:
    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/v1/orders", json=_populated_payload(), headers={"Idempotency-Key": str(uuid4())}
            )
            order_id = created.json()["id"]
            detail = await client.get(f"/v1/orders/{order_id}")
            audit = await client.get(f"/v1/orders/{order_id}/audit")

    assert detail.status_code == 200
    assert set(detail.json()) == {
        "id",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "state",
        "failure_origin",
        "created_at",
        "lines",
        "source_documents",
        "validation_issues",
    }
    assert "audit_events" not in detail.json()
    assert audit.status_code == 200
    assert audit.json()["items"][0]["event_type"] == "ORDER_RECEIVED"


async def _assert_missing_reads() -> None:
    missing = uuid4()
    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            detail = await client.get(f"/v1/orders/{missing}")
            audit = await client.get(f"/v1/orders/{missing}/audit")

    expected = {"detail": {"code": "ORDER_NOT_FOUND", "message": "Order was not found."}}
    assert detail.status_code == 404
    assert detail.json() == expected
    assert audit.status_code == 404
    assert audit.json() == expected


async def _assert_list() -> None:
    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created_ids = []
            for index in range(2):
                response = await client.post(
                    "/v1/orders",
                    json={"po_number": f"PO-LIST-{index}"},
                    headers={"Idempotency-Key": f"api-list-{uuid4()}"},
                )
                assert response.status_code == 201
                created_ids.append(response.json()["id"])
            page = await client.get("/v1/orders?limit=1&offset=1")
            invalid_limit = await client.get("/v1/orders?limit=0")
            invalid_offset = await client.get("/v1/orders?offset=-1")

    assert page.status_code == 200
    body = page.json()
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert body["total"] >= 2
    assert len(body["items"]) == 1
    assert set(body["items"][0]) == {
        "id",
        "customer_reference",
        "po_number",
        "order_date",
        "requested_delivery_date",
        "currency",
        "state",
        "created_at",
    }
    assert body["items"][0]["id"] in created_ids
    assert invalid_limit.status_code == 422
    assert invalid_offset.status_code == 422


def _populated_payload() -> dict[str, object]:
    return {
        "customer_reference": "CUST-API",
        "po_number": "PO-API",
        "order_date": "2030-01-02",
        "requested_delivery_date": "2030-01-10",
        "currency": "USD",
        "lines": [
            {
                "sku": "SKU-API",
                "description": "API fixture",
                "quantity": "2.50",
                "submitted_price": "10.00",
                "trusted_catalogue_price": "11.00",
            }
        ],
        "source_documents": [
            {
                "document_type": "FORM",
                "name": "api-form",
                "mime_type": "application/json",
                "sha256": "a" * 64,
                "metadata": [
                    {"key": "source", "value": "form"},
                    {"key": "source", "value": "archive"},
                ],
            }
        ],
    }

"""Fail-closed bearer transport behavior for Phase 6 commands."""

import asyncio
from uuid import uuid4

import httpx

from opsflow.main import create_app
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings

REVIEWER_TOKEN = "synthetic-command-reviewer-credential"
APPROVER_TOKEN = "synthetic-command-approver-credential"
ELEVATED_TOKEN = "synthetic-command-elevated-credential"


def test_commands_require_known_server_resolved_bearer_without_database_access() -> None:
    asyncio.run(_assert_authentication_contract())


async def _assert_authentication_contract() -> None:
    app = create_app(
        Settings(
            review_dev_operators=(
                DevelopmentOperatorConfig(
                    token=REVIEWER_TOKEN, actor="reviewer-test", role=OperatorRole.REVIEWER
                ),
                DevelopmentOperatorConfig(
                    token=APPROVER_TOKEN, actor="approver-test", role=OperatorRole.APPROVER
                ),
                DevelopmentOperatorConfig(
                    token=ELEVATED_TOKEN,
                    actor="elevated-test",
                    role=OperatorRole.ELEVATED_APPROVER,
                ),
            )
        )
    )
    order_id = uuid4()
    routes = (
        (f"/v1/review/orders/{order_id}/approve", None),
        (f"/v1/review/orders/{order_id}/reject", {"reason": "test reason"}),
        (f"/v1/review/orders/{order_id}/retry", None),
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = []
            for path, body in routes:
                if body:
                    unauthenticated.append(await client.post(path, json=body))
                else:
                    unauthenticated.append(await client.post(path))
                unauthenticated.append(
                    await client.post(
                        path,
                        json=body,
                        headers={"Authorization": "Bearer unknown-command-credential"},
                    )
                    if body
                    else await client.post(
                        path,
                        headers={"Authorization": "Bearer unknown-command-credential"},
                    )
                )

            reviewer_claims = await client.post(
                routes[0][0],
                headers={
                    "Authorization": f"Bearer {REVIEWER_TOKEN}",
                    "If-Match": '"' + "a" * 64 + '"',
                    "X-Operator-Actor": "forged-elevated",
                    "X-Operator-Role": "ELEVATED_APPROVER",
                },
            )
            approver_claims = await client.post(
                routes[2][0],
                headers={
                    "Authorization": f"Bearer {APPROVER_TOKEN}",
                    "If-Match": '"' + "a" * 64 + '"',
                    "X-Operator-Actor": "forged-reviewer",
                    "X-Operator-Role": "REVIEWER",
                },
            )
            reject_claims = await client.post(
                routes[1][0],
                json={"reason": "test reason", "actor": "forged", "role": "APPROVER"},
                headers={
                    "Authorization": f"Bearer {REVIEWER_TOKEN}",
                    "If-Match": '"' + "a" * 64 + '"',
                },
            )

    for response in unauthenticated:
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "UNAUTHENTICATED"
        assert REVIEWER_TOKEN not in response.text
        assert APPROVER_TOKEN not in response.text
        assert ELEVATED_TOKEN not in response.text
    assert reviewer_claims.status_code == 403
    assert reviewer_claims.json()["detail"]["code"] == "FORBIDDEN"
    assert approver_claims.status_code == 403
    assert approver_claims.json()["detail"]["code"] == "FORBIDDEN"
    assert reject_claims.status_code == 422
    assert reject_claims.json()["detail"]["code"] == "INVALID_REJECTION_REQUEST"
    assert "forged" not in reject_claims.text

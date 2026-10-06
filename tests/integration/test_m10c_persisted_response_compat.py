"""M10C regression coverage for unconstrained persisted response values."""

import asyncio
from uuid import uuid4

import httpx
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from opsflow.application.orders import (
    CreateOrderInput,
    CreateSourceDocumentInput,
    create_order,
)
from opsflow.domain import SourceDocumentType
from opsflow.main import create_app
from opsflow.persistence.models import (
    AuditEventModel,
    OrderCreationIdempotencyModel,
    OrderModel,
    SourceDocumentModel,
)
from opsflow.review import OperatorRole
from opsflow.settings import DevelopmentOperatorConfig, Settings

VIEW_TOKEN = "m10c-persisted-response-view-token"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        review_dev_operators=(
            DevelopmentOperatorConfig(
                token=VIEW_TOKEN,
                actor="m10c-persisted-response-viewer",
                role=OperatorRole.REVIEWER,
            ),
        ),
    )


def test_historical_over_limit_metadata_is_returned_unchanged() -> None:
    asyncio.run(_assert_historical_metadata_round_trip())


async def _assert_historical_metadata_round_trip() -> None:
    engine = create_async_engine(Settings().database_url)
    order_id = None
    idempotency_key = f"m10c-legacy-metadata-{uuid4()}"
    over_limit_key = "k" * 129
    over_limit_value = "v" * 513
    try:
        async with AsyncSession(engine) as session:
            persisted = await create_order(
                session,
                CreateOrderInput(
                    source_documents=(
                        CreateSourceDocumentInput(
                            document_type=SourceDocumentType.FORM,
                            name="legacy-form",
                            mime_type="application/json",
                            sha256="a" * 64,
                            metadata=((over_limit_key, over_limit_value),),
                        ),
                    ),
                ),
                idempotency_key,
            )
            order_id = persisted.order.id

        app = create_app(_settings())
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get(
                    f"/v1/orders/{order_id}",
                    headers={"Authorization": f"Bearer {VIEW_TOKEN}"},
                )

        assert response.status_code == 200
        assert response.json()["source_documents"][0]["metadata"] == [
            {"key": over_limit_key, "value": over_limit_value}
        ]
    finally:
        if order_id is not None:
            async with AsyncSession(engine) as session:
                await session.execute(
                    delete(OrderCreationIdempotencyModel).where(
                        OrderCreationIdempotencyModel.idempotency_key == idempotency_key
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(AuditEventModel.order_id == order_id)
                )
                await session.execute(
                    delete(SourceDocumentModel).where(SourceDocumentModel.order_id == order_id)
                )
                await session.execute(delete(OrderModel).where(OrderModel.id == order_id))
                await session.commit()
        await engine.dispose()

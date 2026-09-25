"""Tests for the injectable Phase 7 provider runtime composition."""

import asyncio
import json
from dataclasses import FrozenInstanceError, asdict, fields

import pytest

from opsflow.extraction.errors import ProviderError
from opsflow.extraction.extractor import parse_provider_response
from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.gemini import GeminiProvider
from opsflow.extraction.models import ProviderExtractionResponse
from opsflow.extraction.provider import StructuredGenerationRequest, StructuredGenerationResult
from opsflow.orchestration.composition import build_orchestration_runtime
from opsflow.review.composition import build_demo_review_runtime
from opsflow.settings import Settings

SYNTHETIC_PAYLOAD = {
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


def _request() -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        prompt_version="phase4-extraction-v1",
        system_instruction="extract only",
        user_content="synthetic source",
        response_schema={"type": "object"},
    )


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_orchestration_runtime_is_frozen_and_slotted() -> None:
    runtime = build_orchestration_runtime(_settings())

    assert not hasattr(runtime, "__dict__")
    assert [field.name for field in fields(runtime)] == [
        "extraction_provider_factory",
        "business_data_provider",
        "policy",
        "date_provider",
        "review_base_url",
    ]
    assert runtime.review_base_url == "http://localhost:5173"
    with pytest.raises(FrozenInstanceError):
        runtime.policy = runtime.policy  # type: ignore[misc]


def test_default_runtime_uses_demo_review_runtime_and_fresh_fake_providers() -> None:
    runtime = build_orchestration_runtime(_settings())
    first = runtime.extraction_provider_factory()
    second = runtime.extraction_provider_factory()

    assert isinstance(first, FakeProvider)
    assert isinstance(second, FakeProvider)
    assert first is not second
    demo = build_demo_review_runtime()
    assert type(runtime.business_data_provider) is type(demo.provider)
    assert runtime.policy == demo.policy
    assert type(runtime.date_provider) is type(demo.date_provider)


def test_fresh_fake_provider_factory_isolates_destructive_queues() -> None:
    runtime = build_orchestration_runtime(_settings())
    first = runtime.extraction_provider_factory()
    second = runtime.extraction_provider_factory()

    assert asyncio.run(first.generate_structured(_request())).payload == SYNTHETIC_PAYLOAD
    assert asyncio.run(second.generate_structured(_request())).payload == SYNTHETIC_PAYLOAD
    with pytest.raises(ProviderError, match="script exhausted"):
        asyncio.run(first.generate_structured(_request()))


def test_default_fake_payload_is_strictly_valid_and_deterministic() -> None:
    runtime = build_orchestration_runtime(_settings())
    result = asyncio.run(runtime.extraction_provider_factory().generate_structured(_request()))
    response = parse_provider_response(result.payload)

    assert isinstance(response, ProviderExtractionResponse)
    assert response.customer_reference == "CUST-001"
    assert response.po_number == "PO-SYNTHETIC"
    assert response.currency == "USD"
    assert len(response.lines) == 1
    assert response.lines[0].sku == "SKU-001"
    assert response.lines[0].quantity == "1"
    assert response.lines[0].submitted_price == "10"
    assert response.order_date == "2025-01-01"
    assert response.requested_delivery_date == "2025-01-08"
    assert response.evidence == []


def test_explicit_extraction_factory_is_retained_exactly() -> None:
    provider = FakeProvider((StructuredGenerationResult(payload=SYNTHETIC_PAYLOAD),))

    def factory() -> FakeProvider:
        return provider

    runtime = build_orchestration_runtime(
        _settings(
            gemini_api_key="configured-test-value",
            gemini_model="gemini-test-model",
            gemini_timeout_seconds=12.5,
        ),
        extraction_provider_factory=factory,
    )

    assert runtime.extraction_provider_factory is factory
    assert runtime.extraction_provider_factory() is provider


def test_explicit_review_runtime_is_retained_exactly() -> None:
    review_runtime = build_demo_review_runtime()

    runtime = build_orchestration_runtime(_settings(), review_runtime=review_runtime)

    assert runtime.business_data_provider is review_runtime.provider
    assert runtime.policy is review_runtime.policy
    assert runtime.date_provider is review_runtime.date_provider


def test_complete_gemini_settings_create_fresh_configured_providers() -> None:
    runtime = build_orchestration_runtime(
        _settings(
            gemini_api_key="configured-test-value",
            gemini_model="gemini-test-model",
            gemini_timeout_seconds=12.5,
        )
    )

    first = runtime.extraction_provider_factory()
    second = runtime.extraction_provider_factory()

    assert isinstance(first, GeminiProvider)
    assert isinstance(second, GeminiProvider)
    assert first is not second
    assert first._config.model == "gemini-test-model"
    assert first._config.timeout_seconds == 12.5
    assert "configured-test-value" not in repr(runtime)
    assert "configured-test-value" not in repr(first._config)


@pytest.mark.parametrize(
    "overrides",
    [
        {"gemini_model": None, "gemini_timeout_seconds": 12.5},
        {"gemini_model": "gemini-test-model", "gemini_timeout_seconds": None},
    ],
)
def test_incomplete_gemini_settings_fail_without_echoing_key(
    overrides: dict[str, object],
) -> None:
    settings = _settings(gemini_api_key="configured-test-value", **overrides)

    with pytest.raises(ValueError) as raised:
        build_orchestration_runtime(settings)

    assert "configured-test-value" not in str(raised.value)


def test_composition_repr_and_serialized_fields_do_not_contain_provider_data() -> None:
    runtime = build_orchestration_runtime(_settings())

    serialized = json.dumps(asdict(runtime), default=repr)
    assert "PO-SYNTHETIC" not in repr(runtime)
    assert "PO-SYNTHETIC" not in serialized

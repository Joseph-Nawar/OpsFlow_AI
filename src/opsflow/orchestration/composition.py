"""Small, explicit provider composition for Phase 7 orchestration."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass

from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.gemini import GeminiConfig, GeminiProvider
from opsflow.extraction.provider import LLMProvider, StructuredGenerationResult
from opsflow.review.composition import (
    ReviewDateProvider,
    ReviewRuntime,
    build_demo_review_runtime,
)
from opsflow.settings import Settings
from opsflow.validation.business_data import BusinessDataProvider
from opsflow.validation.policy import ValidationPolicy

_SYNTHETIC_PROVIDER_PAYLOAD = {
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
class OrchestrationRuntime:
    """Explicit provider and deterministic validation dependencies for intake."""

    extraction_provider_factory: Callable[[], LLMProvider]
    business_data_provider: BusinessDataProvider
    policy: ValidationPolicy
    date_provider: ReviewDateProvider
    review_base_url: str


def _build_fake_provider() -> LLMProvider:
    return FakeProvider(
        (
            StructuredGenerationResult(
                payload=deepcopy(_SYNTHETIC_PROVIDER_PAYLOAD),
            ),
        )
    )


def build_orchestration_runtime(
    settings: Settings,
    *,
    extraction_provider_factory: Callable[[], LLMProvider] | None = None,
    review_runtime: ReviewRuntime | None = None,
) -> OrchestrationRuntime:
    """Compose fresh extraction providers with Phase 6 review dependencies."""

    selected_review_runtime = review_runtime or build_demo_review_runtime()
    api_key = settings.gemini_api_key
    model = settings.gemini_model
    timeout_seconds = settings.gemini_timeout_seconds
    if extraction_provider_factory is not None:
        selected_extraction_factory = extraction_provider_factory
    elif api_key is None or not api_key.strip():
        selected_extraction_factory = _build_fake_provider
    else:
        if model is None or timeout_seconds is None:
            raise ValueError("Gemini configuration is incomplete")

        def selected_extraction_factory() -> LLMProvider:
            return GeminiProvider(
                GeminiConfig(
                    api_key=api_key,
                    model=model,
                    timeout_seconds=timeout_seconds,
                )
            )

    return OrchestrationRuntime(
        extraction_provider_factory=selected_extraction_factory,
        business_data_provider=selected_review_runtime.provider,
        policy=selected_review_runtime.policy,
        date_provider=selected_review_runtime.date_provider,
        review_base_url=settings.review_base_url,
    )


__all__ = ["OrchestrationRuntime", "build_orchestration_runtime"]

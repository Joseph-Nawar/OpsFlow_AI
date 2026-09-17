"""Phase 4 structured extraction contracts."""

from opsflow.extraction.errors import (
    ExtractionError,
    ExtractionResponseError,
    ProviderError,
    ProviderTimeoutError,
)
from opsflow.extraction.fake import FakeOutcome, FakeProvider
from opsflow.extraction.models import (
    Evidence,
    ExtractedLine,
    ExtractionDraft,
    ProviderEvidenceResponse,
    ProviderExtractionResponse,
    ProviderLineResponse,
    build_provider_response_schema,
)
from opsflow.extraction.provider import (
    LLMProvider,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)

__all__ = [
    "Evidence",
    "ExtractedLine",
    "ExtractionDraft",
    "ExtractionError",
    "ExtractionResponseError",
    "FakeOutcome",
    "FakeProvider",
    "LLMProvider",
    "ProviderError",
    "ProviderEvidenceResponse",
    "ProviderExtractionResponse",
    "ProviderLineResponse",
    "StructuredGenerationRequest",
    "StructuredGenerationResult",
    "ProviderTimeoutError",
    "build_provider_response_schema",
]

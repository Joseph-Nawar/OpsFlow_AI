"""Phase 4 structured extraction contracts."""

from opsflow.extraction.errors import (
    ExtractionError,
    ExtractionResponseError,
    ProviderError,
    ProviderTimeoutError,
)
from opsflow.extraction.extractor import (
    convert_provider_response,
    parse_decimal_text,
    parse_iso_date,
    parse_provider_response,
    validate_evidence,
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
from opsflow.extraction.prompt import (
    PROMPT_VERSION,
    RenderedSource,
    SourceSegment,
    build_extraction_request,
    render_canonical_document,
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
    "PROMPT_VERSION",
    "ProviderError",
    "ProviderEvidenceResponse",
    "ProviderExtractionResponse",
    "ProviderLineResponse",
    "RenderedSource",
    "SourceSegment",
    "StructuredGenerationRequest",
    "StructuredGenerationResult",
    "ProviderTimeoutError",
    "build_extraction_request",
    "build_provider_response_schema",
    "convert_provider_response",
    "parse_decimal_text",
    "parse_iso_date",
    "parse_provider_response",
    "render_canonical_document",
    "validate_evidence",
]

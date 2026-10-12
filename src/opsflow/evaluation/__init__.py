"""Evaluation contracts and pure scoring primitives for Phase 11."""

from .models import (
    BenchmarkValidationContext,
    CaseActual,
    CaseCategory,
    CaseResult,
    CaseResultStatus,
    EvaluationMode,
    EvaluationRunResult,
    ExtractionQuality,
    MetricsBundle,
    ProviderSummary,
    ReleaseGateSummary,
)
from .scoring import (
    CanonicalExtractionProjection,
    PositionedExtractionScore,
    ValidationOutcomeScore,
    canonicalize_value,
    evaluate_release_gates,
    project_extraction,
    score_extraction_quality,
    score_positioned_extraction,
    score_validation_outcome,
)

__all__ = [
    "CaseCategory",
    "CaseActual",
    "CaseResult",
    "CaseResultStatus",
    "BenchmarkValidationContext",
    "CanonicalExtractionProjection",
    "EvaluationMode",
    "EvaluationRunResult",
    "ExtractionQuality",
    "MetricsBundle",
    "PositionedExtractionScore",
    "ProviderSummary",
    "ReleaseGateSummary",
    "ValidationOutcomeScore",
    "canonicalize_value",
    "evaluate_release_gates",
    "project_extraction",
    "score_extraction_quality",
    "score_positioned_extraction",
    "score_validation_outcome",
]

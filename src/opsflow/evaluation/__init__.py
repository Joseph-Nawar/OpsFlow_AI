"""Evaluation contracts and pure scoring primitives for Phase 11."""

from .models import (
    CaseCategory,
    EvaluationMode,
    EvaluationRunResult,
    ExtractionQuality,
)
from .scoring import (
    CanonicalExtractionProjection,
    PositionedExtractionScore,
    ValidationOutcomeScore,
    canonicalize_value,
    project_extraction,
    score_extraction_quality,
    score_positioned_extraction,
    score_validation_outcome,
)

__all__ = [
    "CaseCategory",
    "CanonicalExtractionProjection",
    "EvaluationMode",
    "EvaluationRunResult",
    "ExtractionQuality",
    "PositionedExtractionScore",
    "ValidationOutcomeScore",
    "canonicalize_value",
    "project_extraction",
    "score_extraction_quality",
    "score_positioned_extraction",
    "score_validation_outcome",
]

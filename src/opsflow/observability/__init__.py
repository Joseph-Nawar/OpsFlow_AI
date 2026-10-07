"""Small process-local observability primitives for M10D."""

from .runtime import Observability, current_observability

__all__ = ["Observability", "current_observability"]

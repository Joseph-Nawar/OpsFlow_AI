"""Run-scoped timing and authoritative provider usage accounting."""

from __future__ import annotations

import importlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import wraps
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast
from uuid import UUID

from opsflow.extraction.provider import (
    LLMProvider,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)

TimingStage = Literal[
    "parse_ms",
    "deterministic_validation_ms",
    "provider_free_intake_ms",
    "live_gemini_call_ms",
    "provider_free_replay_intake_ms",
    "provider_free_recovery_intake_ms",
]

_TIMING_STAGES: tuple[TimingStage, ...] = (
    "parse_ms",
    "deterministic_validation_ms",
    "provider_free_intake_ms",
    "live_gemini_call_ms",
    "provider_free_replay_intake_ms",
    "provider_free_recovery_intake_ms",
)


@dataclass(frozen=True, slots=True)
class TimingSummary:
    """Nearest-rank summary of one explicitly measured stage."""

    stage: TimingStage
    sample_count: int
    minimum_ms: Decimal | None
    maximum_ms: Decimal | None
    sum_ms: Decimal | None
    p50_ms: Decimal | None
    p95_ms: Decimal | None
    percentile_method: str = "nearest_rank_no_interpolation"


class EvaluationMeasurements:
    """Collect only durations wrapped by an explicit evaluation stage scope."""

    def __init__(self, monotonic_ns: Callable[[], int] | None = None) -> None:
        if monotonic_ns is None:
            from time import monotonic_ns as clock

            monotonic_ns = clock
        self._monotonic_ns = monotonic_ns
        self._samples: dict[TimingStage, list[Decimal]] = {stage: [] for stage in _TIMING_STAGES}
        self._case_samples: dict[tuple[str, TimingStage], list[Decimal]] = defaultdict(list)
        self._provider_calls: list[ProviderCallRecord] = []

    @contextmanager
    def measure(
        self,
        stage: TimingStage,
        *,
        case_id: str | None = None,
        record_on_exception: bool = True,
    ) -> Iterator[None]:
        """Record monotonic elapsed time for the named application boundary."""

        if stage not in self._samples:
            raise ValueError("unsupported evaluation timing stage")
        started = self._monotonic_ns()
        try:
            yield
        except BaseException as error:
            elapsed_ns = self._monotonic_ns() - started
            if elapsed_ns < 0:
                raise RuntimeError("monotonic clock moved backwards") from error
            if record_on_exception:
                self.record(stage, Decimal(elapsed_ns) / Decimal(1_000_000), case_id=case_id)
            raise
        else:
            elapsed_ns = self._monotonic_ns() - started
            if elapsed_ns < 0:
                raise RuntimeError("monotonic clock moved backwards")
            self.record(stage, Decimal(elapsed_ns) / Decimal(1_000_000), case_id=case_id)

    def record(
        self, stage: TimingStage, duration_ms: Decimal, *, case_id: str | None = None
    ) -> None:
        """Add one duration measured at a precisely defined evaluation boundary."""

        if stage not in self._samples:
            raise ValueError("unsupported evaluation timing stage")
        if not isinstance(duration_ms, Decimal) or not duration_ms.is_finite() or duration_ms < 0:
            raise ValueError("duration_ms must be a finite non-negative Decimal")
        self._samples[stage].append(duration_ms)
        if case_id is not None:
            self._case_samples[(case_id, stage)].append(duration_ms)

    def summary(self, stage: TimingStage, *, case_id: str | None = None) -> TimingSummary:
        """Return count, extrema, sum, and nearest-rank p50/p95 for a stage."""

        if stage not in self._samples:
            raise ValueError("unsupported evaluation timing stage")
        values = sorted(
            self._samples[stage]
            if case_id is None
            else self._case_samples.get((case_id, stage), ())
        )
        if not values:
            return TimingSummary(
                stage=stage,
                sample_count=0,
                minimum_ms=None,
                maximum_ms=None,
                sum_ms=None,
                p50_ms=None,
                p95_ms=None,
            )

        def nearest_rank(percentile: int) -> Decimal:
            rank = max(1, (percentile * len(values) + 99) // 100)
            return values[rank - 1]

        return TimingSummary(
            stage=stage,
            sample_count=len(values),
            minimum_ms=values[0],
            maximum_ms=values[-1],
            sum_ms=sum(values, Decimal(0)),
            p50_ms=nearest_rank(50),
            p95_ms=nearest_rank(95),
        )

    def record_provider_call(self, record: ProviderCallRecord) -> None:
        self._provider_calls.append(record)
        self.record("live_gemini_call_ms", record.duration_ms, case_id=record.initial_case_id)

    @property
    def provider_calls(self) -> tuple[ProviderCallRecord, ...]:
        return tuple(self._provider_calls)

    def bind_case_order(self, case_id: str, order_id: UUID | None) -> None:
        """Bind attempts to the durable order returned by the real intake seam."""

        self._provider_calls = [
            ProviderCallRecord(
                initial_case_id=record.initial_case_id,
                initial_order_id=order_id,
                attempt_index=record.attempt_index,
                duration_ms=record.duration_ms,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                total_tokens=record.total_tokens,
                model=record.model,
                pricing_snapshot_id=record.pricing_snapshot_id,
                failed=record.failed,
            )
            if record.initial_case_id == case_id and record.initial_order_id is None
            else record
            for record in self._provider_calls
        ]


@contextmanager
def measure_application_stages(
    measurements: EvaluationMeasurements, *, case_id: str
) -> Iterator[None]:
    """Observe the real orchestration parse and Phase 5 validation calls.

    The evaluation runner executes corpus cases sequentially, so these temporary
    module-boundary wrappers are installed for one invocation and restored even
    when application execution raises.
    """

    orchestration_application = cast(
        Any, importlib.import_module("opsflow.application.orchestration")
    )
    validation_application = cast(Any, importlib.import_module("opsflow.application.validation"))
    validation_engine = validation_application.validation_engine
    original_process_document = orchestration_application.process_document
    original_validate = validation_engine.validate

    @wraps(original_process_document)
    def measured_process_document(*args: Any, **kwargs: Any) -> Any:
        with measurements.measure("parse_ms", case_id=case_id, record_on_exception=False):
            return original_process_document(*args, **kwargs)

    @wraps(original_validate)
    def measured_validation(*args: Any, **kwargs: Any) -> Any:
        with measurements.measure("deterministic_validation_ms", case_id=case_id):
            return original_validate(*args, **kwargs)

    orchestration_application.process_document = measured_process_document
    validation_engine.validate = measured_validation
    try:
        yield
    finally:
        orchestration_application.process_document = original_process_document
        validation_engine.validate = original_validate


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    """Immutable input/output token rates captured for one exact model tier."""

    snapshot_id: str
    model: str
    token_unit: int
    input_rate_usd: Decimal
    output_rate_usd: Decimal
    provider: str = "google"
    pricing_tier: str = "standard_paid"
    currency: str = "USD"
    input_modality: str = "text"
    output_modality: str = "text"
    effective_from: str = ""
    effective_through: str = ""
    retrieved_on: str = ""
    source_url: str = ""

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.model.strip():
            raise ValueError("pricing snapshot identity and model must be nonblank")
        if type(self.token_unit) is not int or self.token_unit <= 0:
            raise ValueError("pricing token_unit must be a positive integer")
        for rate in (self.input_rate_usd, self.output_rate_usd):
            if not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0:
                raise ValueError("pricing rates must be finite non-negative Decimals")
        if (
            self.provider != "google"
            or self.pricing_tier != "standard_paid"
            or self.currency != "USD"
            or self.input_modality != "text"
            or self.output_modality != "text"
        ):
            raise ValueError("pricing snapshot does not match the supported Gemini text tier")
        for date_value in (self.effective_from, self.effective_through, self.retrieved_on):
            if date_value:
                try:
                    date.fromisoformat(date_value)
                except (TypeError, ValueError) as error:
                    raise ValueError("pricing snapshot dates must use ISO format") from error
        if (
            self.effective_from
            and self.effective_through
            and (
                date.fromisoformat(self.effective_from) > date.fromisoformat(self.effective_through)
            )
        ):
            raise ValueError("pricing snapshot effective dates are reversed")
        if self.source_url and not self.source_url.startswith("https://ai.google.dev/"):
            raise ValueError("pricing source must be an authoritative Google AI page")


def load_pricing_snapshot(path: str | Path) -> PricingSnapshot:
    """Load one strict, immutable JSON pricing record without floating point."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"), parse_float=Decimal)
    expected_keys = {
        "schema_version",
        "snapshot_id",
        "provider",
        "model",
        "pricing_tier",
        "effective_from",
        "effective_through",
        "retrieved_on",
        "currency",
        "input_modality",
        "output_modality",
        "token_unit",
        "input_rate_usd",
        "output_rate_usd",
        "source_url",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("pricing snapshot schema is invalid")
    if payload["schema_version"] != "opsflow-evaluation-pricing/v1":
        raise ValueError("unsupported pricing snapshot schema version")
    if type(payload["token_unit"]) is not int:
        raise ValueError("pricing token_unit must be an integer")
    if isinstance(payload["input_rate_usd"], bool) or not isinstance(
        payload["input_rate_usd"], (str, Decimal)
    ):
        raise ValueError("pricing input rate must be a decimal string")
    if isinstance(payload["output_rate_usd"], bool) or not isinstance(
        payload["output_rate_usd"], (str, Decimal)
    ):
        raise ValueError("pricing output rate must be a decimal string")
    return PricingSnapshot(
        snapshot_id=payload["snapshot_id"],
        model=payload["model"],
        token_unit=payload["token_unit"],
        input_rate_usd=Decimal(payload["input_rate_usd"]),
        output_rate_usd=Decimal(payload["output_rate_usd"]),
        provider=payload["provider"],
        pricing_tier=payload["pricing_tier"],
        currency=payload["currency"],
        input_modality=payload["input_modality"],
        output_modality=payload["output_modality"],
        effective_from=payload["effective_from"],
        effective_through=payload["effective_through"],
        retrieved_on=payload["retrieved_on"],
        source_url=payload["source_url"],
    )


@dataclass(frozen=True, slots=True)
class ProviderCallRecord:
    """One real provider attempt, attributed to its initial case and order."""

    initial_case_id: str
    initial_order_id: UUID | None
    attempt_index: int
    duration_ms: Decimal
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model: str | None
    pricing_snapshot_id: str | None
    failed: bool = False

    def __post_init__(self) -> None:
        if not self.initial_case_id.strip():
            raise ValueError("provider call requires an initial case identity")
        if type(self.attempt_index) is not int or self.attempt_index < 1:
            raise ValueError("attempt_index must be a positive integer")
        if not isinstance(self.duration_ms, Decimal) or (
            not self.duration_ms.is_finite() or self.duration_ms < 0
        ):
            raise ValueError("provider duration must be a finite non-negative Decimal")
        for value in (self.input_tokens, self.output_tokens, self.total_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("provider token counts must be non-negative integers or None")


@dataclass(frozen=True, slots=True)
class OrderUsageSummary:
    """Token and complete-cost evidence grouped by one initial corpus case."""

    case_id: str
    order_id: UUID | None
    call_count: int
    estimated_model_cost_usd: Decimal | None
    usage_complete: bool


@dataclass(frozen=True, slots=True)
class ProviderUsageSummary:
    """Run aggregate retaining token completeness and attribution counters."""

    initial_order_count: int
    gemini_call_count: int
    failed_call_count: int
    gemini_called_order_count: int
    zero_call_order_count: int
    complete_usage_order_count: int
    incomplete_usage_order_count: int
    incomplete_usage_call_count: int
    missing_call_attribution_count: int
    input_tokens_sum: int | None
    available_input_token_count: int
    missing_input_token_count: int
    output_tokens_sum: int | None
    available_output_token_count: int
    missing_output_token_count: int
    total_tokens_sum: int | None
    available_total_token_count: int
    missing_total_token_count: int
    inconsistent_reported_total_count: int
    missing_pricing_snapshot_count: int
    estimated_model_cost_per_initial_order: Decimal | None
    orders: Mapping[str, OrderUsageSummary]


class MeasuredGeminiProvider:
    """Observe calls around the existing Gemini provider without replacing it."""

    def __init__(
        self,
        provider: LLMProvider,
        measurements: EvaluationMeasurements,
        *,
        case_id: str,
        model: str,
        pricing_snapshot_id: str | None,
        attempt_counter: list[int],
    ) -> None:
        self._provider = provider
        self._measurements = measurements
        self._case_id = case_id
        self._model = model
        self._pricing_snapshot_id = pricing_snapshot_id
        self._attempt_counter = attempt_counter

    async def generate_structured(
        self, request: StructuredGenerationRequest
    ) -> StructuredGenerationResult:
        self._attempt_counter[0] += 1
        attempt_index = self._attempt_counter[0]
        started = self._measurements._monotonic_ns()
        try:
            result = await self._provider.generate_structured(request)
        except BaseException:
            duration = Decimal(self._measurements._monotonic_ns() - started) / Decimal(1_000_000)
            self._measurements.record_provider_call(
                ProviderCallRecord(
                    initial_case_id=self._case_id,
                    initial_order_id=None,
                    attempt_index=attempt_index,
                    duration_ms=duration,
                    input_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    model=self._model,
                    pricing_snapshot_id=self._pricing_snapshot_id,
                    failed=True,
                )
            )
            raise
        duration = Decimal(self._measurements._monotonic_ns() - started) / Decimal(1_000_000)
        self._measurements.record_provider_call(
            ProviderCallRecord(
                initial_case_id=self._case_id,
                initial_order_id=None,
                attempt_index=attempt_index,
                duration_ms=duration,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens,
                model=self._model,
                pricing_snapshot_id=self._pricing_snapshot_id,
            )
        )
        return result


@dataclass(slots=True)
class MeasuredGeminiProviderFactory:
    """Explicit live-only factory that accepts only the real Gemini adapter."""

    provider_factory: Callable[[], LLMProvider]
    measurements: EvaluationMeasurements
    case_id: str
    model: str
    pricing_snapshot_id: str | None
    _attempt_counter: list[int] | None = None

    def __post_init__(self) -> None:
        self._attempt_counter = [0]

    def __call__(self) -> LLMProvider:
        from opsflow.extraction.gemini import GeminiProvider

        provider = self.provider_factory()
        if not isinstance(provider, GeminiProvider):
            raise TypeError("live evaluation requires the configured GeminiProvider")
        return MeasuredGeminiProvider(
            provider,
            self.measurements,
            case_id=self.case_id,
            model=self.model,
            pricing_snapshot_id=self.pricing_snapshot_id,
            attempt_counter=self._attempt_counter or [0],
        )


def measured_gemini_provider_factory(
    provider_factory: Callable[[], LLMProvider],
    measurements: EvaluationMeasurements,
    *,
    case_id: str,
    model: str,
    pricing_snapshot_id: str | None,
) -> MeasuredGeminiProviderFactory:
    """Wrap the repository Gemini provider and reject any other provider type."""

    return MeasuredGeminiProviderFactory(
        provider_factory=provider_factory,
        measurements=measurements,
        case_id=case_id,
        model=model,
        pricing_snapshot_id=pricing_snapshot_id,
    )


def _sum_available(values: Sequence[int | None]) -> tuple[int | None, int, int]:
    available = tuple(value for value in values if value is not None)
    return (
        sum(available) if available else None,
        len(available),
        len(values) - len(available),
    )


def aggregate_provider_usage(
    initial_orders: Mapping[str, UUID | None],
    calls: Sequence[ProviderCallRecord],
    *,
    pricing_snapshot: PricingSnapshot | None,
    configured_model: str | None,
) -> ProviderUsageSummary:
    """Aggregate real attempts without partial order-cost or token estimates."""

    if not initial_orders:
        raise ValueError("initial order denominator must be non-empty")
    calls_by_case: dict[str, list[ProviderCallRecord]] = defaultdict(list)
    missing_attribution = 0
    missing_pricing = 0
    incomplete_calls = 0
    inconsistent_totals = 0
    for record in calls:
        calls_by_case[record.initial_case_id].append(record)
        expected_order_id = initial_orders.get(record.initial_case_id)
        if (
            record.initial_case_id not in initial_orders
            or expected_order_id is None
            or record.initial_order_id is None
            or record.initial_order_id != expected_order_id
        ):
            missing_attribution += 1
        if (
            record.model is None
            or configured_model is None
            or record.model != configured_model
            or pricing_snapshot is None
            or record.pricing_snapshot_id != pricing_snapshot.snapshot_id
            or pricing_snapshot.model != configured_model
        ):
            missing_pricing += 1
        if (
            record.initial_case_id not in initial_orders
            or expected_order_id is None
            or record.initial_order_id is None
            or record.initial_order_id != expected_order_id
            or record.input_tokens is None
            or record.output_tokens is None
            or record.model is None
            or configured_model is None
            or record.model != configured_model
            or pricing_snapshot is None
            or record.pricing_snapshot_id != pricing_snapshot.snapshot_id
            or pricing_snapshot.model != configured_model
        ):
            incomplete_calls += 1
        if (
            record.total_tokens is not None
            and record.input_tokens is not None
            and record.output_tokens is not None
            and record.total_tokens != record.input_tokens + record.output_tokens
        ):
            inconsistent_totals += 1

    order_summaries: dict[str, OrderUsageSummary] = {}
    called_orders = 0
    zero_call_orders = 0
    complete_orders = 0
    incomplete_orders = 0
    order_costs: list[Decimal] = []

    for case_id, order_id in initial_orders.items():
        case_calls = calls_by_case.get(case_id, [])
        if not case_calls:
            zero_call_orders += 1
            order_cost = Decimal(0)
            complete = True
        else:
            called_orders += 1
            order_cost = Decimal(0)
            complete = order_id is not None
            for record in case_calls:
                attributed = record.initial_order_id == order_id and order_id is not None
                pricing_matches = (
                    pricing_snapshot is not None
                    and configured_model is not None
                    and pricing_snapshot.model == configured_model
                    and record.model == configured_model
                    and record.pricing_snapshot_id == pricing_snapshot.snapshot_id
                )
                usage_complete = (
                    record.input_tokens is not None and record.output_tokens is not None
                )
                call_complete = attributed and pricing_matches and usage_complete
                if not call_complete:
                    complete = False
                    continue
                assert (
                    pricing_snapshot is not None
                    and record.input_tokens is not None
                    and record.output_tokens is not None
                )
                order_cost += (
                    Decimal(record.input_tokens) / Decimal(pricing_snapshot.token_unit)
                ) * pricing_snapshot.input_rate_usd
                order_cost += (
                    Decimal(record.output_tokens) / Decimal(pricing_snapshot.token_unit)
                ) * pricing_snapshot.output_rate_usd
            if complete:
                complete_orders += 1
            else:
                incomplete_orders += 1
                order_cost = None
        if order_cost is not None:
            order_costs.append(order_cost)
        order_summaries[case_id] = OrderUsageSummary(
            case_id=case_id,
            order_id=order_id,
            call_count=len(case_calls),
            estimated_model_cost_usd=order_cost,
            usage_complete=complete,
        )

    input_sum, input_count, input_missing = _sum_available(
        tuple(record.input_tokens for record in calls)
    )
    output_sum, output_count, output_missing = _sum_available(
        tuple(record.output_tokens for record in calls)
    )
    total_sum, total_count, total_missing = _sum_available(
        tuple(record.total_tokens for record in calls)
    )
    total_cost = (
        sum(order_costs, Decimal(0)) / Decimal(len(initial_orders))
        if incomplete_orders == 0 and missing_attribution == 0
        else None
    )
    return ProviderUsageSummary(
        initial_order_count=len(initial_orders),
        gemini_call_count=len(calls),
        failed_call_count=sum(record.failed for record in calls),
        gemini_called_order_count=called_orders,
        zero_call_order_count=zero_call_orders,
        complete_usage_order_count=complete_orders,
        incomplete_usage_order_count=incomplete_orders,
        incomplete_usage_call_count=incomplete_calls,
        missing_call_attribution_count=missing_attribution,
        input_tokens_sum=input_sum,
        available_input_token_count=input_count,
        missing_input_token_count=input_missing,
        output_tokens_sum=output_sum,
        available_output_token_count=output_count,
        missing_output_token_count=output_missing,
        total_tokens_sum=total_sum,
        available_total_token_count=total_count,
        missing_total_token_count=total_missing,
        inconsistent_reported_total_count=inconsistent_totals,
        missing_pricing_snapshot_count=missing_pricing,
        estimated_model_cost_per_initial_order=total_cost,
        orders=MappingProxyType(order_summaries),
    )


__all__ = [
    "EvaluationMeasurements",
    "MeasuredGeminiProvider",
    "MeasuredGeminiProviderFactory",
    "OrderUsageSummary",
    "PricingSnapshot",
    "ProviderCallRecord",
    "ProviderUsageSummary",
    "TimingStage",
    "TimingSummary",
    "aggregate_provider_usage",
    "load_pricing_snapshot",
    "measure_application_stages",
    "measured_gemini_provider_factory",
]

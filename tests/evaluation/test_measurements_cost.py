from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import anyio
import pytest

from opsflow.documents.errors import UnsupportedDocumentTypeError
from opsflow.documents.models import DocumentInput
from opsflow.domain.records import SourceDocumentType
from opsflow.evaluation.measurements import (
    EvaluationMeasurements,
    MeasuredGeminiProvider,
    PricingSnapshot,
    ProviderCallRecord,
    aggregate_provider_usage,
    load_pricing_snapshot,
    measure_application_stages,
    measured_gemini_provider_factory,
)
from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.gemini import GeminiConfig, GeminiProvider
from opsflow.extraction.provider import StructuredGenerationRequest, StructuredGenerationResult

MODEL = "gemini-3.8-flash"
SNAPSHOT_ID = "google-gemini-3.8-flash-standard-paid-2026-10-10"
ORDER_A = UUID("00000000-0000-4000-8000-000000000001")
ORDER_B = UUID("00000000-0000-4000-8000-000000000002")


def pricing() -> PricingSnapshot:
    return PricingSnapshot(
        snapshot_id=SNAPSHOT_ID,
        model=MODEL,
        token_unit=1_000_000,
        input_rate_usd=Decimal("0.75"),
        output_rate_usd=Decimal("3.75"),
    )


def call(
    *,
    case_id: str = "case-a",
    order_id: UUID | None = ORDER_A,
    attempt: int = 1,
    input_tokens: int | None = 100_000,
    output_tokens: int | None = 20_000,
    total_tokens: int | None = 120_000,
    model: str | None = MODEL,
    snapshot_id: str | None = SNAPSHOT_ID,
    duration_ms: Decimal = Decimal("12.5"),
    failed: bool = False,
) -> ProviderCallRecord:
    return ProviderCallRecord(
        initial_case_id=case_id,
        initial_order_id=order_id,
        attempt_index=attempt,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        model=model,
        pricing_snapshot_id=snapshot_id,
        failed=failed,
    )


def test_stage_timing_uses_nearest_rank_and_keeps_missing_samples_unavailable() -> None:
    ticks = iter((0, 1_000_000, 2_000_000, 5_000_000, 8_000_000, 13_000_000))
    measurements = EvaluationMeasurements(monotonic_ns=lambda: next(ticks))

    with measurements.measure("parse_ms"):
        pass
    with measurements.measure("parse_ms"):
        pass
    with measurements.measure("parse_ms"):
        pass

    summary = measurements.summary("parse_ms")
    assert summary.sample_count == 3
    assert summary.minimum_ms == Decimal("1")
    assert summary.maximum_ms == Decimal("5")
    assert summary.sum_ms == Decimal("9")
    assert summary.p50_ms == Decimal("3")
    assert summary.p95_ms == Decimal("5")

    missing = measurements.summary("live_gemini_call_ms")
    assert missing.sample_count == 0
    assert missing.minimum_ms is None
    assert missing.p50_ms is None
    assert missing.p95_ms is None


def test_timing_records_only_explicit_stage_boundaries_not_setup() -> None:
    measurements = EvaluationMeasurements(monotonic_ns=lambda: 4_000_000)
    # Database initialization and fixture setup occur outside measured scopes.
    measurements.record("parse_ms", Decimal("3.25"))

    summary = measurements.summary("parse_ms")
    assert summary.sample_count == 1
    assert summary.sum_ms == Decimal("3.25")
    assert measurements.summary("provider_free_intake_ms").sample_count == 0


def test_application_stage_wrappers_measure_real_functions_and_restore_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    orchestration_application = importlib.import_module("opsflow.application.orchestration")
    validation_application = importlib.import_module("opsflow.application.validation")
    validation_engine = validation_application.validation_engine
    original_process_document = orchestration_application.process_document
    monkeypatch.setattr(validation_engine, "validate", lambda: None)
    validation_stub = validation_engine.validate
    measurements = EvaluationMeasurements()

    with measure_application_stages(measurements, case_id="case-a"):
        parsed = orchestration_application.process_document(
            DocumentInput(
                document_type=SourceDocumentType.EMAIL_BODY,
                name="case-a.txt",
                mime_type="text/plain",
                content=b"Purchase order PO-1",
            )
        )
        assert parsed.text
        validation_engine.validate()

    with (
        measure_application_stages(measurements, case_id="case-a"),
        pytest.raises(UnsupportedDocumentTypeError),
    ):
        orchestration_application.process_document(
            DocumentInput(
                document_type=SourceDocumentType.FORM,
                name="unsupported.form",
                mime_type="text/plain",
                content=b"not parseable",
            )
        )

    assert orchestration_application.process_document is original_process_document
    assert validation_engine.validate is validation_stub
    assert measurements.summary("parse_ms").sample_count == 1
    assert measurements.summary("deterministic_validation_ms").sample_count == 1


def test_multiple_calls_and_authorized_retry_are_attributed_to_one_initial_order() -> None:
    result = aggregate_provider_usage(
        {"case-a": ORDER_A, "case-b": ORDER_B},
        (
            call(attempt=1, input_tokens=100, output_tokens=20, total_tokens=120),
            call(attempt=2, input_tokens=80, output_tokens=30, total_tokens=110),
        ),
        pricing_snapshot=pricing(),
        configured_model=MODEL,
    )

    assert result.initial_order_count == 2
    assert result.gemini_called_order_count == 1
    assert result.zero_call_order_count == 1
    assert result.complete_usage_order_count == 1
    assert result.incomplete_usage_order_count == 0
    assert result.orders["case-a"].call_count == 2
    assert result.orders["case-a"].estimated_model_cost_usd == Decimal("0.0003225")
    assert result.orders["case-b"].estimated_model_cost_usd == Decimal("0")
    assert result.estimated_model_cost_per_initial_order == Decimal("0.00016125")


@pytest.mark.parametrize(
    ("field", "value", "expected_counter"),
    [
        ("order_id", None, "missing_call_attribution_count"),
        ("input_tokens", None, "missing_input_token_count"),
        ("output_tokens", None, "missing_output_token_count"),
        ("snapshot_id", None, "missing_pricing_snapshot_count"),
        ("model", "gemini-wrong-model", "missing_pricing_snapshot_count"),
    ],
)
def test_incomplete_call_makes_aggregate_unavailable_without_partial_cost(
    field: str, value: object, expected_counter: str
) -> None:
    broken = call(**{field: value})
    result = aggregate_provider_usage(
        {"case-a": ORDER_A, "case-b": ORDER_B},
        (call(input_tokens=100, output_tokens=20), broken),
        pricing_snapshot=pricing(),
        configured_model=MODEL,
    )

    assert getattr(result, expected_counter) == 1
    assert result.incomplete_usage_order_count == 1
    assert result.incomplete_usage_call_count == 1
    assert result.orders["case-a"].estimated_model_cost_usd is None
    assert result.estimated_model_cost_per_initial_order is None
    # The complete second order's cost is retained as evidence, but never used
    # as a partial workload estimate.
    assert result.orders["case-b"].estimated_model_cost_usd == Decimal("0")


def test_missing_total_token_is_counted_without_rewriting_authoritative_values() -> None:
    result = aggregate_provider_usage(
        {"case-a": ORDER_A},
        (call(input_tokens=2, output_tokens=3, total_tokens=None),),
        pricing_snapshot=pricing(),
        configured_model=MODEL,
    )

    assert result.missing_total_token_count == 1
    assert result.available_total_token_count == 0
    assert result.total_tokens_sum is None
    assert result.inconsistent_reported_total_count == 0
    assert result.orders["case-a"].estimated_model_cost_usd is not None


def test_inconsistent_reported_total_is_flagged_without_mutating_usage() -> None:
    result = aggregate_provider_usage(
        {"case-a": ORDER_A},
        (call(input_tokens=2, output_tokens=3, total_tokens=99),),
        pricing_snapshot=pricing(),
        configured_model=MODEL,
    )

    assert result.input_tokens_sum == 2
    assert result.output_tokens_sum == 3
    assert result.total_tokens_sum == 99
    assert result.inconsistent_reported_total_count == 1


def test_zero_call_orders_have_known_zero_cost_without_pricing() -> None:
    result = aggregate_provider_usage(
        {"case-a": ORDER_A, "case-b": ORDER_B},
        (),
        pricing_snapshot=None,
        configured_model=MODEL,
    )

    assert result.zero_call_order_count == 2
    assert result.incomplete_usage_order_count == 0
    assert result.estimated_model_cost_per_initial_order == Decimal("0")
    assert all(order.estimated_model_cost_usd == Decimal("0") for order in result.orders.values())


def test_missing_pricing_preserves_call_and_latency_observations() -> None:
    measured = call(snapshot_id=None, duration_ms=Decimal("18.75"))
    result = aggregate_provider_usage(
        {"case-a": ORDER_A},
        (measured,),
        pricing_snapshot=None,
        configured_model=MODEL,
    )
    latency = EvaluationMeasurements()
    latency.record("live_gemini_call_ms", measured.duration_ms)

    assert result.gemini_call_count == 1
    assert result.missing_pricing_snapshot_count == 1
    assert result.estimated_model_cost_per_initial_order is None
    assert latency.summary("live_gemini_call_ms").p50_ms == Decimal("18.75")


def test_failed_provider_attempt_is_counted_and_cannot_contribute_partial_cost() -> None:
    result = aggregate_provider_usage(
        {"case-a": ORDER_A},
        (
            call(
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                failed=True,
            ),
        ),
        pricing_snapshot=pricing(),
        configured_model=MODEL,
    )

    assert result.gemini_call_count == 1
    assert result.failed_call_count == 1
    assert result.incomplete_usage_call_count == 1
    assert result.estimated_model_cost_per_initial_order is None


def test_pricing_uses_decimal_arithmetic_without_float_round_trip() -> None:
    result = aggregate_provider_usage(
        {"case-a": ORDER_A},
        (call(input_tokens=1, output_tokens=1),),
        pricing_snapshot=pricing(),
        configured_model=MODEL,
    )

    assert type(result.estimated_model_cost_per_initial_order) is Decimal
    assert result.estimated_model_cost_per_initial_order == Decimal("0.0000045")


def test_dated_snapshot_loads_exact_model_tier_rates_and_source() -> None:
    snapshot = load_pricing_snapshot(
        "evals/pricing/2026-10-10-google-gemini-3.8-flash-standard-paid.json"
    )

    assert snapshot.snapshot_id == SNAPSHOT_ID
    assert snapshot.model == MODEL
    assert snapshot.pricing_tier == "standard_paid"
    assert snapshot.token_unit == 1_000_000
    assert snapshot.input_rate_usd == Decimal("0.75")
    assert snapshot.output_rate_usd == Decimal("3.75")
    assert snapshot.effective_through == "2026-12-31"
    assert snapshot.source_url == "https://ai.google.dev/gemini-api/docs/pricing"


def test_provider_wrapper_records_each_attempt_tokens_failure_and_latency() -> None:
    class SequenceProvider:
        def __init__(self) -> None:
            self.results = [
                StructuredGenerationResult({}, input_tokens=3, output_tokens=2, total_tokens=5),
                RuntimeError("bounded local failure"),
            ]

        async def generate_structured(self, request: StructuredGenerationRequest):
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    ticks = iter((0, 2_000_000, 4_000_000, 9_000_000))
    measurements = EvaluationMeasurements(monotonic_ns=lambda: next(ticks))
    provider = MeasuredGeminiProvider(
        SequenceProvider(),
        measurements,
        case_id="case-a",
        model=MODEL,
        pricing_snapshot_id=SNAPSHOT_ID,
        attempt_counter=[0],
    )
    request = StructuredGenerationRequest("v1", "system", "source", {})

    async def invoke_attempts() -> StructuredGenerationResult:
        result = await provider.generate_structured(request)
        with pytest.raises(RuntimeError, match="bounded local failure"):
            await provider.generate_structured(request)
        return result

    result = anyio.run(invoke_attempts)
    assert result.total_tokens == 5

    assert [record.attempt_index for record in measurements.provider_calls] == [1, 2]
    assert measurements.provider_calls[0].input_tokens == 3
    assert measurements.provider_calls[0].output_tokens == 2
    assert measurements.provider_calls[0].failed is False
    assert measurements.provider_calls[1].input_tokens is None
    assert measurements.provider_calls[1].failed is True
    assert measurements.summary("live_gemini_call_ms").sample_count == 2
    measurements.bind_case_order("case-a", ORDER_A)
    assert {record.initial_order_id for record in measurements.provider_calls} == {ORDER_A}


def test_live_factory_rejects_fake_provider_instead_of_using_it_as_gemini() -> None:
    factory = measured_gemini_provider_factory(
        lambda: FakeProvider(()),
        EvaluationMeasurements(),
        case_id="case-a",
        model=MODEL,
        pricing_snapshot_id=SNAPSHOT_ID,
    )

    with pytest.raises(TypeError, match="configured GeminiProvider"):
        factory()


def test_live_factory_wraps_mocked_gemini_results_and_attributes_failed_attempts() -> None:
    class MockInteractions:
        def __init__(self) -> None:
            self.results = [
                RuntimeError("mocked Gemini transport failure"),
                SimpleNamespace(
                    output_text='{"purchase_order_number": "PO-101"}',
                    usage=SimpleNamespace(
                        total_input_tokens=11,
                        total_output_tokens=7,
                        total_tokens=18,
                    ),
                ),
            ]

        async def create(self, **_kwargs):
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    measurements = EvaluationMeasurements()
    gemini = GeminiProvider(
        GeminiConfig("mock-key", MODEL, 10),
        client=SimpleNamespace(interactions=MockInteractions()),
    )
    factory = measured_gemini_provider_factory(
        lambda: gemini,
        measurements,
        case_id="case-a",
        model=MODEL,
        pricing_snapshot_id=SNAPSHOT_ID,
    )
    request = StructuredGenerationRequest("v1", "system", "source", {})

    async def invoke() -> StructuredGenerationResult:
        provider = factory()
        with pytest.raises(Exception, match="Gemini provider request failed"):
            await provider.generate_structured(request)
        return await provider.generate_structured(request)

    result = anyio.run(invoke)
    measurements.bind_case_order("case-a", ORDER_A)

    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.total_tokens == 18
    assert [record.attempt_index for record in measurements.provider_calls] == [1, 2]
    assert [record.failed for record in measurements.provider_calls] == [True, False]
    assert [record.total_tokens for record in measurements.provider_calls] == [None, 18]
    assert {record.initial_case_id for record in measurements.provider_calls} == {"case-a"}
    assert {record.initial_order_id for record in measurements.provider_calls} == {ORDER_A}

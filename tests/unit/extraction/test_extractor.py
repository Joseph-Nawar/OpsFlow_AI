import asyncio
from copy import deepcopy
from datetime import date
from decimal import Decimal
from inspect import signature
from pathlib import Path
from uuid import UUID

import pytest

from opsflow.documents.models import CanonicalDocument
from opsflow.domain.order import Order
from opsflow.domain.records import SourceDocumentType
from opsflow.extraction.errors import (
    ExtractionResponseError,
    ProviderError,
    ProviderTimeoutError,
)
from opsflow.extraction.extractor import (
    OrderExtractor,
    convert_provider_response,
    parse_decimal_text,
    parse_iso_date,
    parse_provider_response,
    validate_evidence,
)
from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.models import (
    ProviderEvidenceResponse,
    ProviderExtractionResponse,
)
from opsflow.extraction.prompt import RenderedSource, SourceSegment
from opsflow.extraction.provider import StructuredGenerationResult


def _payload() -> dict[str, object]:
    return {
        "customer_name": "Acme Supplies",
        "customer_reference": "CUST-1",
        "po_number": "PO-1",
        "order_date": "2026-09-17",
        "requested_delivery_date": "2026-09-10",
        "currency": "XYZ",
        "lines": [
            {
                "sku": None,
                "description": None,
                "quantity": "-3",
                "submitted_price": "0",
            },
            {
                "sku": "SKU-2",
                "description": "Second line",
                "quantity": "+2",
                "submitted_price": "1.2e3",
            },
        ],
        "notes": "Synthetic note",
        "evidence": [],
    }


def _document() -> CanonicalDocument:
    return CanonicalDocument(
        document_type=SourceDocumentType.EMAIL_BODY,
        name="synthetic-email",
        mime_type="text/plain",
        sha256="a" * 64,
        size_bytes=1,
        source_reference=None,
        metadata=(),
        text="PO-1 Acme Supplies -3 SKU-2",
        pages=(),
        tables=(),
        warnings=(),
    )


def _source(*segments: SourceSegment) -> RenderedSource:
    return RenderedSource(
        content="\n\n".join(segment.text for segment in segments),
        segments=segments,
    )


def _response_with_evidence(*evidence: dict[str, str]) -> ProviderExtractionResponse:
    payload = _payload()
    payload["evidence"] = list(evidence)
    return parse_provider_response(payload)


def test_parse_provider_response_strictly_accepts_valid_structured_payload() -> None:
    response = parse_provider_response(_payload())

    assert response.po_number == "PO-1"
    assert response.lines[0].quantity == "-3"
    assert response.lines[1].submitted_price == "1.2e3"


@pytest.mark.parametrize("payload", [None, [], "not-an-object", 42])
def test_parse_provider_response_rejects_unsupported_payload_shapes(payload: object) -> None:
    with pytest.raises(ExtractionResponseError, match="provider response"):
        parse_provider_response(payload)


def test_parse_provider_response_translates_schema_errors_without_raw_payload_leakage() -> None:
    payload = _payload()
    payload["source_secret"] = "FULL RAW PO CONTENT APIKEY-123"

    with pytest.raises(ExtractionResponseError) as raised:
        parse_provider_response(payload)

    message = str(raised.value)
    assert "FULL RAW PO CONTENT" not in message
    assert "APIKEY-123" not in message
    assert "source_secret" not in message


def test_parse_provider_response_rejects_extra_missing_and_wrong_type_values() -> None:
    extra = _payload()
    extra["unexpected"] = "nope"
    missing = _payload()
    del missing["currency"]
    wrong_type = _payload()
    wrong_type["currency"] = 123

    for payload in (extra, missing, wrong_type):
        with pytest.raises(ExtractionResponseError):
            parse_provider_response(payload)


def test_parse_iso_date_accepts_none_and_exact_calendar_date() -> None:
    assert parse_iso_date(None, field_path="order_date") is None
    assert parse_iso_date("2026-09-17", field_path="order_date") == date(2026, 9, 17)


@pytest.mark.parametrize(
    "value",
    [
        "17/09/2026",
        "09/17/2026",
        "2026-9-17",
        "2026-09-7",
        "2026-02-30",
        "2026-09-17T00:00:00",
        " 2026-09-17",
        "2026-09-17 ",
        "unknown",
    ],
)
def test_parse_iso_date_rejects_non_exact_or_impossible_values(value: str) -> None:
    with pytest.raises(ExtractionResponseError) as raised:
        parse_iso_date(value, field_path="order_date")

    assert value not in str(raised.value)
    assert "order_date" in str(raised.value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("0", Decimal("0")),
        ("-3", Decimal("-3")),
        ("+2", Decimal("2")),
        (".5", Decimal("0.5")),
        ("10.", Decimal("10")),
        ("1.2e3", Decimal("1.2e3")),
        ("-4E-2", Decimal("-4E-2")),
    ],
)
def test_parse_decimal_text_accepts_exact_finite_decimal_grammar(
    value: str | None,
    expected: Decimal | None,
) -> None:
    assert parse_decimal_text(value, field_path="lines[0].quantity") == expected


@pytest.mark.parametrize(
    "value",
    ["NaN", "Infinity", "-Infinity", "1_000", "1,000", " 2", "2 ", "", "text"],
)
def test_parse_decimal_text_rejects_nonfinite_or_unsafe_numeric_text(value: str) -> None:
    with pytest.raises(ExtractionResponseError) as raised:
        parse_decimal_text(value, field_path="lines[0].quantity")

    if value:
        assert value not in str(raised.value)


@pytest.mark.parametrize("value", [1, 1.5, True, Decimal("1")])
def test_parse_decimal_text_rejects_non_string_values(value: object) -> None:
    with pytest.raises(ExtractionResponseError):
        parse_decimal_text(value, field_path="lines[0].quantity")  # type: ignore[arg-type]


def test_validate_evidence_accepts_top_level_and_line_paths() -> None:
    response = _response_with_evidence(
        {
            "field_path": "po_number",
            "source_location": "text:body",
            "quote": "PO-1",
        },
        {
            "field_path": "lines[0].quantity",
            "source_location": "page:2",
            "quote": "-3",
        },
    )
    rendered = _source(
        SourceSegment("text:body", "PO-1"),
        SourceSegment("page:2", "SKU-1 quantity -3"),
    )

    evidence = validate_evidence(response, rendered)

    assert evidence[0].field_path == "po_number"
    assert evidence[1].field_path == "lines[0].quantity"


def test_validate_evidence_preserves_provider_order_and_allows_no_evidence() -> None:
    rendered = _source(SourceSegment("text:body", "PO-1 Acme"))
    no_evidence = parse_provider_response(_payload())
    ordered = _response_with_evidence(
        {
            "field_path": "customer_name",
            "source_location": "text:body",
            "quote": "Acme",
        },
        {
            "field_path": "po_number",
            "source_location": "text:body",
            "quote": "PO-1",
        },
    )

    assert validate_evidence(no_evidence, rendered) == ()
    assert [item.field_path for item in validate_evidence(ordered, rendered)] == [
        "customer_name",
        "po_number",
    ]


@pytest.mark.parametrize(
    "field_path",
    [
        "unknown",
        "customer_name.extra",
        "lines.foo.quantity",
        "lines[-1].quantity",
        "lines[01].quantity",
        "lines[0].unknown",
        "lines[0].quantity.extra",
    ],
)
def test_validate_evidence_rejects_malformed_field_paths(field_path: str) -> None:
    response = _response_with_evidence(
        {
            "field_path": field_path,
            "source_location": "text:body",
            "quote": "PO-1",
        }
    )

    with pytest.raises(ExtractionResponseError):
        validate_evidence(response, _source(SourceSegment("text:body", "PO-1")))


def test_validate_evidence_rejects_out_of_range_line_index() -> None:
    response = _response_with_evidence(
        {
            "field_path": "lines[2].sku",
            "source_location": "text:body",
            "quote": "SKU-2",
        }
    )

    with pytest.raises(ExtractionResponseError):
        validate_evidence(response, _source(SourceSegment("text:body", "SKU-2")))


def test_validate_evidence_rejects_null_referenced_field() -> None:
    payload = _payload()
    payload["customer_name"] = None
    payload["evidence"] = [
        {
            "field_path": "customer_name",
            "source_location": "text:body",
            "quote": "Acme",
        }
    ]

    with pytest.raises(ExtractionResponseError, match="customer_name"):
        validate_evidence(
            parse_provider_response(payload), _source(SourceSegment("text:body", "Acme"))
        )


def test_validate_evidence_rejects_duplicate_field_path() -> None:
    response = _response_with_evidence(
        {
            "field_path": "po_number",
            "source_location": "text:body",
            "quote": "PO-1",
        },
        {
            "field_path": "po_number",
            "source_location": "text:body",
            "quote": "PO-1",
        },
    )

    with pytest.raises(ExtractionResponseError, match="po_number"):
        validate_evidence(response, _source(SourceSegment("text:body", "PO-1")))


def test_validate_evidence_rejects_invented_location() -> None:
    response = _response_with_evidence(
        {
            "field_path": "po_number",
            "source_location": "page:99",
            "quote": "PO-1",
        }
    )

    with pytest.raises(ExtractionResponseError, match="page:99"):
        validate_evidence(response, _source(SourceSegment("text:body", "PO-1")))


def test_validate_evidence_rejects_quote_from_wrong_segment() -> None:
    response = _response_with_evidence(
        {
            "field_path": "po_number",
            "source_location": "text:body",
            "quote": "PO-1",
        }
    )

    with pytest.raises(ExtractionResponseError):
        validate_evidence(
            response,
            _source(SourceSegment("text:body", "not the quote"), SourceSegment("page:2", "PO-1")),
        )


def test_validate_evidence_rejects_altered_or_empty_quote() -> None:
    altered = _response_with_evidence(
        {
            "field_path": "po_number",
            "source_location": "text:body",
            "quote": "PO-2",
        }
    )
    with pytest.raises(ExtractionResponseError):
        validate_evidence(altered, _source(SourceSegment("text:body", "PO-1")))

    empty_evidence = ProviderEvidenceResponse.model_construct(
        field_path="po_number", source_location="text:body", quote=""
    )
    empty = parse_provider_response(_payload()).model_copy(update={"evidence": (empty_evidence,)})
    with pytest.raises(ExtractionResponseError):
        validate_evidence(empty, _source(SourceSegment("text:body", "PO-1")))


def test_convert_provider_response_produces_typed_immutable_draft() -> None:
    response = parse_provider_response(_payload())
    rendered = _source(SourceSegment("text:body", "PO-1 Acme Supplies -3 SKU-2"))

    draft = convert_provider_response(response, _document(), rendered)

    assert draft.source_sha256 == "a" * 64
    assert draft.source_document_type is SourceDocumentType.EMAIL_BODY
    assert draft.order_date == date(2026, 9, 17)
    assert draft.requested_delivery_date == date(2026, 9, 10)
    assert draft.currency == "XYZ"
    assert draft.lines[0].quantity == Decimal("-3")
    assert draft.lines[1].submitted_price == Decimal("1.2e3")
    assert draft.lines[0].sku is None
    assert draft.lines[0].description is None
    assert isinstance(draft.lines, tuple)
    assert isinstance(draft.evidence, tuple)


def test_convert_provider_response_preserves_line_order_literal_values_and_evidence() -> None:
    payload = _payload()
    payload["lines"] = [
        {
            "sku": "UNKNOWN-2",
            "description": "second",
            "quantity": "0",
            "submitted_price": "10.",
        },
        {
            "sku": None,
            "description": "first",
            "quantity": "-3",
            "submitted_price": ".5",
        },
    ]
    payload["evidence"] = [
        {
            "field_path": "lines[0].sku",
            "source_location": "text:body",
            "quote": "UNKNOWN-2",
        },
        {
            "field_path": "lines[1].quantity",
            "source_location": "text:body",
            "quote": "-3",
        },
    ]
    response = parse_provider_response(payload)
    rendered = _source(SourceSegment("text:body", "UNKNOWN-2 -3"))

    draft = convert_provider_response(response, _document(), rendered)

    assert [line.sku for line in draft.lines] == ["UNKNOWN-2", None]
    assert [line.quantity for line in draft.lines] == [Decimal("0"), Decimal("-3")]
    assert [item.field_path for item in draft.evidence] == [
        "lines[0].sku",
        "lines[1].quantity",
    ]


def test_convert_provider_response_is_deterministic_for_equal_inputs() -> None:
    payload = _payload()
    response = parse_provider_response(payload)
    rendered = _source(SourceSegment("text:body", "PO-1 Acme Supplies -3 SKU-2"))

    first = convert_provider_response(response, _document(), rendered)
    second = convert_provider_response(
        parse_provider_response(deepcopy(payload)), _document(), rendered
    )

    assert first == second


def test_order_extractor_maps_one_document_to_one_draft_with_one_provider_call() -> None:
    provider = FakeProvider((StructuredGenerationResult(payload=_payload()),))

    draft = asyncio.run(OrderExtractor(provider).extract(_document()))

    assert draft.source_sha256 == _document().sha256
    assert draft.source_document_type is SourceDocumentType.EMAIL_BODY
    assert draft.lines[0].quantity == Decimal("-3")
    assert len(provider.requests) == 1


def test_order_extractor_preserves_explicit_nulls_and_multiple_lines() -> None:
    payload = _payload()
    payload.update(
        {
            "customer_name": None,
            "customer_reference": None,
            "po_number": None,
            "order_date": None,
            "requested_delivery_date": None,
            "currency": None,
            "notes": None,
            "lines": [
                {
                    "sku": None,
                    "description": None,
                    "quantity": None,
                    "submitted_price": None,
                },
                {
                    "sku": "SKU-2",
                    "description": "Second",
                    "quantity": "0",
                    "submitted_price": "-3",
                },
            ],
        }
    )
    provider = FakeProvider((StructuredGenerationResult(payload=payload),))

    draft = asyncio.run(OrderExtractor(provider).extract(_document()))

    assert draft.customer_name is None
    assert draft.order_date is None
    assert draft.lines[0].quantity is None
    assert draft.lines[1].quantity == Decimal("0")
    assert draft.lines[1].submitted_price == Decimal("-3")


@pytest.mark.parametrize(
    "error_type",
    [ProviderError, ProviderTimeoutError],
)
def test_order_extractor_propagates_provider_errors_unchanged(
    error_type: type[ProviderError],
) -> None:
    error = error_type("scripted provider failure")
    provider = FakeProvider((error,))

    with pytest.raises(error_type) as raised:
        asyncio.run(OrderExtractor(provider).extract(_document()))

    assert raised.value is error
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"extra": "nope"}),
        lambda payload: payload.pop("currency"),
        lambda payload: payload.update({"currency": 123}),
    ],
)
def test_order_extractor_rejects_malformed_provider_payloads(mutate: object) -> None:
    payload = _payload()
    mutate(payload)  # type: ignore[operator]
    provider = FakeProvider((StructuredGenerationResult(payload=payload),))

    with pytest.raises(ExtractionResponseError):
        asyncio.run(OrderExtractor(provider).extract(_document()))


def test_order_extractor_produces_equal_drafts_for_equal_inputs_and_results() -> None:
    first_provider = FakeProvider((StructuredGenerationResult(payload=_payload()),))
    second_provider = FakeProvider((StructuredGenerationResult(payload=deepcopy(_payload())),))

    first = asyncio.run(OrderExtractor(first_provider).extract(_document()))
    second = asyncio.run(OrderExtractor(second_provider).extract(_document()))

    assert first == second
    assert len(first_provider.requests) == 1
    assert len(second_provider.requests) == 1


def test_order_extractor_does_not_accept_document_collections() -> None:
    parameters = list(signature(OrderExtractor.extract).parameters)

    assert parameters == ["self", "document"]


def test_order_extractor_does_not_mutate_an_unrelated_order() -> None:
    order = Order.received(
        UUID("11111111-1111-1111-1111-111111111111"),
        customer_reference="CUST-1",
        po_number="PO-1",
        currency="USD",
    )
    before = order
    provider = FakeProvider((StructuredGenerationResult(payload=_payload()),))

    asyncio.run(OrderExtractor(provider).extract(_document()))

    assert order == before
    assert order.state.value == "RECEIVED"


def test_extractor_module_has_no_order_or_infrastructure_imports() -> None:
    import opsflow.extraction.extractor as extractor_module

    source = Path(extractor_module.__file__).read_text()

    for forbidden in (
        "opsflow.domain.order",
        "opsflow.application",
        "opsflow.persistence",
        "fastapi",
        "sqlalchemy",
        "httpx",
        "requests",
        "google",
    ):
        assert forbidden not in source

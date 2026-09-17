import asyncio
import socket

import pytest

from opsflow.extraction.errors import ProviderError, ProviderTimeoutError
from opsflow.extraction.fake import FakeProvider
from opsflow.extraction.provider import StructuredGenerationRequest, StructuredGenerationResult


def _request(label: str) -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        prompt_version="phase4-extraction-v1",
        system_instruction="extract only",
        user_content=label,
        response_schema={"type": "object", "label": label},
    )


def test_fake_provider_records_requests_and_returns_scripted_result() -> None:
    request = _request("source-1")
    expected = StructuredGenerationResult(payload={"malformed": object()})
    provider = FakeProvider((expected,))

    result = asyncio.run(provider.generate_structured(request))

    assert result is expected
    assert provider.requests == [request]


def test_fake_provider_returns_scripted_results_in_call_order() -> None:
    first_request = _request("source-1")
    second_request = _request("source-2")
    first = StructuredGenerationResult(payload={"sequence": 1})
    second = StructuredGenerationResult(payload={"sequence": 2})
    provider = FakeProvider((first, second))

    assert asyncio.run(provider.generate_structured(first_request)) is first
    assert asyncio.run(provider.generate_structured(second_request)) is second
    assert provider.requests == [first_request, second_request]


@pytest.mark.parametrize(
    "error",
    [
        ProviderError("scripted provider failure"),
        ProviderTimeoutError("scripted provider timeout"),
    ],
)
def test_fake_provider_raises_scripted_provider_errors_unchanged(error: ProviderError) -> None:
    provider = FakeProvider((error,))

    with pytest.raises(type(error)) as raised:
        asyncio.run(provider.generate_structured(_request("source")))

    assert raised.value is error


def test_fake_provider_passes_malformed_payload_without_validation() -> None:
    malformed = object()
    provider = FakeProvider((StructuredGenerationResult(payload=malformed),))

    result = asyncio.run(provider.generate_structured(_request("source")))

    assert result.payload is malformed


def test_fake_provider_exhaustion_is_a_safe_provider_error() -> None:
    provider = FakeProvider(())

    with pytest.raises(ProviderError, match="script exhausted") as raised:
        asyncio.run(provider.generate_structured(_request("source")))

    assert "source" not in str(raised.value)


def test_fake_provider_requires_no_network_or_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("FakeProvider attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.delenv("OPSFLOW_GEMINI_API_KEY", raising=False)

    provider = FakeProvider((StructuredGenerationResult(payload={}),))

    assert asyncio.run(provider.generate_structured(_request("source"))).payload == {}

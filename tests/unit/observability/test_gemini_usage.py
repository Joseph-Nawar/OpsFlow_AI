"""Gemini usage metadata is propagated only when the installed SDK exposes it."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from opsflow.extraction.errors import ProviderError
from opsflow.extraction.gemini import GeminiConfig, GeminiProvider
from opsflow.extraction.provider import StructuredGenerationRequest
from opsflow.observability.runtime import Observability, reset_observability, set_observability


class _Interactions:
    async def create(self, **kwargs: object) -> SimpleNamespace:
        del kwargs
        return SimpleNamespace(
            output_text='{"value": "ok"}',
            usage=SimpleNamespace(
                total_input_tokens=11,
                total_output_tokens=7,
                total_tokens=18,
            ),
        )


class _AsyncClient:
    interactions = _Interactions()

    async def aclose(self) -> None:
        return None


class _Client:
    aio = _AsyncClient()

    def close(self) -> None:
        return None


def test_installed_gemini_usage_counts_are_bounded_and_provider_neutral() -> None:
    provider = GeminiProvider(
        GeminiConfig("secret-api-key", "gemini-test-model", 10.0),
        client=_Client(),
    )
    result = asyncio.run(
        provider.generate_structured(
            StructuredGenerationRequest(
                prompt_version="test",
                system_instruction="extract",
                user_content="untrusted source",
                response_schema={"type": "object"},
            )
        )
    )
    assert result.payload == {"value": "ok"}
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.total_tokens == 18


def test_provider_failure_event_is_bounded_and_redacts_provider_exception(caplog: object) -> None:
    class FailingInteractions:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            del kwargs
            raise RuntimeError("PROVIDER_RESPONSE_SECRET_SENTINEL")

    class FailingAsyncClient:
        interactions = FailingInteractions()

    class FailingClient:
        aio = FailingAsyncClient()

        def close(self) -> None:
            return None

    observer = Observability({"gemini": "CONFIGURED"})
    token = set_observability(observer)
    logger = logging.getLogger("opsflow.observability")
    handler = logging.Handler()
    messages: list[str] = []
    handler.emit = lambda record: messages.append(record.getMessage())  # type: ignore[method-assign]
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        provider = GeminiProvider(
            GeminiConfig("secret-api-key", "gemini-test-model", 10.0),
            client=FailingClient(),
        )
        with pytest.raises(ProviderError):
            asyncio.run(
                provider.generate_structured(
                    StructuredGenerationRequest(
                        prompt_version="test",
                        system_instruction="extract",
                        user_content="SOURCE_SECRET_SENTINEL",
                        response_schema={"type": "object"},
                    )
                )
            )
    finally:
        logger.removeHandler(handler)
        reset_observability(token)

    assert messages
    assert "PROVIDER_RESPONSE_SECRET_SENTINEL" not in "".join(messages)
    assert "SOURCE_SECRET_SENTINEL" not in "".join(messages)
    assert "PROVIDER_ERROR" in messages[-1]
    assert observer.integrations.snapshot()["gemini"]["observation"] == "UNAVAILABLE"

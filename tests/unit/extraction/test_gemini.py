import asyncio
from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace

import httpx
import pytest

from opsflow.extraction.errors import ProviderError, ProviderTimeoutError
from opsflow.extraction.gemini import GeminiConfig, GeminiProvider
from opsflow.extraction.provider import StructuredGenerationRequest


class _FakeInteractions:
    def __init__(self, *, output_text: str = '{"value": "ok"}', error: Exception | None = None):
        self.output_text = output_text
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output_text=self.output_text)


class _FakeAsyncClient:
    def __init__(self, interactions: _FakeInteractions):
        self.interactions = interactions
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, async_client: _FakeAsyncClient, http_options: object | None = None):
        self.aio = async_client
        self._api_client = SimpleNamespace(_http_options=http_options)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _request() -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        prompt_version="phase4-extraction-v1",
        system_instruction="extract only",
        user_content="SOURCE_CONTENT_BEGIN\nPO-1\nSOURCE_CONTENT_END",
        response_schema={"type": "object", "additionalProperties": False},
    )


def test_gemini_config_is_frozen_slotted_and_hides_api_key() -> None:
    config = GeminiConfig(
        api_key="secret-api-key",
        model="gemini-test-model",
        timeout_seconds=12.5,
    )

    assert not hasattr(config, "__dict__")
    assert [field.name for field in fields(config)] == [
        "api_key",
        "model",
        "timeout_seconds",
    ]
    assert "secret-api-key" not in repr(config)

    with pytest.raises(FrozenInstanceError):
        config.model = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("api_key", "model", "timeout_seconds"),
    [
        ("", "gemini-test-model", 10.0),
        ("   ", "gemini-test-model", 10.0),
        ("secret-api-key", "", 10.0),
        ("secret-api-key", "   ", 10.0),
        ("secret-api-key", "gemini-test-model", 0.0),
        ("secret-api-key", "gemini-test-model", -1.0),
        ("secret-api-key", "gemini-test-model", float("inf")),
        ("secret-api-key", "gemini-test-model", float("nan")),
    ],
)
def test_gemini_config_rejects_invalid_values_without_echoing_key(
    api_key: str,
    model: str,
    timeout_seconds: float,
) -> None:
    with pytest.raises(ValueError) as raised:
        GeminiConfig(api_key=api_key, model=model, timeout_seconds=timeout_seconds)

    assert "secret-api-key" not in str(raised.value)


def test_provider_maps_one_stateless_structured_request_and_returns_json_payload() -> None:
    interactions = _FakeInteractions(output_text='{"customer_name": null}')
    provider = GeminiProvider(
        GeminiConfig("secret-api-key", "gemini-test-model", 12.5),
        client=_FakeClient(_FakeAsyncClient(interactions)),
    )

    result = asyncio.run(provider.generate_structured(_request()))

    assert result.payload == {"customer_name": None}
    assert len(interactions.calls) == 1
    call = interactions.calls[0]
    assert call["model"] == "gemini-test-model"
    assert call["system_instruction"] == "extract only"
    assert call["input"] == "SOURCE_CONTENT_BEGIN\nPO-1\nSOURCE_CONTENT_END"
    assert call["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": {"type": "object", "additionalProperties": False},
    }
    assert call["store"] is False
    assert call["timeout"] == 12.5
    assert "previous_interaction_id" not in call
    assert "tools" not in call
    assert "background" not in call
    assert "stream" not in call


def test_provider_uses_only_output_text_and_does_not_return_sdk_object() -> None:
    interactions = _FakeInteractions(output_text='{"value": 7}')
    provider = GeminiProvider(
        GeminiConfig("secret-api-key", "gemini-test-model", 10.0),
        client=_FakeClient(_FakeAsyncClient(interactions)),
    )

    result = asyncio.run(provider.generate_structured(_request()))

    assert result.payload == {"value": 7}
    assert not isinstance(result.payload, SimpleNamespace)


def test_provider_rejects_malformed_json_without_raw_output_or_source() -> None:
    secret = "secret-api-key raw-order-content"
    interactions = _FakeInteractions(output_text=f"not-json {secret}")
    provider = GeminiProvider(
        GeminiConfig("secret-api-key", "gemini-test-model", 10.0),
        client=_FakeClient(_FakeAsyncClient(interactions)),
    )

    with pytest.raises(ProviderError) as raised:
        asyncio.run(provider.generate_structured(_request()))

    message = str(raised.value)
    assert "invalid JSON" in message
    assert secret not in message
    assert "raw-order-content" not in message


@pytest.mark.parametrize("error", [RuntimeError("provider secret-api-key failure")])
def test_provider_maps_sdk_failures_to_safe_provider_errors(error: Exception) -> None:
    interactions = _FakeInteractions(error=error)
    provider = GeminiProvider(
        GeminiConfig("secret-api-key", "gemini-test-model", 10.0),
        client=_FakeClient(_FakeAsyncClient(interactions)),
    )

    with pytest.raises(ProviderError) as raised:
        asyncio.run(provider.generate_structured(_request()))

    assert str(raised.value) == "Gemini provider request failed"
    assert "secret-api-key" not in str(raised.value)


@pytest.mark.parametrize(
    "error",
    [TimeoutError("provider secret-api-key timeout"), httpx.ReadTimeout("timeout")],
)
def test_provider_maps_timeout_failures_to_provider_timeout(error: Exception) -> None:
    interactions = _FakeInteractions(error=error)
    provider = GeminiProvider(
        GeminiConfig("secret-api-key", "gemini-test-model", 10.0),
        client=_FakeClient(_FakeAsyncClient(interactions)),
    )

    with pytest.raises(ProviderTimeoutError) as raised:
        asyncio.run(provider.generate_structured(_request()))

    assert str(raised.value) == "Gemini provider request timed out"
    assert "secret-api-key" not in str(raised.value)


def test_provider_maps_current_sdk_wrapped_timeout_to_provider_timeout() -> None:
    from google.genai._gaos.lib import compat_errors

    request = httpx.Request("POST", "https://example.test")
    wrapped_timeout = compat_errors.wrap_sdk_error(
        httpx.ReadTimeout("provider timeout", request=request)
    )
    assert isinstance(wrapped_timeout, compat_errors.APITimeoutError)

    interactions = _FakeInteractions(error=wrapped_timeout)
    provider = GeminiProvider(
        GeminiConfig("secret-api-key", "gemini-test-model", 10.0),
        client=_FakeClient(_FakeAsyncClient(interactions)),
    )

    with pytest.raises(ProviderTimeoutError) as raised:
        asyncio.run(provider.generate_structured(_request()))

    assert str(raised.value) == "Gemini provider request timed out"
    assert "provider timeout" not in str(raised.value)


def test_owned_client_receives_explicit_key_and_zero_retry_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opsflow.extraction import gemini as gemini_module

    interactions = _FakeInteractions()
    async_client = _FakeAsyncClient(interactions)
    captured: dict[str, object] = {}
    created: list[_FakeClient] = []

    def fake_client(**kwargs: object) -> _FakeClient:
        captured.update(kwargs)
        client = _FakeClient(async_client, kwargs["http_options"])
        created.append(client)
        return client

    monkeypatch.setattr(gemini_module.genai, "Client", fake_client)
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-secret")
    monkeypatch.setenv("GOOGLE_API_KEY", "other-ambient-secret")

    provider = GeminiProvider(GeminiConfig("explicit-secret", "gemini-test-model", 10.0))

    asyncio.run(provider.generate_structured(_request()))

    assert captured["api_key"] == "explicit-secret"
    http_options = captured["http_options"]
    retry_options = http_options.retry_options  # type: ignore[union-attr]
    assert retry_options.attempts == 0
    assert async_client.closed is True
    assert created[0].closed is True
    assert len(interactions.calls) == 1


@pytest.mark.parametrize(
    ("output_text", "error"),
    [
        ('{"value": "ok"}', None),
        ("not-json", None),
        ('{"value": "ignored"}', RuntimeError("provider failure")),
    ],
)
def test_owned_client_closes_both_sides_on_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    output_text: str,
    error: Exception | None,
) -> None:
    from opsflow.extraction import gemini as gemini_module

    interactions = _FakeInteractions(output_text=output_text, error=error)
    async_client = _FakeAsyncClient(interactions)
    created: list[_FakeClient] = []

    def fake_client(**kwargs: object) -> _FakeClient:
        client = _FakeClient(async_client, kwargs["http_options"])
        created.append(client)
        return client

    monkeypatch.setattr(gemini_module.genai, "Client", fake_client)
    provider = GeminiProvider(GeminiConfig("explicit-secret", "gemini-test-model", 10.0))

    if error is not None or output_text == "not-json":
        with pytest.raises(ProviderError):
            asyncio.run(provider.generate_structured(_request()))
    else:
        asyncio.run(provider.generate_structured(_request()))

    assert async_client.closed is True
    assert created[0].closed is True


def test_injected_client_remains_caller_owned() -> None:
    async_client = _FakeAsyncClient(_FakeInteractions())
    root_client = _FakeClient(async_client)
    provider = GeminiProvider(
        GeminiConfig("explicit-secret", "gemini-test-model", 10.0),
        client=root_client,
    )

    asyncio.run(provider.generate_structured(_request()))

    assert async_client.closed is False
    assert root_client.closed is False


def test_actual_sdk_retry_bridge_consumes_zero_interactions_retries() -> None:
    from opsflow.extraction.gemini import _create_client

    client = _create_client(GeminiConfig("synthetic-test-key", "gemini-test-model", 10.0))
    async_client = None
    try:
        retry_options = client._api_client._http_options.retry_options
        assert retry_options is not None
        assert retry_options.attempts == 0

        async_client = client.aio
        interactions = async_client.interactions
        assert interactions.sdk_configuration.retry_config.max_retries == 0
    finally:
        if async_client is not None:
            asyncio.run(async_client.aclose())
        client.close()


def test_settings_remain_constructible_without_gemini_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opsflow.settings import Settings

    monkeypatch.delenv("OPSFLOW_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPSFLOW_GEMINI_MODEL", raising=False)
    monkeypatch.delenv("OPSFLOW_GEMINI_TIMEOUT_SECONDS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.gemini_api_key is None
    assert settings.gemini_model is None
    assert settings.gemini_timeout_seconds is None

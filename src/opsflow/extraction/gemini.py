"""Isolated Google Gemini structured-generation provider adapter."""

import json
import math
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from google import genai
from google.genai import types
from google.genai.errors import ServerError

from opsflow.extraction.errors import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from opsflow.extraction.provider import (
    LLMProvider,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from opsflow.observability.runtime import current_observability, duration_ms


@dataclass(frozen=True, slots=True)
class GeminiConfig:
    """Validated configuration for one optional Gemini provider."""

    api_key: str = field(repr=False)
    model: str
    timeout_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ValueError("Gemini API key is required")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Gemini model is required")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Gemini timeout must be finite and positive")


def _create_client(config: GeminiConfig) -> genai.Client:
    """Create a one-shot SDK client with Interactions retries disabled."""

    http_options = types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=0),
    )
    client = genai.Client(api_key=config.api_key, http_options=http_options)

    # google-genai 2.24.0 normalizes attempts=0 to 1 while building the
    # parent client. The Interactions bridge is lazy and treats this value as
    # max retries after the initial request, so restore zero before aio is read.
    sdk_client = cast(Any, client)
    retry_options = sdk_client._api_client._http_options.retry_options
    if retry_options is None:
        raise RuntimeError("Gemini retry configuration unavailable")
    retry_options.attempts = 0
    return client


def _is_timeout_error(exc: BaseException) -> bool:
    """Recognize direct and SDK-wrapped timeout exceptions safely."""

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, httpx.TimeoutException)):
            return True
        current = current.__cause__ or current.__context__
    return False


class GeminiProvider(LLMProvider):
    """Translate one provider-neutral request into one stateless Gemini call."""

    def __init__(self, config: GeminiConfig, client: object | None = None) -> None:
        self._config = config
        self._client = client

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        root_client = self._client
        owns_client = root_client is None
        async_client: object | None = None
        started_ns = time.perf_counter_ns()
        usage: tuple[int | None, int | None, int | None] = (None, None, None)
        failure_code: str | None = None

        try:
            if root_client is None:
                root_client = _create_client(self._config)
            async_client = getattr(root_client, "aio", root_client)
            interactions = cast(Any, async_client).interactions
            interaction = await interactions.create(
                model=self._config.model,
                system_instruction=request.system_instruction,
                input=request.user_content,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": dict(request.response_schema),
                },
                store=False,
                timeout=self._config.timeout_seconds,
            )
            output_text = getattr(interaction, "output_text", None)
            if not isinstance(output_text, str):
                raise ProviderError("Gemini provider response did not contain text")
            try:
                payload = json.loads(output_text)
            except json.JSONDecodeError as exc:
                raise ProviderError("Gemini provider returned invalid JSON") from exc
            usage = _usage_counts(interaction)
            return StructuredGenerationResult(
                payload=payload,
                input_tokens=usage[0],
                output_tokens=usage[1],
                total_tokens=usage[2],
            )
        except ProviderError:
            failure_code = "PROVIDER_ERROR"
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            failure_code = "PROVIDER_TIMEOUT"
            raise ProviderTimeoutError("Gemini provider request timed out") from exc
        except ServerError as exc:
            if _is_timeout_error(exc):
                failure_code = "PROVIDER_TIMEOUT"
                raise ProviderTimeoutError("Gemini provider request timed out") from exc
            failure_code = "PROVIDER_UNAVAILABLE"
            raise ProviderUnavailableError("Gemini provider is unavailable") from exc
        except Exception as exc:
            if _is_timeout_error(exc):
                failure_code = "PROVIDER_TIMEOUT"
                raise ProviderTimeoutError("Gemini provider request timed out") from exc
            failure_code = "PROVIDER_ERROR"
            raise ProviderError("Gemini provider request failed") from exc
        finally:
            observer = current_observability()
            if observer is not None:
                with suppress(Exception):
                    observer.provider_completed(
                        provider="gemini",
                        operation="structured_generation",
                        success=failure_code is None,
                        duration_ms=duration_ms(started_ns),
                        failure_code=failure_code,
                        input_tokens=usage[0],
                        output_tokens=usage[1],
                        total_tokens=usage[2],
                    )
            if owns_client:
                if async_client is not None:
                    async_close = getattr(async_client, "aclose", None)
                    if async_close is not None:
                        with suppress(Exception):
                            await async_close()

                if root_client is not None:
                    sync_close = getattr(root_client, "close", None)
                    if sync_close is not None:
                        with suppress(Exception):
                            sync_close()


def _usage_counts(interaction: object) -> tuple[int | None, int | None, int | None]:
    """Read only authoritative non-negative counts from google-genai 2.24.0."""

    usage = getattr(interaction, "usage", None)
    values: list[int | None] = []
    for field_name in ("total_input_tokens", "total_output_tokens", "total_tokens"):
        value = getattr(usage, field_name, None)
        values.append(value if type(value) is int and value >= 0 else None)
    return values[0], values[1], values[2]


__all__ = ["GeminiConfig", "GeminiProvider"]

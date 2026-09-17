"""Isolated Google Gemini structured-generation provider adapter."""

import json
import math
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
from google import genai
from google.genai import types

from opsflow.extraction.errors import ProviderError, ProviderTimeoutError
from opsflow.extraction.provider import (
    LLMProvider,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)


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
            return StructuredGenerationResult(payload=payload)
        except ProviderError:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderTimeoutError("Gemini provider request timed out") from exc
        except Exception as exc:
            if _is_timeout_error(exc):
                raise ProviderTimeoutError("Gemini provider request timed out") from exc
            raise ProviderError("Gemini provider request failed") from exc
        finally:
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


__all__ = ["GeminiConfig", "GeminiProvider"]

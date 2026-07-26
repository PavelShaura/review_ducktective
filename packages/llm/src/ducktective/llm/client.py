import time
from typing import (
    Any,
)

import litellm
from litellm.exceptions import (
    APIError,
    RateLimitError,
    Timeout,
)

from ducktective.core.exceptions import (
    LlmInvocationError,
)
from ducktective.core.llm.ports import (
    LlmResponseCache,
)
from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmUsage,
    ModelRequirements,
)
from ducktective.llm.cache import (
    build_cache_key,
)
from ducktective.llm.router import (
    ModelRouter,
)


RETRYABLE_ERRORS = (RateLimitError, Timeout, APIError)


class LiteLlmClient:
    """Единая точка обращения к моделям поверх LiteLLM.

    Выбор провайдера делегирован роутеру, поэтому вызывающий код не знает,
    ушёл ли запрос в локальную модель или во внешний сервис.
    """

    def __init__(
        self,
        router: ModelRouter,
        *,
        cache: LlmResponseCache | None = None,
        prompt_version: str = "v1",
        timeout_seconds: float = 180.0,
        max_attempts: int = 3,
    ) -> None:
        self._router = router
        self._cache = cache
        self._prompt_version = prompt_version
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        choice = self._router.select(requirements)
        cache_key = build_cache_key(
            model=choice.model,
            messages=messages,
            requirements=requirements,
            prompt_version=self._prompt_version,
        )

        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        response = await self._invoke(choice, messages, requirements, json_schema)

        if self._cache is not None:
            await self._cache.put(cache_key, response)
        return response

    async def _invoke(
        self,
        choice: Any,
        messages: list[LlmMessage],
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None,
    ) -> LlmResponse:
        payload: dict[str, Any] = {
            "model": choice.model,
            "messages": [
                {"role": message.role.value, "content": message.content} for message in messages
            ],
            "temperature": requirements.temperature,
            "max_tokens": requirements.max_output_tokens,
            "timeout": self._timeout_seconds,
        }
        if choice.api_base:
            payload["api_base"] = choice.api_base
        if choice.api_key:
            payload["api_key"] = choice.api_key
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "review", "schema": json_schema, "strict": False},
            }

        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            started_at = time.monotonic()
            try:
                completion = await litellm.acompletion(**payload)
            except RETRYABLE_ERRORS as error:
                last_error = error
                if attempt == self._max_attempts:
                    break
                continue
            except Exception as error:
                raise LlmInvocationError(
                    f"Модель {choice.model} вернула ошибку: {error}"
                ) from error

            latency_ms = int((time.monotonic() - started_at) * 1000)
            return _build_response(completion, choice, latency_ms)

        raise LlmInvocationError(
            f"Модель {choice.model} недоступна после {self._max_attempts} попыток: {last_error}"
        )


def _build_response(completion: Any, choice: Any, latency_ms: int) -> LlmResponse:
    content = completion.choices[0].message.content or ""
    usage = getattr(completion, "usage", None)

    return LlmResponse(
        content=content,
        model=choice.model,
        provider=choice.provider,
        usage=LlmUsage(
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            cost_usd=_estimate_cost(completion),
        ),
        latency_ms=latency_ms,
    )


def _estimate_cost(completion: Any) -> float:
    """Стоимость известна не для всех моделей: у локальных её нет вовсе."""
    try:
        return float(litellm.completion_cost(completion_response=completion))
    except Exception:
        return 0.0

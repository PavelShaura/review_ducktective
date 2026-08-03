import asyncio
import re
import time
from typing import (
    Any,
)

import litellm
from litellm.exceptions import (
    APIError,
    ContextWindowExceededError,
    RateLimitError,
    Timeout,
)

from ducktective.core.exceptions import (
    LlmContextOverflowError,
    LlmInvocationError,
    LlmRateLimitError,
    LlmTimeoutError,
    LlmUnavailableError,
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
RETRY_BACKOFF_SECONDS = 1.0
PROMPT_TOKENS_PATTERN = re.compile(r'"n_prompt_tokens"\s*:\s*(\d+)')
CONTEXT_SIZE_PATTERN = re.compile(r'"n_ctx"\s*:\s*(\d+)')


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
        """Ответ модели, по возможности из кэша.

        Оборванный на лимите ответ в кэш не кладётся: он не разберётся ни
        сейчас, ни через неделю, а повторный прогон того же диффа получил бы
        из кэша тот же мусор вместо новой попытки.
        """
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

        if self._cache is not None and not response.is_truncated:
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
            except ContextWindowExceededError as error:
                raise _context_overflow_error(choice.model, error) from error
            except RETRYABLE_ERRORS as error:
                last_error = error
                if attempt == self._max_attempts:
                    break
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * 2 ** (attempt - 1))
                continue
            except Exception as error:
                raise LlmUnavailableError(
                    f"Модель {choice.model} вернула ошибку: {error}",
                    model=choice.model,
                ) from error

            latency_ms = int((time.monotonic() - started_at) * 1000)
            return _build_response(completion, choice, latency_ms)

        raise self._unavailable_error(choice.model, last_error)

    def _unavailable_error(self, model: str, last_error: Exception | None) -> LlmInvocationError:
        """Разделяет причины: они чинятся по-разному.

        Не ответившая вовремя модель требует другого таймаута или модели
        полегче, а недоступный сервер — вообще другого разбирательства.
        """
        if isinstance(last_error, Timeout):
            return LlmTimeoutError(
                f"Модель {model} не ответила за {self._timeout_seconds:.0f} с "
                f"({self._max_attempts} попыт.)",
                model=model,
            )

        if isinstance(last_error, RateLimitError):
            return LlmRateLimitError(
                f"Модель {model} ограничивает частоту запросов "
                f"({self._max_attempts} попыт.): {last_error}",
                model=model,
            )

        return LlmUnavailableError(
            f"Модель {model} недоступна после {self._max_attempts} попыток: {last_error}",
            model=model,
        )


def _context_overflow_error(model: str, error: Exception) -> LlmContextOverflowError:
    """Достаёт размеры из ответа сервера.

    Без цифр сообщение не подсказывает, что чинить: одно и то же переполнение
    лечится и увеличением окна модели, и сокращением контекста.
    """
    text = str(error)
    prompt_tokens = PROMPT_TOKENS_PATTERN.search(text)
    context_size = CONTEXT_SIZE_PATTERN.search(text)
    if prompt_tokens is None or context_size is None:
        return LlmContextOverflowError(
            f"Промпт не поместился в окно контекста модели {model}",
            model=model,
        )

    return LlmContextOverflowError(
        f"Промпт не поместился в окно контекста модели {model}: "
        f"{prompt_tokens.group(1)} токенов при окне {context_size.group(1)}",
        model=model,
    )


def _build_response(completion: Any, choice: Any, latency_ms: int) -> LlmResponse:
    choice_data = completion.choices[0]
    content = choice_data.message.content or ""
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
        is_truncated=getattr(choice_data, "finish_reason", None) == "length",
    )


def _estimate_cost(completion: Any) -> float:
    """Стоимость известна не для всех моделей: у локальных её нет вовсе."""
    try:
        return float(litellm.completion_cost(completion_response=completion))
    except Exception:
        return 0.0

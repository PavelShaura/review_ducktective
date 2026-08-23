import asyncio
import re
import time
from collections.abc import (
    AsyncIterator,
    Sequence,
)
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
    LlmRole,
    LlmStreamPiece,
    LlmUsage,
    ModelRequirements,
    ToolCall,
    ToolSpec,
)
from ducktective.llm.cache import (
    build_cache_key,
)
from ducktective.llm.router import (
    ModelRouter,
)


RETRYABLE_ERRORS = (RateLimitError, Timeout, APIError)
RETRY_BACKOFF_SECONDS = 1.0
RATE_LIMIT_COOLDOWN_SECONDS = 300.0
"""Сколько исчерпавшая лимит модель не спрашивается снова.

Пять минут — компромисс: минутные лимиты за это время восстанавливаются,
суточные нет, и пробовать их повторно каждые несколько секунд бессмысленно.
Слишком долгий срок держал бы разговор на запасной модели дольше нужного.
"""

FAILURE_COOLDOWN_SECONDS = 60.0
"""Отказавший провайдер отдыхает меньше: сеть чинится быстрее лимита."""
PROMPT_TOKENS_PATTERN = re.compile(r'"n_prompt_tokens"\s*:\s*(\d+)')
CONTEXT_SIZE_PATTERN = re.compile(r'"n_ctx"\s*:\s*(\d+)')
CONTEXT_OVERFLOW_MARKERS = (
    "context size has been exceeded",
    "exceed_context_size_error",
    "exceeds the available context size",
    "context window",
    "context length",
    "maximum context",
)


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
        self._cooling: dict[str, float] = {}

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[ToolSpec] | None = None,
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
            tools=tools,
        )

        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return cached

        response = await self._invoke(choice, messages, requirements, json_schema, tools)

        if self._cache is not None and not response.is_truncated:
            await self._cache.put(cache_key, response)
        return response

    async def stream(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncIterator[LlmStreamPiece]:
        """Ответ по мере появления; итог приходит последним куском.

        Отказ до первого куска и отказ посреди текста — разные события.
        В первом случае человеку ещё ничего не показано, и повторить можно
        безнаказанно: сперва той же моделью с паузой, затем — следующей
        по политике репозитория. Во втором повтор начал бы писать другой
        текст поверх начатого, поэтому поток честно обрывается.

        Замена модели здесь не роскошь: бесплатные тиры считают запросы,
        а цикл с инструментами тратит по обращению на шаг — вторая модель
        рядом заведена ровно для этой минуты (D-029).
        """
        first_choice = self._router.select(requirements)
        candidates = self._live_first(
            (
                first_choice,
                *self._router.alternatives(requirements, besides=first_choice),
            )
        )

        last_error: Exception | None = None
        last_refused = first_choice
        for position, choice in enumerate(candidates):
            if position:
                yield LlmStreamPiece(
                    notice=(
                        f"Модель {last_refused.name} не ответила "
                        f"({_short_reason(last_error)}). Дальше в этом ответе "
                        f"отвечает {choice.name}"
                    )
                )

            started_at = time.monotonic()
            collected = _StreamCollector()
            has_text = False

            try:
                async for piece in self._stream_once(
                    choice, messages, requirements, tools, collected
                ):
                    has_text = True
                    yield piece
            except ContextWindowExceededError as error:
                raise _context_overflow_error(choice.model, error) from error
            except Exception as error:
                if _mentions_context_overflow(str(error)):
                    raise _context_overflow_error(choice.model, error) from error
                if has_text:
                    raise self._stream_error(choice.model, error) from error

                last_error = error
                last_refused = choice
                self._start_cooldown(choice.name, error)
                continue

            latency_ms = int((time.monotonic() - started_at) * 1000)
            yield LlmStreamPiece(response=collected.finish(choice, latency_ms))
            return

        raise self._stream_error(last_refused.model, last_error)

    async def _stream_once(
        self,
        choice: Any,
        messages: list[LlmMessage],
        requirements: ModelRequirements,
        tools: Sequence[ToolSpec] | None,
        collected: "_StreamCollector",
    ) -> AsyncIterator[LlmStreamPiece]:
        """Одна попытка одной модели.

        Собственные повторы библиотеки выключены: они молча тратят секунды
        на модель, которую мы и так готовы заменить следующей, и в журнале
        выглядят как зависание.
        """
        payload = self._payload(choice, messages, requirements, None, tools)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        payload["num_retries"] = 0

        async for chunk in await litellm.acompletion(**payload):
            text = collected.absorb(chunk)
            if text:
                yield LlmStreamPiece(text=text)

    def _live_first(self, candidates: Sequence[Any]) -> tuple[Any, ...]:
        """Ставит вперёд тех, кто не отдыхает после недавнего отказа.

        Цикл с инструментами тратит по обращению на шаг, и без этого каждый
        шаг заново стучался бы в исчерпанную модель, дожидаясь её отказа.
        Отдыхающие не выбрасываются совсем: если живых не осталось, попытка
        всё равно лучше отказа.
        """
        now = time.monotonic()
        live = [choice for choice in candidates if self._cooling.get(choice.name, 0.0) <= now]
        resting = [choice for choice in candidates if self._cooling.get(choice.name, 0.0) > now]
        return (*live, *resting)

    def _start_cooldown(self, name: str, error: Exception) -> None:
        seconds = (
            RATE_LIMIT_COOLDOWN_SECONDS
            if isinstance(error, RateLimitError)
            else FAILURE_COOLDOWN_SECONDS
        )
        self._cooling[name] = time.monotonic() + seconds

    @staticmethod
    def _stream_error(model: str, error: Exception | None) -> LlmInvocationError:
        """Называет причину так, чтобы по ней было понятно, что делать.

        Исчерпанный лимит — не поломка модели: он проходит сам или лечится
        другой моделью, и сказать об этом надо человеку, а не показывать
        ему исключение библиотеки.
        """
        if isinstance(error, RateLimitError):
            return LlmRateLimitError(
                f"Модель {model} исчерпала лимит запросов. Бесплатные тиры считают "
                "обращения, а разговор тратит по одному на каждый шаг поиска: "
                "выберите другую модель в списке или повторите позже",
                model=model,
            )
        return LlmUnavailableError(
            f"Модель {model} прервала ответ: {error}",
            model=model,
        )

    def _payload(
        self,
        choice: Any,
        messages: list[LlmMessage],
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None,
        tools: Sequence[ToolSpec] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": choice.model,
            "messages": [_to_wire(message) for message in messages],
            "temperature": requirements.temperature,
            "max_tokens": requirements.max_output_tokens,
            "timeout": self._timeout_seconds,
        }
        if choice.api_base:
            payload["api_base"] = choice.api_base
        if choice.api_key:
            payload["api_key"] = choice.api_key
        if tools:
            payload["tools"] = [_tool_to_wire(tool) for tool in tools]
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "review", "schema": json_schema, "strict": False},
            }
        return payload

    async def _invoke(
        self,
        choice: Any,
        messages: list[LlmMessage],
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None,
        tools: Sequence[ToolSpec] | None = None,
    ) -> LlmResponse:
        payload = self._payload(choice, messages, requirements, json_schema, tools)

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
                if _mentions_context_overflow(str(error)):
                    raise _context_overflow_error(choice.model, error) from error
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


def _short_reason(error: Exception | None) -> str:
    """Причина отказа в двух словах — она едет человеку, а не в журнал."""
    if isinstance(error, RateLimitError):
        return "исчерпан лимит запросов"
    if isinstance(error, Timeout):
        return "не дождались ответа"
    return "провайдер отказал"


def _to_wire(message: LlmMessage) -> dict[str, Any]:
    """Переводит сообщение в формат протокола.

    Ответ ассистента с вызовами приходится возвращать модели тем же составом,
    каким она его прислала: провайдер сверяет пары «вызов — результат» и
    отвергает диалог, где результат отвечает на вызов, которого в переписке
    нет.
    """
    wire: dict[str, Any] = {"role": message.role.value, "content": message.content}

    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]

    if message.role is LlmRole.TOOL and message.tool_call_id is not None:
        wire["tool_call_id"] = message.tool_call_id

    return wire


def _tool_to_wire(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


class _StreamCollector:
    """Собирает ответ из приращений.

    Текст приходит кусками, а вызовы инструментов — по частям: имя в одном
    приращении, аргументы по буквам в следующих, и связывает их порядковый
    номер, а не идентификатор. Поэтому вызовы копятся по индексу и становятся
    ответом только в конце.

    Расход токенов приходит отдельным куском в самом хвосте и только если
    сервер согласился его прислать: у локальных сборок это не гарантировано,
    и тогда счётчики остаются нулевыми — соврать было бы хуже.
    """

    def __init__(self) -> None:
        self._text: list[str] = []
        self._calls: dict[int, dict[str, str]] = {}
        self._finish_reason: str | None = None
        self._usage: LlmUsage = LlmUsage()

    def absorb(self, chunk: Any) -> str:
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self._usage = LlmUsage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )

        choices = getattr(chunk, "choices", None) or ()
        if not choices:
            return ""

        first = choices[0]
        self._finish_reason = getattr(first, "finish_reason", None) or self._finish_reason

        delta = getattr(first, "delta", None)
        if delta is None:
            return ""

        self._absorb_tool_calls(delta)
        text = getattr(delta, "content", None) or ""
        if text:
            self._text.append(text)
        return str(text)

    def finish(self, choice: Any, latency_ms: int) -> LlmResponse:
        return LlmResponse(
            content="".join(self._text),
            model=choice.model,
            provider=choice.provider,
            usage=self._usage,
            latency_ms=latency_ms,
            is_truncated=self._finish_reason == "length",
            tool_calls=tuple(
                ToolCall(
                    id=call.get("id") or f"call_{index}",
                    name=call.get("name", ""),
                    arguments=call.get("arguments") or "{}",
                )
                for index, call in sorted(self._calls.items())
                if call.get("name")
            ),
        )

    def _absorb_tool_calls(self, delta: Any) -> None:
        for position, raw in enumerate(getattr(delta, "tool_calls", None) or ()):
            index = getattr(raw, "index", None)
            index = position if index is None else int(index)
            call = self._calls.setdefault(index, {"id": "", "name": "", "arguments": ""})

            identifier = getattr(raw, "id", None)
            if identifier:
                call["id"] = str(identifier)

            function = getattr(raw, "function", None)
            if function is None:
                continue

            name = getattr(function, "name", None)
            if name:
                call["name"] = str(name)

            arguments = getattr(function, "arguments", None)
            if arguments:
                call["arguments"] += str(arguments)


def _read_tool_calls(message: Any) -> tuple[ToolCall, ...]:
    """Достаёт вызовы из ответа.

    Аргументы не разбираются: их валидность — забота того, кто исполняет
    вызов, и неразобранный JSON должен вернуться модели ошибкой, а не
    уронить обращение к ней.
    """
    raw_calls = getattr(message, "tool_calls", None) or ()
    calls = []
    for index, raw in enumerate(raw_calls):
        function = getattr(raw, "function", None)
        if function is None:
            continue
        calls.append(
            ToolCall(
                id=getattr(raw, "id", None) or f"call_{index}",
                name=getattr(function, "name", "") or "",
                arguments=getattr(function, "arguments", None) or "{}",
            )
        )
    return tuple(calls)


def _mentions_context_overflow(text: str) -> bool:
    """Узнаёт переполнение окна по словам сервера.

    Тип исключения тут не помощник: LM Studio отдаёт переполнение обычным
    `BadRequestError`, litellm его в `ContextWindowExceededError` не переводит,
    и переполнение приезжает неотличимым от «провайдер отказал». Разница
    важна человеку: одно чинится окном модели, другое — разбирательством
    с сервисом, и совет в интерфейсе выбирается по виду причины.
    """
    lowered = text.lower()
    return any(marker in lowered for marker in CONTEXT_OVERFLOW_MARKERS)


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
        tool_calls=_read_tool_calls(choice_data.message),
    )


def _estimate_cost(completion: Any) -> float:
    """Стоимость известна не для всех моделей: у локальных её нет вовсе."""
    try:
        return float(litellm.completion_cost(completion_response=completion))
    except Exception:
        return 0.0

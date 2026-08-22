from collections.abc import (
    AsyncIterator,
    Sequence,
)
from typing import (
    Any,
    Protocol,
)

from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
    LlmStreamPiece,
    ModelRequirements,
    ToolSpec,
)


class LlmClient(Protocol):
    """Единственный выход к языковым моделям.

    Вызовы выполняются вне открытой транзакции: ответ может занимать десятки
    секунд.
    """

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        json_schema: dict[str, Any] | None = None,
        tools: Sequence[ToolSpec] | None = None,
    ) -> LlmResponse:
        """Ответ модели; при переданных инструментах — возможно, просьба вызвать.

        Инструменты и схема ответа задаются вместе только на последнем шаге
        цикла, где ответ вынуждается структурированным: в остальных случаях
        схема лишает модель права попросить инструмент.
        """
        ...


class StreamingLlmClient(LlmClient, Protocol):
    """Клиент, умеющий отдавать ответ по мере появления.

    Отдельный порт, а не метод в общем: ревью потоком не пользуется — там
    ответ разбирается целиком и по частям бесполезен, — и требовать его
    от каждой реализации значило бы требовать несуществующей надобности.

    Кэш в потоке не участвует: смысл потока в том, чтобы показывать работу
    по ходу, а отданный из кэша ответ показывать по ходу нечего.
    """

    def stream(
        self,
        messages: list[LlmMessage],
        *,
        requirements: ModelRequirements,
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncIterator[LlmStreamPiece]:
        """Ответ кусками; итог приходит последним и единственный раз."""
        ...


class LlmResponseCache(Protocol):
    """Кэш ответов модели по содержимому запроса."""

    async def get(self, cache_key: str) -> LlmResponse | None: ...

    async def put(self, cache_key: str, response: LlmResponse) -> None: ...

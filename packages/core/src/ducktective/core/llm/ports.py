from collections.abc import (
    Sequence,
)
from typing import (
    Any,
    Protocol,
)

from ducktective.core.llm.value_objects import (
    LlmMessage,
    LlmResponse,
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


class LlmResponseCache(Protocol):
    """Кэш ответов модели по содержимому запроса."""

    async def get(self, cache_key: str) -> LlmResponse | None: ...

    async def put(self, cache_key: str, response: LlmResponse) -> None: ...

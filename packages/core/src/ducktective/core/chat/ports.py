from collections.abc import (
    AsyncIterator,
)
from dataclasses import (
    dataclass,
)
from typing import (
    Protocol,
)

from ducktective.core.chat.entities import (
    AttachedDocument,
    ChatMessage,
    Conversation,
)
from ducktective.core.chat.value_objects import (
    ChatEvent,
)
from ducktective.core.llm.value_objects import (
    ModelRequirements,
)
from ducktective.core.retrieval.navigation import (
    CodeNavigator,
)
from ducktective.core.types import (
    CommitSha,
    ConversationId,
    RepositoryId,
    TenantId,
)


class ConversationRepository(Protocol):
    """Доступ к агрегату Conversation. Транзакцию не фиксирует."""

    def add(self, conversation: Conversation) -> None: ...

    async def get(self, conversation_id: ConversationId) -> Conversation: ...

    async def list_for_repository(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[Conversation]: ...

    async def remove(self, conversation: Conversation) -> None: ...


@dataclass(frozen=True, kw_only=True)
class ChatRequest:
    """Что нужно агенту, чтобы ответить на вопрос.

    История приходит целиком, а укладывает её в окно сам агент: сколько
    реплик поместится, зависит от модели и от того, сколько места займут
    результаты инструментов, — а это знает он, а не use case.
    """

    repository_id: RepositoryId
    question: str
    history: tuple[ChatMessage, ...] = ()
    requirements: ModelRequirements
    navigator: CodeNavigator | None = None
    index_revision: CommitSha | None = None
    document: AttachedDocument | None = None
    """Документ, приложенный к разговору.

    Едет целиком, а в подсказку попадает кусками: отбирает их агент под
    вопрос, потому что знает, сколько места осталось в окне (D-025).
    """


class ChatAgent(Protocol):
    """Отвечает на вопрос о коде, добывая сведения сам.

    Ответ отдаётся потоком: разговор пишется на экране по мере того, как
    модель его составляет, а вызовы инструментов видны в момент вызова,
    а не задним числом. Ждать ответа целиком нельзя — на локальной модели
    это десятки секунд молчания.
    """

    def answer(self, request: ChatRequest) -> AsyncIterator[ChatEvent]: ...

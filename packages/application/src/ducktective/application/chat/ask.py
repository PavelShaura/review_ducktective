from collections.abc import (
    AsyncGenerator,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.chat.manage import (
    ensure_own,
)
from ducktective.application.exceptions import (
    ApplicationError,
)
from ducktective.core.chat.entities import (
    Conversation,
)
from ducktective.core.chat.ports import (
    ChatAgent,
    ChatRequest,
)
from ducktective.core.chat.value_objects import (
    ChatEvent,
    ChatEventKind,
    ToolInvocation,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.llm.value_objects import (
    ModelRequirements,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.retrieval.navigation import (
    CodeNavigatorFactory,
)
from ducktective.core.types import (
    ConversationId,
    TenantId,
)


FINAL_KINDS = frozenset({ChatEventKind.ANSWER, ChatEventKind.FAILURE})
"""События, после которых разговору нечего добавить к этому вопросу."""


class IndexNotReadyError(ApplicationError):
    """Разговор идёт по индексу, а его ещё нет.

    Отдельная ошибка, а не пустой ответ: без индекса агенту нечем смотреть
    в код, и разговор выродился бы в беседу об общих представлениях о том,
    как такое обычно пишут. Человеку нужно сказать, что собрать индекс.
    """


class AskQuestion(TransactionalUseCase):
    """Проводит вопрос через агента и записывает разговор.

    Транзакций две, и между ними — работа с моделью, которая идёт минутами
    (D-016). Первая записывает вопрос: ответ может не случиться, а разговор,
    потерявший вопрос, выглядит так, будто его не задавали. Вторая
    записывает ответ вместе с тем, что агент посмотрел в кодовой базе.

    События отдаются наружу по мере появления: use case их не копит, потому
    что ждать ответа целиком — это и есть то, ради ухода от чего затевался
    поток.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        agent: ChatAgent,
        navigators: CodeNavigatorFactory,
        *,
        max_output_tokens: int = ModelRequirements().max_output_tokens,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._agent = agent
        self._navigators = navigators
        self._max_output_tokens = max_output_tokens

    async def execute(
        self,
        tenant_id: TenantId,
        conversation_id: ConversationId,
        question: str,
    ) -> AsyncGenerator[ChatEvent, None]:
        async with self._unit_of_work:
            conversation = await self._unit_of_work.conversations.get(conversation_id)
            ensure_own(conversation, tenant_id)

            repository = await self._unit_of_work.code_repositories.get(conversation.repository_id)
            snapshot = await self._unit_of_work.index_snapshots.find_latest_ready(
                conversation.repository_id
            )
            if snapshot is None:
                raise IndexNotReadyError(
                    f"Репозиторий «{repository.name}» не проиндексирован: "
                    f"соберите индекс, и разговор станет возможен"
                )

            conversation.ask(question)
            history = tuple(conversation.messages[:-1])
            await self._commit_and_publish()

        request = ChatRequest(
            repository_id=conversation.repository_id,
            question=question,
            history=history,
            requirements=ModelRequirements(
                needs_deep_reasoning=True,
                cloud_allowed=_cloud_allowed(repository, conversation),
                max_output_tokens=self._max_output_tokens,
            ),
            navigator=self._navigators.for_repository(conversation.repository_id),
            index_revision=snapshot.commit_sha,
            document=conversation.document,
        )

        return self._converse(conversation_id, tenant_id, request)

    async def _converse(
        self,
        conversation_id: ConversationId,
        tenant_id: TenantId,
        request: ChatRequest,
    ) -> AsyncGenerator[ChatEvent, None]:
        said: list[ChatEvent] = []
        is_recorded = False

        try:
            async for event in self._agent.answer(request):
                if event.kind is ChatEventKind.TOKEN:
                    yield event
                    continue

                said.append(event)
                if event.kind in FINAL_KINDS:
                    await self._record(conversation_id, tenant_id, said)
                    is_recorded = True

                yield event
        finally:
            if not is_recorded:
                await self._record(conversation_id, tenant_id, said)

    async def _record(
        self,
        conversation_id: ConversationId,
        tenant_id: TenantId,
        events: list[ChatEvent],
    ) -> None:
        """Записывает сказанное агентом.

        Итог пишется **до** того, как уходит клиенту, а не после: клиент,
        получив ответ, закрывает сокет, обработчик снимается вместе с ним,
        и запись, начатая после отправки, обрывается на первом же `await`.
        Проверено живым прогоном — второй ответ разговора терялся целиком.

        Незаконченный разговор дописывается в `finally`: человек закрыл
        страницу, модель отказала посреди ответа — то, что агент успел
        посмотреть, стоило работы, и терять его незачем. Эта попытка
        уже без гарантий: задача к тому моменту может быть снята.
        """
        if not events:
            return

        async with self._unit_of_work:
            conversation = await self._unit_of_work.conversations.get(conversation_id)
            ensure_own(conversation, tenant_id)
            _replay(conversation, events)
            await self._commit_and_publish()
        events.clear()


def _cloud_allowed(repository: CodeRepository, conversation: Conversation) -> bool:
    """Разрешено ли этому разговору уходить в облако.

    Приложенный документ ужесточает политику независимо от репозитория
    (D-025): `egress_policy` описывает код, а документ аналитика — не код,
    там сроки, фамилии и договорённости, и он часто чувствительнее того,
    к чему приложен.
    """
    return repository.cloud_processing_allowed and not conversation.has_document


def _replay(conversation: Conversation, events: list[ChatEvent]) -> None:
    """Переносит поток событий в реплики разговора."""
    pending: dict[str, ToolInvocation] = {}

    for event in events:
        if event.kind is ChatEventKind.TOOL_CALL and event.tool is not None:
            pending[event.tool.call_id] = event.tool
            conversation.record_tool_call((event.tool,))
        elif event.kind is ChatEventKind.TOOL_RESULT and event.tool is not None:
            invocation = pending.pop(event.tool.call_id, event.tool)
            conversation.record_tool_result(invocation, event.text)
        elif event.kind is ChatEventKind.ANSWER:
            conversation.record_answer(event.text, model=event.model, usage=event.usage)
        elif event.kind is ChatEventKind.FAILURE:
            conversation.record_answer(event.text)

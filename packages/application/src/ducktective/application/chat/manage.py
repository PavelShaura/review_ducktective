from dataclasses import (
    dataclass,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.chat.views import (
    ConversationView,
    DocumentView,
    MessageView,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.chat.documents import (
    plain_text,
)
from ducktective.core.chat.entities import (
    ChatMessage,
    Conversation,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.types import (
    ConversationId,
    RepositoryId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class StartedConversation:
    """Разговор, в котором предстоит спрашивать, и как он получен.

    Признак нужен интерфейсу: заведённый разговор просто открывается,
    а возвращённый прежний требует объяснения — человек нажал «новый»
    и вправе не понять, почему остался на месте.
    """

    conversation: ConversationView
    is_new: bool


class StartConversation(TransactionalUseCase):
    """Заводит разговор о репозитории — или возвращает уже пустой.

    Название не спрашивается: им становится первый вопрос. Просить человека
    придумать заголовок раньше, чем он задал вопрос, значит просить его
    угадать, о чём выйдет разговор.

    Второй пустой разговор не заводится. Разговор без единого вопроса ничем
    не отличается от такого же соседа, и нажатая дважды кнопка оставляла бы
    в списке вереницу «без вопроса», среди которых не выбрать нужный.
    """

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        *,
        preferred_model: str | None = None,
    ) -> StartedConversation:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            existing = await self._unit_of_work.conversations.list_for_repository(
                tenant_id,
                repository_id,
            )
            empty = next((item for item in existing if not item.messages), None)
            if empty is not None:
                return StartedConversation(conversation=to_view(empty), is_new=False)

            conversation = Conversation.start(
                tenant_id=tenant_id,
                repository_id=repository_id,
                preferred_model=preferred_model,
            )
            self._unit_of_work.conversations.add(conversation)
            await self._commit_and_publish()

        return StartedConversation(conversation=to_view(conversation), is_new=True)


class DeleteConversation(TransactionalUseCase):
    async def execute(self, tenant_id: TenantId, conversation_id: ConversationId) -> None:
        async with self._unit_of_work:
            conversation = await self._unit_of_work.conversations.get(conversation_id)
            ensure_own(conversation, tenant_id)

            await self._unit_of_work.conversations.remove(conversation)
            await self._commit_and_publish()


class AttachDocument(TransactionalUseCase):
    """Прикладывает документ к разговору.

    Текст приходит уже текстом: файл читает браузер, а сервер не принимает
    двоичного и не разбирает форматов (D-025). Разметка снимается здесь —
    выгрузка из Confluence приходит страницей HTML, и теги в подсказке
    занимают место, ничего не объясняя.
    """

    async def execute(
        self,
        tenant_id: TenantId,
        conversation_id: ConversationId,
        name: str,
        text: str,
    ) -> ConversationView:
        async with self._unit_of_work:
            conversation = await self._unit_of_work.conversations.get(conversation_id)
            ensure_own(conversation, tenant_id)

            conversation.attach(name, plain_text(text))
            await self._commit_and_publish()

        return to_view(conversation)


class DetachDocument(TransactionalUseCase):
    async def execute(
        self,
        tenant_id: TenantId,
        conversation_id: ConversationId,
    ) -> ConversationView:
        async with self._unit_of_work:
            conversation = await self._unit_of_work.conversations.get(conversation_id)
            ensure_own(conversation, tenant_id)

            conversation.detach()
            await self._commit_and_publish()

        return to_view(conversation)


class ListConversations:
    """Разговоры по репозиторию, свежие сверху."""

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[ConversationView]:
        async with self._unit_of_work:
            conversations = await self._unit_of_work.conversations.list_for_repository(
                tenant_id,
                repository_id,
                limit=limit,
            )
            return [to_view(conversation, with_messages=False) for conversation in conversations]


class ReadConversation:
    """Разговор целиком: реплики вместе с тем, что агент смотрел."""

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(
        self,
        tenant_id: TenantId,
        conversation_id: ConversationId,
    ) -> ConversationView:
        async with self._unit_of_work:
            conversation = await self._unit_of_work.conversations.get(conversation_id)
            ensure_own(conversation, tenant_id)
            return to_view(conversation)


def to_view(conversation: Conversation, *, with_messages: bool = True) -> ConversationView:
    return ConversationView(
        id=conversation.id,
        repository_id=conversation.repository_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(conversation.messages),
        document=DocumentView(
            name=conversation.document.name,
            size=conversation.document.size,
        )
        if conversation.document is not None
        else None,
        messages=tuple(_message_view(message) for message in conversation.messages)
        if with_messages
        else (),
    )


def _message_view(message: ChatMessage) -> MessageView:
    return MessageView(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        tool_calls=message.tool_calls,
        tool_name=message.tool_name,
        model=message.model,
        tokens_input=message.usage.input_tokens,
        tokens_output=message.usage.output_tokens,
    )


def ensure_own(conversation: Conversation, tenant_id: TenantId) -> None:
    """Разговор чужого тенанта не читается и не продолжается."""
    if conversation.tenant_id != tenant_id:
        raise PermissionDeniedError("Разговор принадлежит другому тенанту")

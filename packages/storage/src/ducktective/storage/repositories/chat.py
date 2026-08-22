from sqlalchemy import (
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.chat.entities import (
    Conversation,
)
from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.types import (
    ConversationId,
    RepositoryId,
    TenantId,
)
from ducktective.storage.mappers import chat as mapper
from ducktective.storage.models.chat import (
    ConversationModel,
)


class SqlAlchemyConversationRepository:
    """Репозиторий агрегата Conversation.

    Транзакцию не фиксирует: ей управляет Unit of Work. Реплики дописываются
    при коммите — разговор идёт минутами, и держать транзакцию открытой всё
    это время нельзя (D-016).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[ConversationId, tuple[Conversation, ConversationModel]] = {}
        self._removed_events: list[DomainEvent] = []

    def add(self, conversation: Conversation) -> None:
        model = mapper.to_model(conversation)
        self._session.add(model)
        self._identity_map[conversation.id] = (conversation, model)

    async def get(self, conversation_id: ConversationId) -> Conversation:
        tracked = self._identity_map.get(conversation_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(ConversationModel, conversation_id)
        if model is None:
            raise EntityNotFoundError("Conversation", conversation_id)
        return self._track(model)

    async def list_for_repository(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[Conversation]:
        statement = (
            select(ConversationModel)
            .where(
                ConversationModel.tenant_id == tenant_id,
                ConversationModel.repository_id == repository_id,
            )
            .order_by(ConversationModel.updated_at.desc())
            .limit(limit)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._track(model) for model in models]

    async def remove(self, conversation: Conversation) -> None:
        tracked = self._identity_map.pop(conversation.id, None)
        model = (
            tracked[1]
            if tracked is not None
            else await self._session.get(ConversationModel, conversation.id)
        )
        if model is None:
            raise EntityNotFoundError("Conversation", conversation.id)

        await self._session.delete(model)
        self._removed_events.extend(conversation.pull_events())

    def flush_changes(self) -> None:
        for conversation, model in self._identity_map.values():
            mapper.apply_changes(model, conversation)

    def collect_events(self) -> list[DomainEvent]:
        collected = self._removed_events
        self._removed_events = []
        for conversation, _ in self._identity_map.values():
            collected.extend(conversation.pull_events())
        return collected

    def _track(self, model: ConversationModel) -> Conversation:
        conversation_id = ConversationId(model.id)
        tracked = self._identity_map.get(conversation_id)
        if tracked is not None:
            return tracked[0]

        conversation = mapper.to_domain(model)
        self._identity_map[conversation_id] = (conversation, model)
        return conversation

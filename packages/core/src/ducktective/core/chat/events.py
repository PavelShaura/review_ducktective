from dataclasses import (
    dataclass,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.types import (
    ConversationId,
    RepositoryId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class ConversationStarted(DomainEvent):
    conversation_id: ConversationId
    tenant_id: TenantId
    repository_id: RepositoryId


@dataclass(frozen=True, kw_only=True)
class ConversationDeleted(DomainEvent):
    conversation_id: ConversationId
    repository_id: RepositoryId

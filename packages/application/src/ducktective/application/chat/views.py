from dataclasses import (
    dataclass,
    field,
)
from datetime import (
    datetime,
)

from ducktective.core.chat.value_objects import (
    ChatRole,
    ToolInvocation,
)
from ducktective.core.types import (
    ConversationId,
    MessageId,
    RepositoryId,
)


@dataclass(frozen=True, kw_only=True)
class MessageView:
    id: MessageId
    role: ChatRole
    content: str
    created_at: datetime
    tool_calls: tuple[ToolInvocation, ...] = ()
    tool_name: str | None = None
    model: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0


@dataclass(frozen=True, kw_only=True)
class DocumentView:
    """Приложенный документ, каким его видит интерфейс: без содержимого.

    Текст в списке разговоров не нужен и весит десятки килобайт; человеку
    важно, что документ есть, как называется и насколько велик.
    """

    name: str
    size: int


@dataclass(frozen=True, kw_only=True)
class ConversationView:
    """Разговор для показа: без реплик, когда нужен только список."""

    id: ConversationId
    repository_id: RepositoryId
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    document: DocumentView | None = None
    messages: tuple[MessageView, ...] = field(default_factory=tuple)

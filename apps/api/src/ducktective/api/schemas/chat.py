from datetime import (
    datetime,
)
from typing import (
    Self,
)
from uuid import (
    UUID,
)

from pydantic import (
    BaseModel,
    Field,
)

from ducktective.application.chat.views import (
    ConversationView,
    MessageView,
)
from ducktective.core.chat.entities import (
    MAX_DOCUMENT_CHARS,
    MAX_QUESTION_LENGTH,
)
from ducktective.core.chat.value_objects import (
    ChatEvent,
    ChatRole,
)


class StartConversationRequest(BaseModel):
    repository_id: UUID
    tenant_id: UUID


class AttachDocumentRequest(BaseModel):
    """Документ, приложенный к разговору: имя и текст.

    Предел длины тот же, что в домене: отказать сразу дешевле, чем принять
    книгу и объяснять на первом же вопросе, почему из неё ничего не нашлось.
    """

    name: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)


class DocumentResponse(BaseModel):
    name: str
    size: int


class ToolCallResponse(BaseModel):
    call_id: str
    name: str
    arguments: str


class MessageResponse(BaseModel):
    id: UUID
    role: ChatRole
    content: str
    created_at: datetime
    tool_calls: list[ToolCallResponse] = Field(default_factory=list)
    tool_name: str | None = None
    model: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0

    @classmethod
    def from_view(cls, view: MessageView) -> Self:
        return cls(
            id=view.id,
            role=view.role,
            content=view.content,
            created_at=view.created_at,
            tool_calls=[
                ToolCallResponse(call_id=call.call_id, name=call.name, arguments=call.arguments)
                for call in view.tool_calls
            ],
            tool_name=view.tool_name,
            model=view.model,
            tokens_input=view.tokens_input,
            tokens_output=view.tokens_output,
        )


class ConversationResponse(BaseModel):
    id: UUID
    repository_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    document: DocumentResponse | None = None
    messages: list[MessageResponse] = Field(default_factory=list)

    @classmethod
    def from_view(cls, view: ConversationView) -> Self:
        return cls(
            id=view.id,
            repository_id=view.repository_id,
            title=view.title,
            created_at=view.created_at,
            updated_at=view.updated_at,
            message_count=view.message_count,
            document=DocumentResponse(name=view.document.name, size=view.document.size)
            if view.document is not None
            else None,
            messages=[MessageResponse.from_view(message) for message in view.messages],
        )


class AskRequest(BaseModel):
    """Вопрос, пришедший в сокет.

    Предел длины тот же, что в домене: вопрос идёт в окно модели целиком,
    и отказать в нём лучше сразу, чем на середине ответа.
    """

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class ChatEventResponse(BaseModel):
    """Событие потока, каким его видит клиент."""

    kind: str
    text: str = ""
    tool_name: str | None = None
    tool_arguments: str | None = None
    tool_call_id: str | None = None
    model: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0

    @classmethod
    def from_domain(cls, event: ChatEvent) -> Self:
        return cls(
            kind=event.kind.value,
            text=event.text,
            tool_name=event.tool.name if event.tool else None,
            tool_arguments=event.tool.arguments if event.tool else None,
            tool_call_id=event.tool.call_id if event.tool else None,
            model=event.model,
            tokens_input=event.usage.input_tokens,
            tokens_output=event.usage.output_tokens,
        )

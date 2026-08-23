from typing import (
    Any,
)
from uuid import (
    uuid4,
)

from ducktective.core.chat.entities import (
    AttachedDocument,
    ChatMessage,
    Conversation,
)
from ducktective.core.chat.value_objects import (
    ChatUsage,
    ToolInvocation,
)
from ducktective.core.types import (
    ConversationId,
    MessageId,
    RepositoryId,
    TenantId,
)
from ducktective.storage.models.chat import (
    ConversationAttachmentModel,
    ConversationModel,
    MessageModel,
)


def to_domain(model: ConversationModel) -> Conversation:
    return Conversation(
        id=ConversationId(model.id),
        tenant_id=TenantId(model.tenant_id),
        repository_id=RepositoryId(model.repository_id),
        title=model.title,
        created_at=model.created_at,
        updated_at=model.updated_at,
        messages=[_message_to_domain(message) for message in model.messages],
        document=_document_to_domain(model.attachment),
        preferred_model=model.preferred_model,
    )


def to_model(conversation: Conversation) -> ConversationModel:
    return ConversationModel(
        id=conversation.id,
        tenant_id=conversation.tenant_id,
        repository_id=conversation.repository_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_message_to_model(message) for message in conversation.messages],
        attachment=_document_to_model(conversation.document),
        preferred_model=conversation.preferred_model,
    )


def apply_changes(model: ConversationModel, conversation: Conversation) -> None:
    """Досылает то, что появилось в разговоре с прошлой записи.

    Реплики только добавляются: сказанное не переписывается, и сверять
    их по одной незачем — достаточно дописать хвост.
    """
    model.title = conversation.title
    model.updated_at = conversation.updated_at

    known = {message.id for message in model.messages}
    for message in conversation.messages:
        if message.id not in known:
            model.messages.append(_message_to_model(message))

    _apply_document(model, conversation.document)


def _apply_document(model: ConversationModel, document: AttachedDocument | None) -> None:
    """Досылает приложенный документ: он один и заменяется целиком.

    Заменяется, а не дописывается, в отличие от реплик: приложить второй
    документ значит передумать насчёт первого, и держать оба — значит
    хранить то, о чём уже не спрашивают.
    """
    if document is None:
        model.attachment = None
        return

    if model.attachment is None:
        model.attachment = _document_to_model(document)
        return

    model.attachment.name = document.name
    model.attachment.content = document.text
    model.attachment.attached_at = document.attached_at


def _message_to_domain(model: MessageModel) -> ChatMessage:
    return ChatMessage(
        id=MessageId(model.id),
        role=model.role,
        content=model.content,
        created_at=model.created_at,
        tool_calls=tuple(_invocation_to_domain(call) for call in model.tool_calls or ()),
        tool_call_id=model.tool_call_id,
        tool_name=model.tool_name,
        model=model.model,
        usage=ChatUsage(
            input_tokens=model.tokens_input,
            output_tokens=model.tokens_output,
        ),
    )


def _message_to_model(message: ChatMessage) -> MessageModel:
    return MessageModel(
        id=message.id,
        role=message.role,
        content=message.content,
        tool_calls=[_invocation_to_json(call) for call in message.tool_calls] or None,
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        model=message.model,
        tokens_input=message.usage.input_tokens,
        tokens_output=message.usage.output_tokens,
        created_at=message.created_at,
    )


def _document_to_domain(model: ConversationAttachmentModel | None) -> AttachedDocument | None:
    if model is None:
        return None
    return AttachedDocument(
        name=model.name,
        text=model.content,
        attached_at=model.attached_at,
    )


def _document_to_model(document: AttachedDocument | None) -> ConversationAttachmentModel | None:
    if document is None:
        return None
    return ConversationAttachmentModel(
        id=uuid4(),
        name=document.name,
        content=document.text,
        attached_at=document.attached_at,
    )


def _invocation_to_json(invocation: ToolInvocation) -> dict[str, Any]:
    return {
        "call_id": invocation.call_id,
        "name": invocation.name,
        "arguments": invocation.arguments,
    }


def _invocation_to_domain(payload: dict[str, Any]) -> ToolInvocation:
    return ToolInvocation(
        call_id=str(payload.get("call_id", "")),
        name=str(payload.get("name", "")),
        arguments=str(payload.get("arguments", "")),
    )

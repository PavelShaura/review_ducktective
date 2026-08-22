from contextlib import (
    aclosing,
)
from typing import (
    Any,
)
from uuid import (
    UUID,
)

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import (
    ValidationError,
)

from ducktective.api.dependencies import (
    build_chat_use_case,
)
from ducktective.api.routers.investigation_stream import (
    WS_FORBIDDEN,
    WS_NOT_FOUND,
    _close,
    _send,
)
from ducktective.api.schemas.chat import (
    AskRequest,
    ChatEventResponse,
)
from ducktective.application.chat.ask import (
    IndexNotReadyError,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.exceptions import (
    DomainError,
    EntityNotFoundError,
)
from ducktective.core.types import (
    ConversationId,
    TenantId,
)
from ducktective.observability.logging import (
    get_logger,
)


logger = get_logger(__name__)
router = APIRouter(tags=["chat"])

WS_NO_INDEX = 4409
WS_BAD_QUESTION = 4400


@router.websocket("/chat/conversations/{conversation_id}/stream")
async def stream_chat(websocket: WebSocket, conversation_id: UUID, tenant_id: UUID) -> None:
    """Разговор о коде: вопрос в сокет, ответ по мере появления.

    Сокет живёт весь разговор, а не один вопрос: держать соединение дешевле,
    чем открывать его на каждую реплику, и следующий вопрос не ждёт нового
    рукопожатия.

    Это единственное место, где `api` обращается к модели сам. Ревью идёт
    воркером — там задача живёт минутами и переживает перезапуск, — а в
    разговоре очередь между токеном и экраном добавила бы задержку без
    пользы (`02-architecture.md`).
    """
    await websocket.accept()

    try:
        while True:
            question = await _receive_question(websocket)
            if question is None:
                return

            await _answer(websocket, conversation_id, tenant_id, question)
    except WebSocketDisconnect:
        logger.debug("chat.stream_closed", conversation_id=str(conversation_id))


async def _receive_question(websocket: WebSocket) -> str | None:
    """Ждёт следующий вопрос. `None` — разговор окончен или вопрос негоден."""
    try:
        payload = await websocket.receive_json()
    except (WebSocketDisconnect, RuntimeError, ValueError):
        return None

    try:
        return AskRequest.model_validate(payload).question
    except ValidationError as error:
        await _send(
            websocket,
            _failure(f"Вопрос не принят: {_first_reason(error)}"),
        )
        return ""


async def _answer(
    websocket: WebSocket,
    conversation_id: UUID,
    tenant_id: UUID,
    question: str,
) -> None:
    """Проводит один вопрос через агента, отправляя события по мере появления."""
    if not question:
        return

    use_case = build_chat_use_case(websocket.app)

    try:
        events = await use_case.execute(
            TenantId(tenant_id),
            ConversationId(conversation_id),
            question,
        )
    except PermissionDeniedError:
        await _close(websocket, WS_FORBIDDEN, "Разговор принадлежит другому тенанту")
        return
    except EntityNotFoundError:
        await _close(websocket, WS_NOT_FOUND, "Разговор не найден")
        return
    except IndexNotReadyError as error:
        await _send(websocket, _failure(str(error)))
        return
    except DomainError as error:
        await _send(websocket, _failure(str(error)))
        return

    async with aclosing(events) as stream:
        async for event in stream:
            if not await _send(websocket, ChatEventResponse.from_domain(event).model_dump()):
                return


def _failure(text: str) -> dict[str, Any]:
    return ChatEventResponse(kind="failure", text=text).model_dump()


def _first_reason(error: ValidationError) -> str:
    problems = error.errors()
    return str(problems[0].get("msg", error)) if problems else str(error)

from contextlib import (
    suppress,
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
from starlette.websockets import (
    WebSocketState,
)

from ducktective.api.schemas.review import (
    InvestigationStepResponse,
)
from ducktective.api.security import (
    authenticate_websocket,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.review.read_investigation import (
    ReadInvestigation,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.types import (
    ReviewRunId,
)
from ducktective.observability.logging import (
    get_logger,
)
from ducktective.storage.events.step_broadcaster import (
    subscribe_to_steps,
)
from ducktective.storage.repositories.investigation import (
    SqlAlchemyInvestigationLog,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


logger = get_logger(__name__)
router = APIRouter(tags=["reviews"])

WS_FORBIDDEN = 4403
WS_NOT_FOUND = 4404


@router.websocket("/reviews/{run_id}/investigation/stream")
async def stream_investigation(websocket: WebSocket, run_id: UUID) -> None:
    """Ход расследования по мере появления шагов.

    Подписка открывается до чтения уже записанного: шаг, появившийся между
    чтением и подпиской, иначе пропал бы навсегда. Задвоение при этом
    невозможно — у каждого шага свой курсор, и клиент отбрасывает то,
    что уже видел.

    Права проверяются здесь же и один раз: у сокета нет повторного запроса,
    в котором это можно было бы сделать позже. Первым сообщением приходит
    токен — в адресе ему не место, адрес целиком пишется в логи.
    """
    await websocket.accept()

    member = await authenticate_websocket(websocket)
    if member is None:
        return

    unit_of_work = SqlAlchemyUnitOfWork(
        websocket.app.state.session_factory,
        tenant_id=member.tenant_id,
    )
    log = SqlAlchemyInvestigationLog(
        websocket.app.state.session_factory,
        tenant_id=member.tenant_id,
    )
    use_case = ReadInvestigation(unit_of_work, log)

    try:
        async with subscribe_to_steps(websocket.app.state.redis, ReviewRunId(run_id)) as stream:
            recorded = await use_case.execute(member.tenant_id, ReviewRunId(run_id))
            for step in recorded.steps:
                payload = InvestigationStepResponse.from_view(step).model_dump()
                if not await _send(websocket, payload):
                    return

            async for live in stream:
                if not await _send(websocket, live):
                    return
    except PermissionDeniedError:
        await _close(websocket, WS_FORBIDDEN, "Прогон принадлежит другому тенанту")
    except EntityNotFoundError:
        await _close(websocket, WS_NOT_FOUND, "Прогон не найден")
    except WebSocketDisconnect:
        logger.debug("investigation.stream_closed", run_id=str(run_id))


async def _send(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    """Отправляет шаг, пока есть кому. `False` — смотреть больше некому.

    Уход клиента посреди отправки — обычное дело, а не сбой: страницу
    закрывают, дело досматривают до конца, а в разработке React монтирует
    подписку дважды и первый сокет закрывает сам. Транспорт к этому моменту
    уже закрыт, и запись в него роняет обработчик трейсбеком на весь лог —
    хотя произошло ровно то, что должно было.

    Состояние сокета проверяется до отправки, но одной проверки мало:
    закрыться он может и между ней и записью.
    """
    if websocket.client_state is not WebSocketState.CONNECTED:
        return False

    try:
        await websocket.send_json(payload)
    except (WebSocketDisconnect, RuntimeError, ConnectionError):
        return False

    return True


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    """Прощается, если ещё есть с кем.

    Отказ приходит после `accept()`, и к этому моменту клиента может уже
    не быть: закрывать закрытое — вторая ошибка поверх первой, и в логе
    видна будет только она.
    """
    if websocket.client_state is not WebSocketState.CONNECTED:
        return

    with suppress(RuntimeError, ConnectionError):
        await websocket.close(code=code, reason=reason)

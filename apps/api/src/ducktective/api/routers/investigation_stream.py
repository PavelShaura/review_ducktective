from uuid import (
    UUID,
)

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
)

from ducktective.api.schemas.review import (
    InvestigationStepResponse,
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
    TenantId,
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
async def stream_investigation(websocket: WebSocket, run_id: UUID, tenant_id: UUID) -> None:
    """Ход расследования по мере появления шагов.

    Подписка открывается до чтения уже записанного: шаг, появившийся между
    чтением и подпиской, иначе пропал бы навсегда. Задвоение при этом
    невозможно — у каждого шага свой курсор, и клиент отбрасывает то,
    что уже видел.

    Права проверяются здесь же и один раз: у сокета нет повторного запроса,
    в котором это можно было бы сделать позже.
    """
    await websocket.accept()

    unit_of_work = SqlAlchemyUnitOfWork(websocket.app.state.session_factory)
    log = SqlAlchemyInvestigationLog(websocket.app.state.session_factory)
    use_case = ReadInvestigation(unit_of_work, log)

    try:
        async with subscribe_to_steps(websocket.app.state.redis, ReviewRunId(run_id)) as stream:
            recorded = await use_case.execute(TenantId(tenant_id), ReviewRunId(run_id))
            for step in recorded.steps:
                await websocket.send_json(InvestigationStepResponse.from_view(step).model_dump())

            async for payload in stream:
                await websocket.send_json(payload)
    except PermissionDeniedError:
        await websocket.close(code=WS_FORBIDDEN, reason="Прогон принадлежит другому тенанту")
    except EntityNotFoundError:
        await websocket.close(code=WS_NOT_FOUND, reason="Прогон не найден")
    except WebSocketDisconnect:
        logger.debug("investigation.stream_closed", run_id=str(run_id))

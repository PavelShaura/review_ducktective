import asyncio
from typing import (
    Annotated,
    Literal,
)

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from ducktective.api.dependencies import (
    SettingsDependency,
)
from ducktective.api.schemas.logs import (
    LogTailResponse,
)
from ducktective.api.security import (
    InstallationAdminDependency,
)
from ducktective.observability.logfile import (
    MAX_LIMIT,
    LogQuery,
    tail_records,
)


router = APIRouter(tags=["admin"])

Level = Literal["debug", "info", "warning", "error", "critical"]


@router.get("/admin/logs", response_model=LogTailResponse)
async def tail_logs(
    _admin: InstallationAdminDependency,
    settings: SettingsDependency,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 200,
    level: Annotated[Level | None, Query()] = None,
    logger: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> LogTailResponse:
    """Хвост журнала установки для администратора.

    Источник — тот же файл, куда пишут api и воркеры (`APP_LOG_FILE`); без
    него ручке нечего показать, и об этом она говорит прямо, а не отдаёт
    пустой список. Чтение уходит в отдельный поток: файл на диске, и цикл
    событий не должен ждать его вместе с остальными запросами.
    """
    path = settings.app_log_file
    if path is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Журнал не пишется в файл: задайте APP_LOG_FILE и перезапустите службы",
        )
    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Файл журнала ещё не создан: {path}",
        )

    query = LogQuery(limit=limit, min_level=level, logger=logger or None, text=q or None)
    tail = await asyncio.to_thread(tail_records, path, query)
    return LogTailResponse.from_tail(str(path), tail)

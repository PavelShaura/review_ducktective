from typing import (
    Literal,
)

from fastapi import (
    APIRouter,
    Request,
    status,
)
from fastapi.responses import (
    JSONResponse,
)
from pydantic import (
    BaseModel,
)
from redis.asyncio import (
    Redis,
)
from sqlalchemy import (
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)


router = APIRouter(tags=["service"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    redis: bool


@router.get("/health", response_model=HealthResponse)
async def check_health(request: Request) -> JSONResponse:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    redis_client: Redis = request.app.state.redis

    database_alive = await _check_database(session_factory)
    redis_alive = await _check_redis(redis_client)

    is_healthy = database_alive and redis_alive
    payload = HealthResponse(
        status="ok" if is_healthy else "degraded",
        database=database_alive,
        redis=redis_alive,
    )
    return JSONResponse(
        content=payload.model_dump(),
        status_code=status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


async def _check_database(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    try:
        async with session_factory() as session:
            await session.execute(text("select 1"))
    except Exception:
        return False
    return True


async def _check_redis(redis_client: Redis) -> bool:
    try:
        await redis_client.ping()
    except Exception:
        return False
    return True

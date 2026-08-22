from typing import (
    Any,
)

import httpx
from fastapi import (
    FastAPI,
)

from ducktective.api.routers import (
    health,
)


class FailingSessionFactory:
    def __call__(self) -> Any:
        raise ConnectionError("база недоступна")


class FailingRedis:
    async def ping(self) -> bool:
        raise ConnectionError("redis недоступен")


def build_app(session_factory: Any, redis_client: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(health.router)
    app.state.session_factory = session_factory
    app.state.redis = redis_client
    return app


async def test_health_reports_degraded_when_dependencies_are_down() -> None:
    app = build_app(FailingSessionFactory(), FailingRedis())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": False, "redis": False}

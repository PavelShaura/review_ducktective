from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    asynccontextmanager,
)

from arq import (
    create_pool,
)
from arq.connections import (
    RedisSettings,
)
from fastapi import (
    FastAPI,
)
from redis.asyncio import (
    Redis,
)

from ducktective.api.routers import (
    health,
    repositories,
    reviews,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.observability.logging import (
    configure_logging,
    get_logger,
)
from ducktective.storage.database import (
    build_engine,
    build_session_factory,
)


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure_logging(
        level=settings.app_log_level,
        json_output=settings.app_env != "dev",
    )
    engine = build_engine(
        settings.require_database_url(),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
    )
    redis_url = settings.require_redis_url()
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    task_queue = await create_pool(RedisSettings.from_dsn(redis_url))

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.redis = redis_client
    app.state.task_queue = task_queue

    logger.info(
        "api.started",
        profile=settings.deployment_profile,
        cloud_providers_allowed=settings.cloud_providers_allowed,
    )

    try:
        yield
    finally:
        await task_queue.aclose()
        await redis_client.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="review_ducktective",
        description="Автоматическое code review на LLM с RAG по кодовой базе",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(repositories.router)
    app.include_router(reviews.router)
    return app


app = create_app()

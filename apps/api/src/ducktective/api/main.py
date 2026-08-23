from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    asynccontextmanager,
)

import httpx
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
    chat,
    chat_stream,
    health,
    investigation_stream,
    models,
    organization,
    repositories,
    reviews,
)
from ducktective.auth.oidc import (
    OidcIdentityVerifier,
    OidcSettings,
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
    if not settings.authentication_required:
        raise RuntimeError(
            "Не задан OIDC_ISSUER: сетевая служба без входа отдала бы данные "
            "любой организации всякому, кто угадает идентификатор"
        )

    redis_url = settings.require_redis_url()
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    task_queue = await create_pool(RedisSettings.from_dsn(redis_url))

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.redis = redis_client
    app.state.task_queue = task_queue

    identity_client = httpx.AsyncClient(timeout=10.0)
    app.state.identity_client = identity_client
    app.state.identity_verifier = OidcIdentityVerifier(
        OidcSettings(
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
        ),
        identity_client,
    )

    logger.info(
        "api.started",
        profile=settings.deployment_profile,
        cloud_providers_allowed=settings.cloud_providers_allowed,
    )

    try:
        yield
    finally:
        await identity_client.aclose()
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
    app.include_router(organization.router)
    app.include_router(models.router)
    app.include_router(repositories.router)
    app.include_router(reviews.router)
    app.include_router(investigation_stream.router)
    app.include_router(chat.router)
    app.include_router(chat_stream.router)
    return app


app = create_app()

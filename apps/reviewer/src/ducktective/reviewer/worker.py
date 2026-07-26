import os
from typing import (
    Any,
    ClassVar,
)
from uuid import (
    UUID,
)

from arq import (
    func,
)
from arq.connections import (
    RedisSettings,
)
from redis.asyncio import (
    Redis,
)

from ducktective.application.exceptions import (
    ApplicationError,
)
from ducktective.application.review.run_review import (
    RunReview,
)
from ducktective.config.queues import (
    REVIEW_TASK_NAME,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.core.exceptions import (
    DomainError,
)
from ducktective.core.types import (
    ReviewRunId,
    TenantId,
)
from ducktective.llm.factory import (
    build_code_reviewer,
)
from ducktective.observability.logging import (
    configure_logging,
    get_logger,
)
from ducktective.storage.database import (
    build_engine,
    build_session_factory,
)
from ducktective.storage.events.redis_publisher import (
    RedisEventPublisher,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


logger = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = Settings()
    configure_logging(level=settings.app_log_level, json_output=settings.app_env != "dev")

    engine = build_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
    )
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)

    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = build_session_factory(engine)
    ctx["redis"] = redis_client
    ctx["code_reviewer"] = build_code_reviewer(
        redis_client=redis_client,
        local_provider=settings.local_llm_provider,
        local_model=settings.local_review_model,
        local_base_url=settings.local_llm_base_url,
        local_api_key=settings.local_llm_api_key,
        cloud_model=settings.cloud_review_model,
        cloud_api_key=settings.anthropic_api_key,
        cloud_enabled=settings.cloud_providers_allowed,
        cache_ttl_seconds=settings.llm_cache_ttl_seconds,
        timeout_seconds=settings.llm_timeout_seconds,
    )

    logger.info("reviewer.started", profile=settings.deployment_profile)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["redis"].aclose()
    await ctx["engine"].dispose()


async def run_review_task(ctx: dict[str, Any], run_id: str, tenant_id: str) -> dict[str, Any]:
    """Фоновый прогон ревью.

    Ошибки домена и приложения не пробрасываются наружу: прогон уже переведён
    в неуспешный статус внутри use case, а повторная попытка arq ничего
    не изменит и только займёт воркер.
    """
    use_case = RunReview(
        SqlAlchemyUnitOfWork(ctx["session_factory"]),
        RedisEventPublisher(ctx["redis"]),
        ctx["code_reviewer"],
    )

    logger.info("review.started", run_id=run_id)
    try:
        run = await use_case.execute(TenantId(UUID(tenant_id)), ReviewRunId(UUID(run_id)))
    except (DomainError, ApplicationError) as error:
        logger.warning("review.failed", run_id=run_id, error=str(error))
        return {"run_id": run_id, "status": "failed", "error": str(error)}

    logger.info(
        "review.finished",
        run_id=run_id,
        status=run.status.value,
        findings=len(run.findings),
        tokens_input=run.tokens_input,
        tokens_output=run.tokens_output,
    )
    return {
        "run_id": run_id,
        "status": run.status.value,
        "findings": len(run.findings),
        "totals": run.severity_totals,
    }


class WorkerSettings:
    """Точка входа arq: `arq ducktective.reviewer.worker.WorkerSettings`.

    Подключение и таймаут читаются из окружения напрямую: полный набор настроек
    на этапе импорта модуля ещё не обязан быть валидным.
    """

    functions: ClassVar[list[Any]] = [func(run_review_task, name=REVIEW_TASK_NAME)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = int(os.environ.get("REVIEW_MAX_JOBS", "2"))
    job_timeout = int(os.environ.get("REVIEW_JOB_TIMEOUT_SECONDS", "1800"))
    keep_result = 3600

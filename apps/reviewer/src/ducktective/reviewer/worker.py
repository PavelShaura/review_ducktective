import os
from contextlib import (
    AsyncExitStack,
)
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
    ReviewCancelledError,
    RunReview,
)
from ducktective.config.queues import (
    REVIEW_QUEUE,
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
from ducktective.llm.embedder import (
    LiteLlmEmbedder,
)
from ducktective.llm.factory import (
    build_code_reviewers,
)
from ducktective.observability.logging import (
    configure_logging,
    get_logger,
)
from ducktective.retrieval.navigation import (
    IndexedNavigators,
)
from ducktective.retrieval.session_scope import (
    SessionScopedContextBuilder,
    SessionScopedHybridSearch,
    SessionScopedSymbolReader,
)
from ducktective.review_graph import (
    LangGraphReviewPipeline,
)
from ducktective.review_graph.checkpointing import (
    open_checkpointer,
)
from ducktective.review_graph.navigators import (
    RequestNavigators,
)
from ducktective.storage.database import (
    build_engine,
    build_session_factory,
)
from ducktective.storage.events.redis_publisher import (
    RedisEventPublisher,
)
from ducktective.storage.events.step_broadcaster import (
    RedisStepBroadcaster,
)
from ducktective.storage.investigation import (
    RecordingInvestigationSinks,
)
from ducktective.storage.repositories.investigation import (
    SqlAlchemyInvestigationLog,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from ducktective.vcs.git_provider import (
    LocalGitProvider,
)
from ducktective.vcs.navigation import (
    GitNavigators,
)


logger = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = Settings()
    configure_logging(level=settings.app_log_level, json_output=settings.app_env != "dev")

    engine = build_engine(
        settings.require_database_url(),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
    )
    redis_client = Redis.from_url(settings.require_redis_url(), decode_responses=True)

    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = build_session_factory(engine)
    ctx["redis"] = redis_client
    ctx["context_builder"] = SessionScopedContextBuilder(
        ctx["session_factory"],
        LiteLlmEmbedder(
            model=settings.local_embedding_model,
            dimensions=settings.embedding_dimensions,
            base_url=settings.local_embedding_base_url or None,
            api_key=settings.local_llm_api_key,
        ),
        token_budget=settings.context_token_budget,
    )
    ctx["max_output_tokens"] = settings.llm_max_output_tokens
    resources = AsyncExitStack()
    ctx["resources"] = resources
    ctx["navigators"] = RequestNavigators(
        indexed=IndexedNavigators(
            symbols=SessionScopedSymbolReader(ctx["session_factory"]),
            search=SessionScopedHybridSearch(
                ctx["session_factory"],
                LiteLlmEmbedder(
                    model=settings.local_embedding_model,
                    dimensions=settings.embedding_dimensions,
                    base_url=settings.local_embedding_base_url or None,
                    api_key=settings.local_llm_api_key,
                ),
            ),
        ),
        git=GitNavigators(git=LocalGitProvider()),
    )
    ctx["investigation_log"] = SqlAlchemyInvestigationLog(ctx["session_factory"])
    ctx["pipeline"] = LangGraphReviewPipeline(
        build_code_reviewers(
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
            local_supports_tools=settings.local_review_model_supports_tools,
        ),
        context_builder=ctx["context_builder"],
        navigators=ctx["navigators"],
        sinks=RecordingInvestigationSinks(
            ctx["investigation_log"],
            broadcaster=RedisStepBroadcaster(redis_client),
        ),
        checkpointer=await resources.enter_async_context(
            open_checkpointer(settings.require_database_url())
        ),
    )

    logger.info(
        "reviewer.started",
        profile=settings.deployment_profile,
        context_budget=settings.context_token_budget,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    """Гасит ресурсы в порядке, обратном открытию, и все до одного.

    Закрытия зарегистрированы стопкой, а не выстроены в очередь `await`:
    сбой первого не должен оставить остальные висеть. Незакрытый пул
    соединений переживает процесс и достаётся сборщику мусора уже после
    того, как цикл событий разобран, — оттуда и берутся жалобы на
    невозвращённые в пул соединения при остановке.
    """
    async with AsyncExitStack() as closing:
        closing.push_async_callback(ctx["engine"].dispose)
        closing.push_async_callback(ctx["redis"].aclose)
        closing.push_async_callback(ctx["resources"].aclose)


async def run_review_task(
    ctx: dict[str, Any],
    run_id: str,
    tenant_id: str,
    resume: bool = False,
) -> dict[str, Any]:
    """Фоновый прогон ревью.

    Ошибки домена и приложения не пробрасываются наружу: прогон уже переведён
    в неуспешный статус внутри use case, а повторная попытка arq ничего
    не изменит и только займёт воркер. Всё остальное — ошибка не предусмотренная,
    и прогон переводится в неуспешный здесь: иначе он навсегда останется
    «идущим», а интерфейс будет вечно показывать растущее время.

    `resume` со значением по умолчанию: задачи, поставленные в очередь
    до появления продолжения, лежат там с двумя аргументами и обязаны
    отработать как прогон с начала.
    """
    use_case = RunReview(
        SqlAlchemyUnitOfWork(ctx["session_factory"]),
        RedisEventPublisher(ctx["redis"]),
        ctx["pipeline"],
        max_output_tokens=ctx["max_output_tokens"],
    )

    logger.info("review.started", run_id=run_id, resume=resume)
    try:
        outcome = await use_case.execute(
            TenantId(UUID(tenant_id)),
            ReviewRunId(UUID(run_id)),
            resume=resume,
        )
    except ReviewCancelledError:
        logger.info("review.cancelled", run_id=run_id)
        return {"run_id": run_id, "status": "cancelled"}
    except (DomainError, ApplicationError) as error:
        logger.warning("review.failed", run_id=run_id, error=str(error))
        return {"run_id": run_id, "status": "failed", "error": str(error)}
    except Exception as error:
        logger.exception("review.crashed", run_id=run_id, error=str(error))
        await _mark_failed(ctx, run_id, error)
        return {"run_id": run_id, "status": "failed", "error": str(error)}

    run = outcome.run
    logger.info(
        "review.finished",
        run_id=run_id,
        status=run.status.value,
        findings=len(run.findings),
        proposed=outcome.proposed,
        discarded_outside_diff=outcome.discarded_outside_diff,
        discarded_without_evidence=outcome.discarded_without_evidence,
        discarded_unproven_claim=outcome.discarded_unproven_claim,
        discarded_as_duplicate=outcome.discarded_as_duplicate,
        failed_files=len(outcome.failed_files),
        tokens_input=run.tokens_input,
        tokens_output=run.tokens_output,
    )
    return {
        "run_id": run_id,
        "status": run.status.value,
        "findings": len(run.findings),
        "proposed": outcome.proposed,
        "discarded": outcome.discarded,
        "totals": run.severity_totals,
    }


async def _mark_failed(ctx: dict[str, Any], run_id: str, error: Exception) -> None:
    """Переводит прогон в неуспешный после непредвиденной ошибки.

    Отдельной транзакцией и с подавлением собственных ошибок: упасть могла
    как раз работа с базой, и вторая попытка не должна маскировать первую
    причину в журнале.
    """
    try:
        unit_of_work = SqlAlchemyUnitOfWork(ctx["session_factory"])
        async with unit_of_work:
            run = await unit_of_work.review_runs.get(ReviewRunId(UUID(run_id)))
            if not run.is_finished:
                run.mark_failed(str(error))
                await unit_of_work.commit()
    except Exception:
        logger.warning("review.status_not_saved", run_id=run_id)


class WorkerSettings:
    """Точка входа arq: `arq ducktective.reviewer.worker.WorkerSettings`.

    Подключение и таймаут читаются из окружения напрямую: полный набор настроек
    на этапе импорта модуля ещё не обязан быть валидным.
    """

    functions: ClassVar[list[Any]] = [func(run_review_task, name=REVIEW_TASK_NAME)]
    queue_name = REVIEW_QUEUE
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = int(os.environ.get("REVIEW_MAX_JOBS", "2"))
    job_timeout = int(os.environ.get("REVIEW_JOB_TIMEOUT_SECONDS", "1800"))
    keep_result = 3600

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
from ducktective.application.indexing.build_embeddings import (
    BuildEmbeddings,
)
from ducktective.application.indexing.build_index import (
    BuildIndex,
    BuildIndexCommand,
    IndexingCancelledError,
)
from ducktective.config.queues import (
    INDEX_QUEUE,
    INDEX_TASK_NAME,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.core.exceptions import (
    DomainError,
    LlmInvocationError,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStage,
)
from ducktective.core.types import (
    IndexSnapshotId,
    RepositoryId,
    TenantId,
)
from ducktective.indexing.python_parser import (
    PythonParser,
)
from ducktective.llm.embedder import (
    LiteLlmEmbedder,
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
from ducktective.vcs.git_provider import (
    LocalGitProvider,
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
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = build_session_factory(engine)
    ctx["redis"] = Redis.from_url(settings.require_redis_url(), decode_responses=True)

    logger.info("indexer.started", profile=settings.deployment_profile)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["redis"].aclose()
    await ctx["engine"].dispose()


async def build_index_task(
    ctx: dict[str, Any],
    repository_id: str,
    tenant_id: str,
    revision: str = "HEAD",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Фоновая индексация репозитория.

    Векторы считаются вторым шагом и своей ошибкой прогон не отменяют:
    символы и граф уже записаны и полезны сами по себе, а недостающие
    векторы досчитаются при следующем запуске.
    """
    settings: Settings = ctx["settings"]
    unit_of_work = SqlAlchemyUnitOfWork(ctx["session_factory"])
    command = BuildIndexCommand(
        tenant_id=TenantId(UUID(tenant_id)),
        repository_id=RepositoryId(UUID(repository_id)),
        revision=revision,
        snapshot_id=IndexSnapshotId(UUID(snapshot_id)) if snapshot_id else None,
    )

    logger.info("index.started", repository_id=repository_id, revision=revision)
    try:
        outcome = await BuildIndex(
            unit_of_work,
            RedisEventPublisher(ctx["redis"]),
            LocalGitProvider(),
            PythonParser(),
        ).execute(command)
    except IndexingCancelledError:
        logger.info("index.cancelled", repository_id=repository_id)
        return {"repository_id": repository_id, "status": "cancelled"}
    except (DomainError, ApplicationError) as error:
        logger.warning("index.failed", repository_id=repository_id, error=str(error))
        return {"repository_id": repository_id, "status": "failed", "error": str(error)}
    except Exception as error:
        logger.exception("index.crashed", repository_id=repository_id)
        return {"repository_id": repository_id, "status": "failed", "error": str(error)}

    await _mark_embedding_stage(unit_of_work, outcome.snapshot.id)
    embeddings = await _embed(
        settings,
        unit_of_work,
        command.repository_id,
        outcome.snapshot.id,
    )

    stats = outcome.stats
    logger.info(
        "index.finished",
        repository_id=repository_id,
        commit_sha=outcome.snapshot.commit_sha,
        incremental=outcome.is_incremental,
        files_parsed=stats.files_parsed,
        files_reused=stats.files_reused,
        symbols=stats.symbols,
        chunks=stats.chunks,
        edges_resolved=stats.edges_resolved,
        embeddings=embeddings,
    )
    return {
        "repository_id": repository_id,
        "status": outcome.snapshot.status.value,
        "commit_sha": outcome.snapshot.commit_sha,
        "files_parsed": stats.files_parsed,
        "files_reused": stats.files_reused,
        "embeddings": embeddings,
    }


async def _mark_embedding_stage(
    unit_of_work: SqlAlchemyUnitOfWork,
    snapshot_id: IndexSnapshotId,
) -> None:
    """Отмечает, что осталось посчитать векторы.

    Снапшот к этому моменту уже готов: символы и граф записаны, и падение
    эмбеддера ничего из этого не отменяет.
    """
    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.get(snapshot_id)
        snapshot.enter_stage(SnapshotStage.EMBEDDING)
        await unit_of_work.commit()


async def _embed(
    settings: Settings,
    unit_of_work: SqlAlchemyUnitOfWork,
    repository_id: RepositoryId,
    snapshot_id: IndexSnapshotId,
) -> int:
    embedder = LiteLlmEmbedder(
        model=settings.local_embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.local_embedding_base_url or None,
        api_key=settings.local_llm_api_key,
    )

    try:
        outcome = await BuildEmbeddings(unit_of_work, embedder).execute(
            repository_id,
            snapshot_id=snapshot_id,
        )
    except LlmInvocationError as error:
        logger.warning("index.embeddings_skipped", error=str(error))
        return 0

    return outcome.total


class WorkerSettings:
    """Точка входа arq: `arq ducktective.indexer.worker.WorkerSettings`."""

    functions: ClassVar[list[Any]] = [func(build_index_task, name=INDEX_TASK_NAME)]
    queue_name = INDEX_QUEUE
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = int(os.environ.get("INDEX_MAX_JOBS", "1"))
    job_timeout = int(os.environ.get("INDEX_JOB_TIMEOUT_SECONDS", "3600"))
    keep_result = 3600

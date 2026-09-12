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
from ducktective.indexing.parsers import (
    build_parser,
)
from ducktective.llm.factory import (
    build_embedders,
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
    """Гасит ресурсы все до одного: сбой первого не оставляет остальные висеть.

    Незакрытый пул соединений достаётся сборщику мусора уже после разбора
    цикла событий, и процесс уходит с жалобами на невозвращённые соединения.
    """
    async with AsyncExitStack() as closing:
        closing.push_async_callback(ctx["engine"].dispose)
        closing.push_async_callback(ctx["redis"].aclose)


async def build_index_task(
    ctx: dict[str, Any],
    repository_id: str,
    tenant_id: str,
    revision: str = "HEAD",
    snapshot_id: str | None = None,
    embedding_backend: str | None = None,
) -> dict[str, Any]:
    """Фоновая индексация репозитория.

    Векторы считаются вторым шагом и своей ошибкой прогон не отменяют:
    символы и граф уже записаны и полезны сами по себе, а недостающие
    векторы досчитаются при следующем запуске.
    """
    settings: Settings = ctx["settings"]
    tenant = TenantId(UUID(tenant_id))
    unit_of_work = SqlAlchemyUnitOfWork(ctx["session_factory"], tenant_id=tenant)
    command = BuildIndexCommand(
        tenant_id=tenant,
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
            build_parser(),
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
        embedding_backend,
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
    embedding_backend: str | None,
) -> int:
    """Считает векторы выбранным сервером.

    Пустой ключ — выбор, записанный у репозитория; неизвестный — сервер
    по умолчанию.
    """
    if embedding_backend is None:
        async with unit_of_work:
            repository = await unit_of_work.code_repositories.get(repository_id)
            embedding_backend = repository.embedding_backend

    backends = settings.embedding_backends()
    backend = next((item for item in backends if item.key == embedding_backend), backends[0])
    embedder = build_embedders([backend], dimensions=settings.embedding_dimensions)[backend.key]

    try:
        outcome = await BuildEmbeddings(unit_of_work, embedder).execute(
            repository_id,
            snapshot_id=snapshot_id,
        )
    except LlmInvocationError as error:
        logger.warning("index.embeddings_skipped", error=str(error))
        await _record_embedding_failure(
            unit_of_work,
            snapshot_id,
            f"Векторы досчитаны не полностью: {backend.title} — модель {backend.model} "
            f"по адресу {backend.base_url} не ответила. {error}",
        )
        return 0

    if not outcome.stopped:
        await _finish_embedding(unit_of_work, snapshot_id)
    return outcome.total


async def _finish_embedding(
    unit_of_work: SqlAlchemyUnitOfWork,
    snapshot_id: IndexSnapshotId,
) -> None:
    """Закрывает досчёт: без этой отметки он неотличим от идущего."""
    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.get(snapshot_id)
        if snapshot.stage is SnapshotStage.EMBEDDING and not snapshot.embedding_stopped:
            snapshot.finish_embedding()
        await unit_of_work.commit()


async def _record_embedding_failure(
    unit_of_work: SqlAlchemyUnitOfWork,
    snapshot_id: IndexSnapshotId,
    reason: str,
) -> None:
    """Пишет на снапшот, почему векторов не будет.

    Без этой отметки прерванный досчёт неотличим от идущего: доля посчитанных
    замирает, а карточка продолжает объяснять, что векторы считаются. Символы
    и граф при этом целы, поэтому статус остаётся готовым.
    """
    try:
        async with unit_of_work:
            snapshot = await unit_of_work.index_snapshots.get(snapshot_id)
            snapshot.record_embedding_failure(reason)
            await unit_of_work.commit()
    except Exception:
        logger.warning("index.embedding_failure_not_saved", snapshot_id=str(snapshot_id))


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

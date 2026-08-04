from typing import (
    TYPE_CHECKING,
)
from uuid import (
    UUID,
)

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.llm.value_objects import (
    ModelRequirements,
)
from ducktective.core.review.pipeline import (
    PipelineRequest,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.review_graph import (
    LangGraphReviewPipeline,
)
from ducktective.review_graph.checkpointing import (
    open_checkpointer,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)
from tests.fakes import (
    FakeCodeReviewer,
)
from tests.integration.test_review_run_persistence import (
    build_run,
    prepare_repository,
)
from tests.test_review_graph import (
    HELPERS_FILE,
    SERVICE_FILE,
    build_draft,
    read_at_least,
)


if TYPE_CHECKING:
    from langchain_core.runnables import (
        RunnableConfig,
    )


pytestmark = pytest.mark.integration


async def store_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[TenantId, PipelineRequest]:
    """Кладёт прогон в базу и читает его обратно — как это делает use case.

    Именно чтение обратно и важно: объекты, рождённые в памяти, носят
    `uuid.UUID`, а пришедшие из базы — тип драйвера, и разница видна только
    здесь.
    """
    tenant_id, repository_id = await prepare_repository(session_factory)
    run = build_run(tenant_id, repository_id)

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.review_runs.add(run)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as unit_of_work:
        stored = await unit_of_work.review_runs.get(run.id)

    return tenant_id, PipelineRequest(
        run_id=stored.id,
        repository_id=stored.repository_id,
        files=tuple(stored.reviewable_files()),
        requirements=ModelRequirements(),
    )


async def test_identifiers_from_the_database_are_stdlib_uuid(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Тип драйвера не должен доезжать до домена: он ломает сохранение хода."""
    _, request = await store_run(session_factory)

    assert type(request.run_id) is UUID
    assert type(request.files[0].id) is UUID
    assert type(request.files[0].hunks[0].id) is UUID


async def test_run_read_from_the_database_survives_being_resumed(
    session_factory: async_sessionmaker[AsyncSession],
    migrated_database_url: str,
) -> None:
    """Прерванный прогон дочитывает остаток, а не начинает заново.

    Тест интеграционный не ради Postgres как хранилища чекпоинтов, а ради
    объектов, пришедших из базы: на объектах из `uuid4()` эта поломка
    не воспроизводится вовсе.
    """
    _, request = await store_run(session_factory)

    async with open_checkpointer(migrated_database_url) as checkpointer:
        reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()], HELPERS_FILE: []})
        pipeline = LangGraphReviewPipeline([reviewer], checkpointer=checkpointer)

        stopped = await pipeline.run(request, cancellation=read_at_least(reviewer, 1))
        assert stopped.is_cancelled is True
        assert len(reviewer.reviewed_paths) == 1

        continued = await pipeline.run(request, resume=True)

        assert sorted(reviewer.reviewed_paths) == sorted([SERVICE_FILE, HELPERS_FILE])
        assert continued.reviewed_files == 2
        assert len(continued.findings) == 1

        await pipeline.forget(request.run_id)


async def test_forgotten_run_leaves_nothing_behind(
    session_factory: async_sessionmaker[AsyncSession],
    migrated_database_url: str,
) -> None:
    """В состоянии лежат патчи всех файлов — забытый прогон не хранит их."""
    _, request = await store_run(session_factory)

    async with open_checkpointer(migrated_database_url) as checkpointer:
        reviewer = FakeCodeReviewer({SERVICE_FILE: [build_draft()]})
        pipeline = LangGraphReviewPipeline([reviewer], checkpointer=checkpointer)
        await pipeline.run(request, cancellation=read_at_least(reviewer, 1))
        await pipeline.forget(request.run_id)

        config: RunnableConfig = {"configurable": {"thread_id": str(request.run_id)}}
        assert await checkpointer.aget_tuple(config) is None

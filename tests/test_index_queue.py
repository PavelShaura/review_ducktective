from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.build_index import (
    BuildIndex,
    BuildIndexCommand,
    IndexingCancelledError,
)
from ducktective.application.indexing.cancel import (
    CancelIndexing,
)
from ducktective.application.indexing.delete import (
    DeleteIndex,
    IndexingInProgressError,
)
from ducktective.application.indexing.enqueue import (
    EnqueueIndexing,
    IndexingAlreadyQueuedError,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.indexing.entities import (
    IndexSnapshot,
    IndexStats,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStage,
    SnapshotStatus,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)
from ducktective.indexing.python_parser import (
    PythonParser,
)
from tests.fakes import (
    FakeEventPublisher,
    FakeUnitOfWork,
    FakeVcsProvider,
)


TENANT_ID = TenantId(uuid4())
OTHER_TENANT_ID = TenantId(uuid4())


def registered(unit_of_work: FakeUnitOfWork, *, tenant_id: TenantId = TENANT_ID) -> RepositoryId:
    repository = CodeRepository.register(
        tenant_id=tenant_id,
        name="ducktective",
        vcs_provider=VcsProvider.LOCAL,
        local_path=Path("/repos/ducktective"),
    )
    unit_of_work.code_repositories.add(repository)
    return repository.id


def enqueue(unit_of_work: FakeUnitOfWork) -> EnqueueIndexing:
    return EnqueueIndexing(unit_of_work, FakeEventPublisher(), FakeVcsProvider())


async def test_queued_indexing_leaves_a_pending_snapshot() -> None:
    """Без следа в базе очередь живёт только в памяти вкладки."""
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work)

    await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")

    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.find_latest(repository_id)

    assert snapshot is not None
    assert snapshot.status is SnapshotStatus.PENDING
    assert snapshot.commit_sha == "sha-HEAD"


async def test_queued_indexing_can_be_cancelled_before_the_worker_starts() -> None:
    """Прежде отмена в этот момент молча ничего не делала."""
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work)
    await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")

    cancelled = await CancelIndexing(unit_of_work, FakeEventPublisher()).execute(
        TENANT_ID,
        repository_id,
    )

    assert cancelled

    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.find_latest(repository_id)
    assert snapshot is not None
    assert snapshot.status is SnapshotStatus.CANCELLED


async def test_second_queueing_is_refused() -> None:
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work)
    await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")

    with pytest.raises(IndexingAlreadyQueuedError):
        await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")


async def test_queueing_for_a_foreign_repository_is_denied() -> None:
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work, tenant_id=OTHER_TENANT_ID)

    with pytest.raises(PermissionDeniedError):
        await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")


async def test_deleting_the_index_removes_its_snapshots() -> None:
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work)
    await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")

    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.find_latest(repository_id)
        assert snapshot is not None
        snapshot.mark_running()
        snapshot.mark_ready(IndexStats(symbols=1))
        await unit_of_work.commit()

    removed = await DeleteIndex(unit_of_work, FakeEventPublisher()).execute(
        TENANT_ID,
        repository_id,
    )

    assert removed == 1
    async with unit_of_work:
        assert await unit_of_work.index_snapshots.find_latest(repository_id) is None


async def test_index_is_not_deleted_while_it_is_being_built() -> None:
    """Удалить снапшот, в который пишет воркер, значило бы оборвать его записью."""
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work)
    await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")

    with pytest.raises(IndexingInProgressError):
        await DeleteIndex(unit_of_work, FakeEventPublisher()).execute(TENANT_ID, repository_id)


async def test_deleting_a_foreign_index_is_denied() -> None:
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work, tenant_id=OTHER_TENANT_ID)

    with pytest.raises(PermissionDeniedError):
        await DeleteIndex(unit_of_work, FakeEventPublisher()).execute(TENANT_ID, repository_id)


async def test_cancelled_job_does_not_revive_when_the_worker_picks_it_up() -> None:
    """Задача остаётся в очереди и после отмены.

    Прекратить её может только воркер, посмотрев на состояние снапшота,
    за которым его позвали, — иначе отменённая сборка отработает сама.
    """
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work)
    snapshot_id = await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")
    await CancelIndexing(unit_of_work, FakeEventPublisher()).execute(TENANT_ID, repository_id)

    build = BuildIndex(
        unit_of_work,
        FakeEventPublisher(),
        FakeVcsProvider(),
        PythonParser(),
    )

    with pytest.raises(IndexingCancelledError):
        await build.execute(
            BuildIndexCommand(
                tenant_id=TENANT_ID,
                repository_id=repository_id,
                snapshot_id=snapshot_id,
            )
        )


async def indexed_repository(unit_of_work: FakeUnitOfWork) -> tuple[RepositoryId, IndexSnapshot]:
    repository_id = registered(unit_of_work)
    await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")

    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.find_latest(repository_id)
        assert snapshot is not None
        snapshot.mark_running()
        snapshot.mark_ready(IndexStats(chunks=10))
        snapshot.enter_stage(SnapshotStage.EMBEDDING)
        await unit_of_work.commit()

    return repository_id, snapshot


async def test_cancel_stops_the_vector_pass_after_the_snapshot_is_ready() -> None:
    """У индексации две завершающие точки, и отменять приходится обе.

    Прежде досчёт векторов нельзя было остановить ничем, кроме снятия воркера:
    снапшот к этому моменту готов, а отмена требовала незавершённого.
    """
    unit_of_work = FakeUnitOfWork()
    repository_id, _ = await indexed_repository(unit_of_work)

    cancelled = await CancelIndexing(unit_of_work, FakeEventPublisher()).execute(
        TENANT_ID,
        repository_id,
    )

    assert cancelled
    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.find_latest(repository_id)
    assert snapshot is not None
    assert snapshot.status is SnapshotStatus.READY
    assert snapshot.embedding_stopped is True


async def test_second_cancel_of_a_stopped_pass_reports_nothing_to_do() -> None:
    unit_of_work = FakeUnitOfWork()
    repository_id, _ = await indexed_repository(unit_of_work)
    cancel = CancelIndexing(unit_of_work, FakeEventPublisher())
    await cancel.execute(TENANT_ID, repository_id)

    assert await cancel.execute(TENANT_ID, repository_id) is False


async def test_vector_pass_cannot_be_stopped_outside_its_stage() -> None:
    unit_of_work = FakeUnitOfWork()
    repository_id = registered(unit_of_work)
    await enqueue(unit_of_work).execute(TENANT_ID, repository_id, "HEAD")

    async with unit_of_work:
        snapshot = await unit_of_work.index_snapshots.find_latest(repository_id)
        assert snapshot is not None
        snapshot.mark_running()
        snapshot.mark_ready(IndexStats(chunks=10))
        await unit_of_work.commit()

        with pytest.raises(InvariantViolationError):
            snapshot.stop_embedding()

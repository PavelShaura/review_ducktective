from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.enqueue import (
    EnqueueIndexing,
    IndexingAlreadyQueuedError,
)
from ducktective.core.diff.ports import (
    VcsProvider,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.types import (
    CommitSha,
    IndexSnapshotId,
    RepositoryId,
    TenantId,
)


class EnsureIndexForRevision:
    """Ставит сборку индекса на ревизию, если готового снимка на ней нет.

    Индекс на другой ревизии ревью не использует, поэтому дело о коммите
    получает свой снимок до начала прогона. Идущая сборка не прерывается
    и вторая не ставится: прогон дождётся её и возьмёт то, что она соберёт.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        vcs_provider: VcsProvider,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._enqueue = EnqueueIndexing(unit_of_work, event_publisher, vcs_provider)

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        commit_sha: CommitSha,
    ) -> IndexSnapshotId | None:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            ready = await self._unit_of_work.index_snapshots.find_latest_ready(repository_id)
            if ready is not None and ready.commit_sha == commit_sha:
                return None

            latest = await self._unit_of_work.index_snapshots.find_latest(repository_id)
            if latest is not None and not latest.is_finished:
                return None

        try:
            return await self._enqueue.execute(tenant_id, repository_id, commit_sha)
        except IndexingAlreadyQueuedError:
            return None

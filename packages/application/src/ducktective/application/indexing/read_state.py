from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.views import (
    IndexStateView,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class GetIndexState:
    """Отдаёт состояние индекса репозитория.

    Отсутствие снапшота — не ошибка, а обычное состояние нового репозитория,
    поэтому возвращается пустое представление, а не исключение.
    """

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
    ) -> IndexStateView:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            snapshot = await self._unit_of_work.index_snapshots.find_latest(repository_id)
            if snapshot is None:
                return IndexStateView()

            return IndexStateView(
                snapshot_id=snapshot.id,
                status=snapshot.status,
                stage=snapshot.stage,
                commit_sha=snapshot.commit_sha,
                stats=snapshot.stats,
                finished_at=snapshot.finished_at,
                failure_reason=snapshot.failure_reason,
            )

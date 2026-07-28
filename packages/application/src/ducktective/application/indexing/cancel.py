from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class CancelIndexing(TransactionalUseCase):
    """Просит прекратить идущую индексацию.

    Работа не обрывается на месте: снапшот помечается отменённым, а воркер
    замечает это на ближайшей отсечке и выходит. Записанное откатывается
    вместе с транзакцией, а файлы отменённого снапшота не считаются
    разобранными — следующий запуск начнёт с чистого листа.
    """

    async def execute(self, tenant_id: TenantId, repository_id: RepositoryId) -> bool:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            snapshot = await self._unit_of_work.index_snapshots.find_latest(repository_id)
            if snapshot is None or snapshot.is_finished:
                return False

            snapshot.cancel()
            await self._commit_and_publish()
            return True

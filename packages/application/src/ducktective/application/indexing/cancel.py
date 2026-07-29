from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStage,
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

    У индексации две завершающие точки, и отменять приходится обе. После
    записи символов и графа снапшот готов, но работа продолжается досчётом
    векторов — там отменяется продолжение, а не снапшот: он действительно
    завершён, и менять его состояние было бы неправдой.
    """

    async def execute(self, tenant_id: TenantId, repository_id: RepositoryId) -> bool:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            snapshot = await self._unit_of_work.index_snapshots.find_latest(repository_id)
            if snapshot is None:
                return False

            if not snapshot.is_finished:
                snapshot.cancel()
                await self._commit_and_publish()
                return True

            if snapshot.stage is SnapshotStage.EMBEDDING and not snapshot.embedding_stopped:
                snapshot.stop_embedding()
                await self._commit_and_publish()
                return True

            return False

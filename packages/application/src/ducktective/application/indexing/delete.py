from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class IndexingInProgressError(ApplicationError):
    """Индекс нельзя стереть, пока по нему идёт работа."""


class DeleteIndex(TransactionalUseCase):
    """Стирает индекс репозитория, оставляя сам репозиторий и его дела.

    Нужен, когда изменились правила разбора или чанкинга: инкрементальность
    опирается на хеши, и неизменившийся файл новый прогон не перечитает.
    Стереть и собрать заново — единственный способ применить их ко всей базе.

    Идущая сборка сначала отменяется: удалить снапшот, в который прямо сейчас
    пишет воркер, значило бы оборвать его на середине записи.
    """

    async def execute(self, tenant_id: TenantId, repository_id: RepositoryId) -> int:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            latest = await self._unit_of_work.index_snapshots.find_latest(repository_id)
            if latest is not None and not latest.is_finished:
                raise IndexingInProgressError(
                    "Сейчас идёт сборка индекса — отмените её, прежде чем стирать"
                )

            removed = await self._unit_of_work.index_snapshots.remove_for_repository(repository_id)
            await self._commit_and_publish()
            return removed

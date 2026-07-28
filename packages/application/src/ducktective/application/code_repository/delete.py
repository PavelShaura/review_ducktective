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


class DeleteCodeRepository(TransactionalUseCase):
    """Убирает репозиторий вместе со всем, что к нему относится.

    Уходит и индекс, и прогоны с находками: держать дела репозитория,
    которого больше нет, незачем — открыть их всё равно не выйдет.
    Удаление разбирают внешние ключи, а не приложение.
    """

    async def execute(self, tenant_id: TenantId, repository_id: RepositoryId) -> None:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            repository.record_deletion()
            await self._unit_of_work.code_repositories.remove(repository)
            await self._commit_and_publish()

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.types import (
    TenantId,
)


class ListCodeRepositories:
    """Чтение списка репозиториев тенанта.

    Транзакция на запись не нужна, поэтому базовый TransactionalUseCase не используется.
    """

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(self, tenant_id: TenantId) -> list[CodeRepository]:
        async with self._unit_of_work:
            return await self._unit_of_work.code_repositories.list_for_tenant(tenant_id)

from uuid import (
    UUID,
)

from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class RepositoryNotResolvedError(ApplicationError):
    """Репозиторий не найден ни по идентификатору, ни по имени.

    Несёт имена доступных репозиториев: клиент, ошибшийся в названии,
    должен получить выбор, а не тупик.
    """

    def __init__(self, reference: str, available: list[str]) -> None:
        super().__init__(f"Репозиторий не найден: {reference}")
        self.reference = reference
        self.available = available


class ResolveCodeRepository:
    """Находит репозиторий по идентификатору или имени.

    Точкам входа, за которыми стоит человек или агент, идентификатор назвать
    нечем — они знают имя. Приём обеих форм оставляет UUID работающим там,
    где он уже используется.
    """

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(self, tenant_id: TenantId, reference: str) -> CodeRepository:
        async with self._unit_of_work:
            repositories = self._unit_of_work.code_repositories

            found = await self._by_identifier(tenant_id, reference)
            if found is None:
                found = await repositories.find_by_name(tenant_id, reference.strip())

            if found is None:
                owned = await repositories.list_for_tenant(tenant_id)
                raise RepositoryNotResolvedError(
                    reference,
                    sorted(repository.name for repository in owned),
                )
            return found

    async def _by_identifier(self, tenant_id: TenantId, reference: str) -> CodeRepository | None:
        try:
            identifier = RepositoryId(UUID(reference))
        except ValueError:
            return None

        try:
            repository = await self._unit_of_work.code_repositories.get(identifier)
        except EntityNotFoundError:
            return None

        if repository.tenant_id != tenant_id:
            raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")
        return repository

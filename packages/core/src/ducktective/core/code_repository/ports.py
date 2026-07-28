from typing import (
    Protocol,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class CodeRepositoryRepository(Protocol):
    """Доступ к агрегату CodeRepository. Не фиксирует транзакцию — это дело UoW."""

    def add(self, repository: CodeRepository) -> None: ...

    async def get(self, repository_id: RepositoryId) -> CodeRepository: ...

    async def find_by_name(self, tenant_id: TenantId, name: str) -> CodeRepository | None: ...

    async def list_for_tenant(self, tenant_id: TenantId) -> list[CodeRepository]: ...

    async def remove(self, repository: CodeRepository) -> None:
        """Удаляет репозиторий. Индекс и прогоны уходят по каскаду."""
        ...

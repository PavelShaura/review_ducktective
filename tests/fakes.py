from types import (
    TracebackType,
)
from typing import (
    Self,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class FakeCodeRepositoryRepository:
    def __init__(self) -> None:
        self.stored: dict[RepositoryId, CodeRepository] = {}

    def add(self, repository: CodeRepository) -> None:
        self.stored[repository.id] = repository

    async def get(self, repository_id: RepositoryId) -> CodeRepository:
        repository = self.stored.get(repository_id)
        if repository is None:
            raise EntityNotFoundError("CodeRepository", repository_id)
        return repository

    async def find_by_name(self, tenant_id: TenantId, name: str) -> CodeRepository | None:
        for repository in self.stored.values():
            if repository.tenant_id == tenant_id and repository.name == name:
                return repository
        return None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[CodeRepository]:
        return [
            repository for repository in self.stored.values() if repository.tenant_id == tenant_id
        ]


class FakeUnitOfWork:
    """Unit of Work на словарях: позволяет тестировать use cases без БД."""

    def __init__(self) -> None:
        self.code_repositories = FakeCodeRepositoryRepository()
        self.commit_calls = 0
        self.rollback_calls = 0
        self.is_active = False

    async def __aenter__(self) -> Self:
        self.is_active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.is_active = False

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for repository in self.code_repositories.stored.values():
            collected.extend(repository.pull_events())
        return collected


class FakeEventPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, events: list[DomainEvent]) -> None:
        self.published.extend(events)

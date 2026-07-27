from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.types import (
    RepositoryId,
    ReviewRunId,
    TenantId,
)


class InMemoryCodeRepositoryRepository:
    """Репозиторий агрегата CodeRepository в памяти процесса.

    Добавленные агрегаты попадают в основное хранилище только после commit —
    так соблюдается тот же контракт, что и у реализации поверх SQLAlchemy.
    """

    def __init__(self) -> None:
        self._committed: dict[RepositoryId, CodeRepository] = {}
        self._pending: dict[RepositoryId, CodeRepository] = {}

    def add(self, repository: CodeRepository) -> None:
        self._pending[repository.id] = repository

    async def get(self, repository_id: RepositoryId) -> CodeRepository:
        repository = self._pending.get(repository_id) or self._committed.get(repository_id)
        if repository is None:
            raise EntityNotFoundError("CodeRepository", repository_id)
        return repository

    async def find_by_name(self, tenant_id: TenantId, name: str) -> CodeRepository | None:
        for repository in self._tracked():
            if repository.tenant_id == tenant_id and repository.name == name:
                return repository
        return None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[CodeRepository]:
        return [repository for repository in self._tracked() if repository.tenant_id == tenant_id]

    def commit(self) -> None:
        self._committed.update(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for repository in self._tracked():
            collected.extend(repository.pull_events())
        return collected

    def _tracked(self) -> list[CodeRepository]:
        return [*self._committed.values(), *self._pending.values()]


class InMemoryReviewRunRepository:
    """Репозиторий агрегата ReviewRun в памяти процесса."""

    def __init__(self) -> None:
        self._committed: dict[ReviewRunId, ReviewRun] = {}
        self._pending: dict[ReviewRunId, ReviewRun] = {}
        self._removed_events: list[DomainEvent] = []

    def add(self, run: ReviewRun) -> None:
        self._pending[run.id] = run

    async def get(self, run_id: ReviewRunId) -> ReviewRun:
        run = self._pending.get(run_id) or self._committed.get(run_id)
        if run is None:
            raise EntityNotFoundError("ReviewRun", run_id)
        return run

    async def list_for_repository(
        self,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[ReviewRun]:
        runs = [run for run in self._tracked() if run.repository_id == repository_id]
        return runs[:limit]

    async def remove(self, run: ReviewRun) -> None:
        self._pending.pop(run.id, None)
        self._committed.pop(run.id, None)
        self._removed_events.extend(run.pull_events())

    def commit(self) -> None:
        self._committed.update(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()

    def collect_events(self) -> list[DomainEvent]:
        collected = self._removed_events
        self._removed_events = []
        for run in self._tracked():
            collected.extend(run.pull_events())
        return collected

    def _tracked(self) -> list[ReviewRun]:
        return [*self._committed.values(), *self._pending.values()]

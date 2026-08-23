from types import (
    TracebackType,
)
from typing import (
    Protocol,
    Self,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.storage.memory.repositories import (
    InMemoryCodeRepositoryRepository,
    InMemoryConversationRepository,
    InMemoryEmbeddingStore,
    InMemoryIndexSnapshotRepository,
    InMemoryInvitationRepository,
    InMemoryModelProfileRepository,
    InMemoryReviewRunRepository,
    InMemorySourceFileRepository,
    InMemorySymbolEdgeRepository,
    InMemoryTenantRepository,
    InMemoryUserAccountRepository,
)


class InMemoryRepository(Protocol):
    """Репозиторий в памяти: фиксирует и откатывает добавленное."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def collect_events(self) -> list[DomainEvent]: ...


class InMemoryUnitOfWork:
    """Unit of Work без внешнего хранилища.

    Нужен для автономного режима CLI: прогон ревью на своей машине не должен
    требовать поднятых Postgres и Redis. Реализует тот же порт, что и версия
    поверх SQLAlchemy, поэтому use cases не знают о подмене.

    Ограничение, сознательно оставленное: откат отменяет добавление новых
    агрегатов, но не отменяет изменения уже загруженных — копировать состояние
    ради однопроцессного сценария незачем. Данные живут до конца процесса.
    """

    def __init__(self) -> None:
        self.code_repositories = InMemoryCodeRepositoryRepository()
        self.review_runs = InMemoryReviewRunRepository()
        self.index_snapshots = InMemoryIndexSnapshotRepository()
        self.source_files = InMemorySourceFileRepository(self.index_snapshots)
        self.symbol_edges = InMemorySymbolEdgeRepository(self.source_files)
        self.embeddings = InMemoryEmbeddingStore(self.source_files)
        self.conversations = InMemoryConversationRepository()
        self.tenants = InMemoryTenantRepository()
        self.user_accounts = InMemoryUserAccountRepository()
        self.invitations = InMemoryInvitationRepository()
        self.model_profiles = InMemoryModelProfileRepository()
        self._collected_events: list[DomainEvent] = []
        self._is_active = False

    async def __aenter__(self) -> Self:
        if self._is_active:
            raise RuntimeError("Вложенные Unit of Work запрещены")
        self._is_active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._is_active = False
        self._rollback_all()

    async def commit(self) -> None:
        self._collect_from_repositories()
        for repository in self._repositories():
            repository.commit()

    async def rollback(self) -> None:
        self._collected_events = []
        self._rollback_all()

    def collect_events(self) -> list[DomainEvent]:
        collected = self._collected_events
        self._collected_events = []
        return collected

    def _collect_from_repositories(self) -> None:
        for repository in self._repositories():
            self._collected_events.extend(repository.collect_events())

    def _rollback_all(self) -> None:
        for repository in self._repositories():
            repository.rollback()

    def _repositories(self) -> list[InMemoryRepository]:
        return [
            self.code_repositories,
            self.review_runs,
            self.index_snapshots,
            self.source_files,
            self.symbol_edges,
            self.embeddings,
            self.conversations,
            self.tenants,
            self.user_accounts,
            self.invitations,
            self.model_profiles,
        ]

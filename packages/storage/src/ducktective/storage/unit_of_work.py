from types import (
    TracebackType,
)
from typing import (
    Protocol,
    Self,
)

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.storage.repositories.code_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from ducktective.storage.repositories.review_run import (
    SqlAlchemyReviewRunRepository,
)


class TrackingRepository(Protocol):
    """Репозиторий, отслеживающий загруженные агрегаты."""

    def flush_changes(self) -> None: ...

    def collect_events(self) -> list[DomainEvent]: ...


class SqlAlchemyUnitOfWork:
    """Реализация Unit of Work поверх сессии SQLAlchemy.

    Одна единица работы — одна сессия — одна транзакция. Выход из контекста без
    явного commit откатывает изменения. Перед коммитом изменения агрегатов
    переносятся в ORM-модели, а их события накапливаются для публикации.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._code_repositories: SqlAlchemyCodeRepositoryRepository | None = None
        self._review_runs: SqlAlchemyReviewRunRepository | None = None
        self._collected_events: list[DomainEvent] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of Work используется вне контекстного менеджера")
        return self._session

    @property
    def code_repositories(self) -> SqlAlchemyCodeRepositoryRepository:
        if self._code_repositories is None:
            self._code_repositories = SqlAlchemyCodeRepositoryRepository(self.session)
        return self._code_repositories

    @property
    def review_runs(self) -> SqlAlchemyReviewRunRepository:
        if self._review_runs is None:
            self._review_runs = SqlAlchemyReviewRunRepository(self.session)
        return self._review_runs

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Вложенные Unit of Work запрещены")
        self._session = self._session_factory()
        self._reset_repositories()
        self._collected_events = []
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self.session
        try:
            await session.rollback()
        finally:
            await session.close()
            self._session = None
            self._reset_repositories()

    async def commit(self) -> None:
        self._absorb_aggregate_changes()
        await self.session.commit()

    async def rollback(self) -> None:
        self._collected_events = []
        await self.session.rollback()

    def collect_events(self) -> list[DomainEvent]:
        collected = self._collected_events
        self._collected_events = []
        return collected

    def record_events(self, events: list[DomainEvent]) -> None:
        self._collected_events.extend(events)

    def _active_repositories(self) -> list[TrackingRepository]:
        candidates: list[TrackingRepository | None] = [self._code_repositories, self._review_runs]
        return [repository for repository in candidates if repository is not None]

    def _absorb_aggregate_changes(self) -> None:
        for repository in self._active_repositories():
            repository.flush_changes()
            self._collected_events.extend(repository.collect_events())

    def _reset_repositories(self) -> None:
        self._code_repositories = None
        self._review_runs = None

from types import (
    TracebackType,
)
from typing import (
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

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Вложенные Unit of Work запрещены")
        self._session = self._session_factory()
        self._code_repositories = None
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
            self._code_repositories = None

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

    def _absorb_aggregate_changes(self) -> None:
        if self._code_repositories is None:
            return
        self._code_repositories.flush_changes()
        self._collected_events.extend(self._code_repositories.collect_events())

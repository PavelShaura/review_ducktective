from types import (
    TracebackType,
)
from typing import (
    Self,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.storage.memory.repositories import (
    InMemoryCodeRepositoryRepository,
    InMemoryReviewRunRepository,
)


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
        self.code_repositories.rollback()
        self.review_runs.rollback()

    async def commit(self) -> None:
        self._collect_from_repositories()
        self.code_repositories.commit()
        self.review_runs.commit()

    async def rollback(self) -> None:
        self._collected_events = []
        self.code_repositories.rollback()
        self.review_runs.rollback()

    def collect_events(self) -> list[DomainEvent]:
        collected = self._collected_events
        self._collected_events = []
        return collected

    def _collect_from_repositories(self) -> None:
        self._collected_events.extend(self.code_repositories.collect_events())
        self._collected_events.extend(self.review_runs.collect_events())

from types import (
    TracebackType,
)
from typing import (
    Protocol,
    Self,
    runtime_checkable,
)

from ducktective.core.code_repository.ports import (
    CodeRepositoryRepository,
)
from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.review.ports import (
    ReviewRunRepository,
)


@runtime_checkable
class UnitOfWork(Protocol):
    """Граница транзакции.

    Открывается use case'ом, не репозиторием. Выход из контекста без явного commit
    означает откат. Долгие операции — вызовы LLM, git, линтеров — выполняются вне
    открытой транзакции.
    """

    @property
    def code_repositories(self) -> CodeRepositoryRepository: ...

    @property
    def review_runs(self) -> ReviewRunRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    def collect_events(self) -> list[DomainEvent]:
        """События агрегатов, изменённых в этой транзакции."""
        ...


class EventPublisher(Protocol):
    async def publish(self, events: list[DomainEvent]) -> None: ...

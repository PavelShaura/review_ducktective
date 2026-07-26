from dataclasses import (
    dataclass,
    field,
)
from datetime import (
    UTC,
    datetime,
)
from uuid import (
    UUID,
    uuid4,
)


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Базовое событие домена. Публикуется Unit of Work после успешного коммита.

    Наследуется конкретными событиями и самостоятельно не используется.
    """

    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def event_name(self) -> str:
        return type(self).__name__

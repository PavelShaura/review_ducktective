from dataclasses import (
    dataclass,
    field,
)

from ducktective.core.events import (
    DomainEvent,
)


@dataclass(kw_only=True)
class AggregateRoot:
    """Корень агрегата.

    Накапливает доменные события; Unit of Work забирает их и публикует после
    успешного коммита.
    """

    pending_events: list[DomainEvent] = field(default_factory=list, repr=False, compare=False)

    def record_event(self, event: DomainEvent) -> None:
        self.pending_events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        collected = self.pending_events
        self.pending_events = []
        return collected

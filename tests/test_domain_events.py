from dataclasses import (
    dataclass,
)

from ducktective.core.aggregate import (
    AggregateRoot,
)
from ducktective.core.events import (
    DomainEvent,
)


@dataclass(frozen=True, kw_only=True)
class SomethingHappened(DomainEvent):
    payload: str


@dataclass(kw_only=True)
class SampleAggregate(AggregateRoot):
    name: str


def test_event_name_matches_class() -> None:
    event = SomethingHappened(payload="x")

    assert event.event_name == "SomethingHappened"


def test_occurred_at_is_timezone_aware() -> None:
    event = SomethingHappened(payload="x")

    assert event.occurred_at.tzinfo is not None


def test_aggregate_returns_events_once() -> None:
    aggregate = SampleAggregate(name="sample")
    aggregate.record_event(SomethingHappened(payload="first"))
    aggregate.record_event(SomethingHappened(payload="second"))

    assert len(aggregate.pull_events()) == 2
    assert aggregate.pull_events() == []

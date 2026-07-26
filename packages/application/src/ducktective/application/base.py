from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)


class TransactionalUseCase:
    """Базовый use case, владеющий границей транзакции.

    Наследники не вызывают commit напрямую: они выполняют работу внутри
    транзакции, а публикация доменных событий происходит после коммита.
    """

    def __init__(self, unit_of_work: UnitOfWork, event_publisher: EventPublisher) -> None:
        self._unit_of_work = unit_of_work
        self._event_publisher = event_publisher

    async def _commit_and_publish(self) -> None:
        collected_events = self._unit_of_work.collect_events()
        await self._unit_of_work.commit()
        await self._event_publisher.publish(collected_events)

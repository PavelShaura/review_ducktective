from ducktective.core.events import (
    DomainEvent,
)


class NullEventPublisher:
    """Публикация в никуда.

    Используется в автономном режиме, где подписчиков не существует: события
    домена всё равно собираются Unit of Work, но отправлять их некуда.
    """

    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, events: list[DomainEvent]) -> None:
        self.published.extend(events)

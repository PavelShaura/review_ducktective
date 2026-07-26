import json
from dataclasses import (
    asdict,
)
from datetime import (
    datetime,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
)
from uuid import (
    UUID,
)

from redis.asyncio import (
    Redis,
)

from ducktective.core.events import (
    DomainEvent,
)


DOMAIN_EVENT_CHANNEL = "ducktective:events"


class RedisEventPublisher:
    """Публикация доменных событий в Redis pub/sub.

    Вызывается только после успешного коммита: подписчики не должны видеть
    изменений, которые могут быть откачены.
    """

    def __init__(self, redis_client: Redis, channel: str = DOMAIN_EVENT_CHANNEL) -> None:
        self._redis_client = redis_client
        self._channel = channel

    async def publish(self, events: list[DomainEvent]) -> None:
        for event in events:
            payload = json.dumps(
                {"event": event.event_name, "data": asdict(event)},
                default=_serialize_value,
                ensure_ascii=False,
            )
            await self._redis_client.publish(self._channel, payload)


def _serialize_value(value: Any) -> str:
    if isinstance(value, UUID | Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Значение типа {type(value)!r} не сериализуется в событие")

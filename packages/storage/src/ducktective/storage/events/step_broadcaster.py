import json
from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    asynccontextmanager,
)
from typing import (
    Any,
)

from redis.asyncio import (
    Redis,
)

from ducktective.core.review.investigation import (
    RecordedStep,
)
from ducktective.core.types import (
    ReviewRunId,
)


CHANNEL_PREFIX = "ducktective:run"


def step_channel(run_id: ReviewRunId) -> str:
    """Канал одного прогона.

    Канал на прогон, а не общий на всех: смотрят за конкретным делом, и разбор
    чужих шагов на стороне подписчика — лишняя работа на каждом сообщении.
    """
    return f"{CHANNEL_PREFIX}:{run_id}:steps"


class RedisStepBroadcaster:
    """Рассылка шагов расследования тем, кто смотрит прямо сейчас.

    Отправляется то же, что уже записано, вместе с курсором: подписчик,
    подключившийся посреди прогона, дочитывает начало ленты обычным запросом
    и продолжает с этого места, не теряя и не задваивая шаги.
    """

    def __init__(self, redis_client: Redis) -> None:
        self._redis_client = redis_client

    async def publish(self, run_id: ReviewRunId, recorded: RecordedStep) -> None:
        await self._redis_client.publish(step_channel(run_id), _encode(recorded))


@asynccontextmanager
async def subscribe_to_steps(
    redis_client: Redis,
    run_id: ReviewRunId,
) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
    """Подписка на шаги прогона на время работы с ней."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(step_channel(run_id))
    try:
        yield _messages(pubsub)
    finally:
        await pubsub.unsubscribe(step_channel(run_id))
        await pubsub.aclose()  # type: ignore[no-untyped-call]


async def _messages(pubsub: Any) -> AsyncIterator[dict[str, Any]]:
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        payload: dict[str, Any] = json.loads(message["data"])
        yield payload


def _encode(recorded: RecordedStep) -> str:
    step = recorded.step
    return json.dumps(
        {
            "cursor": recorded.cursor,
            "file_path": step.file_path,
            "number": step.number,
            "kind": step.kind.value,
            "tool_name": step.tool_name,
            "arguments": step.arguments,
            "detail": step.detail,
            "duration_ms": step.duration_ms,
            "is_error": step.is_error,
        },
        ensure_ascii=False,
    )

import json
from typing import (
    Any,
)
from uuid import (
    uuid4,
)

from ducktective.core.review.investigation import (
    InvestigationStep,
    RecordedStep,
    StepKind,
)
from ducktective.core.types import (
    ReviewRunId,
)
from ducktective.storage.events.step_broadcaster import (
    RedisStepBroadcaster,
    step_channel,
    subscribe_to_steps,
)


RUN_ID = ReviewRunId(uuid4())


def build_recorded(cursor: int = 7) -> RecordedStep:
    return RecordedStep(
        cursor=cursor,
        step=InvestigationStep(
            file_path="app/service.py",
            number=2,
            kind=StepKind.TOOL_RESULT,
            tool_name="find_callers",
            detail="Источник: индекс проекта",
            duration_ms=16,
        ),
    )


class FakePubSub:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed.append(channel)

    async def aclose(self) -> None:
        self.closed = True

    async def listen(self) -> Any:
        for message in self.messages:
            yield message


class FakeRedis:
    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self.published: list[tuple[str, str]] = []
        self.pubsub_object = FakePubSub(messages or [])

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    def pubsub(self) -> FakePubSub:
        return self.pubsub_object


async def test_step_goes_to_the_channel_of_its_run() -> None:
    """Канал на прогон: разбирать чужие шаги подписчику незачем."""
    redis = FakeRedis()

    await RedisStepBroadcaster(redis).publish(RUN_ID, build_recorded())  # type: ignore[arg-type]

    channel, payload = redis.published[0]
    assert channel == step_channel(RUN_ID)
    assert json.loads(payload)["tool_name"] == "find_callers"


async def test_published_step_carries_its_cursor() -> None:
    """Подписчик, пришедший посреди прогона, по нему отличает новое от прочитанного."""
    redis = FakeRedis()

    await RedisStepBroadcaster(redis).publish(RUN_ID, build_recorded(cursor=42))  # type: ignore[arg-type]

    assert json.loads(redis.published[0][1])["cursor"] == 42


async def test_subscription_reads_messages_and_closes_itself() -> None:
    payload = json.dumps({"cursor": 1, "kind": "answer"})
    redis = FakeRedis(
        [
            {"type": "subscribe", "data": 1},
            {"type": "message", "data": payload},
        ]
    )

    received = []
    async with subscribe_to_steps(redis, RUN_ID) as stream:  # type: ignore[arg-type]
        async for message in stream:
            received.append(message)

    assert received == [{"cursor": 1, "kind": "answer"}]
    assert redis.pubsub_object.subscribed == [step_channel(RUN_ID)]
    assert redis.pubsub_object.unsubscribed == [step_channel(RUN_ID)]
    assert redis.pubsub_object.closed

import asyncio
from typing import (
    Any,
)
from uuid import (
    uuid4,
)

import pytest

from ducktective.core.types import (
    ReviewRunId,
)
from ducktective.storage.locks import (
    RedisRunLock,
    RunLockBusyError,
)


RUN_ID = ReviewRunId(uuid4())


class FakeRedis:
    """Столько Redis, сколько нужно блокировке: `set nx px` и два скрипта."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        px: int | None = None,
    ) -> bool | None:
        if nx and key in self.values:
            return None

        self.values[key] = value
        if px is not None:
            self.expirations[key] = px
        return True

    async def eval(self, script: str, numkeys: int, *args: Any) -> int:
        key, token = str(args[0]), str(args[1])
        if self.values.get(key) != token:
            return 0

        if "del" in script:
            del self.values[key]
            return 1

        self.expirations[key] = int(args[2])
        return 1


async def test_second_attempt_waits_for_the_first_to_let_go() -> None:
    redis_client = FakeRedis()
    lock = RedisRunLock(redis_client, wait_seconds=5.0, poll_seconds=0.01)  # type: ignore[arg-type]
    released = asyncio.Event()

    async def first() -> None:
        async with lock.hold(RUN_ID):
            await asyncio.sleep(0.05)
        released.set()

    async def second() -> None:
        await asyncio.sleep(0.01)
        async with lock.hold(RUN_ID):
            assert released.is_set()

    await asyncio.gather(first(), second())

    assert redis_client.values == {}


async def test_run_held_by_an_unresponsive_attempt_is_not_waited_forever() -> None:
    """Попытка, молчащая дольше отведённого, ждать себя не заслуживает.

    Слот воркера один на два прогона, и занять его ожиданием без конца
    значит остановить не только это дело.
    """
    redis_client = FakeRedis()
    lock = RedisRunLock(redis_client, wait_seconds=0.05, poll_seconds=0.01)  # type: ignore[arg-type]

    async with lock.hold(RUN_ID):
        with pytest.raises(RunLockBusyError):
            async with lock.hold(RUN_ID):
                pass


async def test_lock_is_released_after_a_failure() -> None:
    redis_client = FakeRedis()
    lock = RedisRunLock(redis_client, wait_seconds=0.0)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        async with lock.hold(RUN_ID):
            raise RuntimeError("прогон упал")

    assert redis_client.values == {}


async def test_hold_is_refreshed_while_the_work_goes_on() -> None:
    """Короткий срок и продление — иначе упавший воркер держит дело мёртвым."""
    redis_client = FakeRedis()
    lock = RedisRunLock(
        redis_client,  # type: ignore[arg-type]
        ttl_seconds=0.2,
        refresh_seconds=0.02,
        wait_seconds=0.0,
    )

    async with lock.hold(RUN_ID):
        await asyncio.sleep(0.05)
        key = next(iter(redis_client.values))
        assert redis_client.expirations[key] == 200


async def test_foreign_lock_is_not_taken_off() -> None:
    redis_client = FakeRedis()
    lock = RedisRunLock(redis_client, wait_seconds=0.0)  # type: ignore[arg-type]

    async with lock.hold(RUN_ID):
        key = next(iter(redis_client.values))
        redis_client.values[key] = "чужой держатель"

    assert redis_client.values[key] == "чужой держатель"

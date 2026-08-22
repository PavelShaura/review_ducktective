"""Право работать над прогоном — одно на всех.

Признак отмены отвечает на вопрос «мне пора уйти?», и отвечает не сразу:
попытка узнаёт о себе перед очередным обращением к модели, то есть с задержкой
до одного вызова. Пока она этого не узнала, второе задание по тому же делу
уже стартовало бы — и тогда на одном прогоне оказываются две попытки: обе
занимают слоты воркера, обе зовут модель и обе пишут в общий сохранённый ход.

Проверка такое предотвратить не может по построению, потому что смотрит назад.
Блокировка смотрит вперёд: новая попытка не начинает работу, пока прежняя
не отпустила прогон.
"""

import asyncio
from collections.abc import (
    AsyncIterator,
)
from contextlib import (
    asynccontextmanager,
    suppress,
)
from uuid import (
    uuid4,
)

from redis.asyncio import (
    Redis,
)

from ducktective.core.types import (
    ReviewRunId,
)


LOCK_TTL_SECONDS = 60.0
"""Насколько блокировка переживает того, кто её взял.

Срок короткий и продлевается по ходу работы, а не выставляется сразу
на всю длительность прогона: прогон идёт минутами и десятками минут, и
блокировка с таким сроком после падения воркера держала бы дело мёртвым
всё это время. Продление прекращается вместе с процессом само.
"""

LOCK_REFRESH_SECONDS = 20.0
"""Как часто держащий подтверждает, что жив. Втрое чаще срока — чтобы
пропущенное продление не стоило блокировки."""

LOCK_POLL_SECONDS = 2.0

RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""
"""Отпускает только свою блокировку.

Между чтением и удалением чужой процесс успевает взять освободившийся ключ,
и безусловный `del` снял бы блокировку, которую уже держит кто-то другой.
"""

REFRESH_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""
"""Продлевает только свою блокировку — по той же причине, что и снятие."""


class RunLockBusyError(RuntimeError):
    """Прогон занят другой попыткой, и она не отпустила его за отведённое время."""


class RedisRunLock:
    """Блокировка прогона на время работы над ним."""

    def __init__(
        self,
        redis_client: Redis,
        *,
        ttl_seconds: float = LOCK_TTL_SECONDS,
        wait_seconds: float = 0.0,
        refresh_seconds: float = LOCK_REFRESH_SECONDS,
        poll_seconds: float = LOCK_POLL_SECONDS,
    ) -> None:
        self._redis_client = redis_client
        self._ttl_seconds = ttl_seconds
        self._wait_seconds = wait_seconds
        self._refresh_seconds = refresh_seconds
        self._poll_seconds = poll_seconds

    @asynccontextmanager
    async def hold(self, run_id: ReviewRunId) -> AsyncIterator[None]:
        """Держит прогон за собой, пока идёт работа.

        Ожидание ограничено: прежняя попытка уходит на ближайшей проверке,
        и если она не ушла за отведённое время, значит дело не в задержке
        проверки, а в том, что попытка не отвечает вовсе. Ждать её дольше
        значит занимать слот воркера впустую.
        """
        key = _lock_key(run_id)
        token = uuid4().hex

        if not await self._acquire(key, token):
            raise RunLockBusyError(
                f"Прогон {run_id} занят прежней попыткой — она не освободила его "
                f"за {self._wait_seconds:.0f} с"
            )

        keeping = asyncio.create_task(self._keep(key, token))
        try:
            yield
        finally:
            keeping.cancel()
            with suppress(asyncio.CancelledError):
                await keeping
            await self._release(key, token)

    async def _acquire(self, key: str, token: str) -> bool:
        deadline = asyncio.get_running_loop().time() + self._wait_seconds
        while True:
            taken = await self._redis_client.set(
                key,
                token,
                nx=True,
                px=int(self._ttl_seconds * 1000),
            )
            if taken:
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(self._poll_seconds)

    async def _keep(self, key: str, token: str) -> None:
        """Продлевает срок, пока работа идёт.

        Продление тоже условное: истёкшую и перехваченную блокировку продлевать
        нельзя — иначе держащий отберёт её у того, кто взял её честно.
        """
        while True:
            await asyncio.sleep(self._refresh_seconds)
            await self._redis_client.eval(  # type: ignore[misc]
                REFRESH_SCRIPT,
                1,
                key,
                token,
                str(int(self._ttl_seconds * 1000)),
            )

    async def _release(self, key: str, token: str) -> None:
        await self._redis_client.eval(RELEASE_SCRIPT, 1, key, token)  # type: ignore[misc]


def _lock_key(run_id: ReviewRunId) -> str:
    return f"ducktective:run:{run_id}:lock"

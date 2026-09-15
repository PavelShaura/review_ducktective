from collections.abc import (
    Awaitable,
)
from dataclasses import (
    dataclass,
)
from typing import (
    Protocol,
)
from uuid import (
    UUID,
)

from arq.constants import (
    in_progress_key_prefix,
    job_key_prefix,
)
from arq.jobs import (
    deserialize_job_raw,
)

from ducktective.config.queues import (
    INDEX_QUEUE,
    INDEX_TASK_NAME,
)
from ducktective.core.types import (
    IndexSnapshotId,
    RepositoryId,
)


class QueueRedis(Protocol):
    """То немногое, что нужно от клиента Redis без декодирования ответов.

    Задачи arq лежат в pickle, и клиент с `decode_responses` их не прочтёт —
    поэтому очередь читается тем же клиентом, которым задачи и ставятся.
    """

    def zrange(self, name: str, start: int, end: int) -> Awaitable[list[bytes]]: ...

    def get(self, name: str) -> Awaitable[bytes | None]: ...

    def exists(self, *names: str) -> Awaitable[int]: ...


@dataclass(frozen=True, slots=True)
class QueuedBuild:
    repository_id: RepositoryId
    snapshot_id: IndexSnapshotId | None
    is_running: bool


class ArqIndexQueue:
    """Очередь сборок индекса глазами Redis: что воркер делает и кто ждёт.

    Состояние снапшота в базе говорит «в очереди», но не говорит, за кем:
    очередь живёт в Redis, а воркер берёт по одной сборке. Без этого
    «ждёт воркера» читалось как «воркер не запущен», когда он просто занят
    соседним репозиторием на полчаса.
    """

    def __init__(self, redis: QueueRedis) -> None:
        self._redis = redis

    async def builds(self) -> list[QueuedBuild]:
        """Сборки в порядке очереди: идущие первыми, затем ожидающие.

        Задача, чей ключ уже исчез — выполнена или снята между двумя
        чтениями, — пропускается: очередь читается без блокировки, и такое
        расхождение штатно.
        """
        job_ids = await self._redis.zrange(INDEX_QUEUE, 0, -1)
        running: list[QueuedBuild] = []
        waiting: list[QueuedBuild] = []

        for job_id in job_ids:
            key = job_id.decode()
            raw = await self._redis.get(job_key_prefix + key)
            if raw is None:
                continue
            function, args, _kwargs, _try, _enqueued = deserialize_job_raw(raw)
            if function != INDEX_TASK_NAME or not args:
                continue

            build = QueuedBuild(
                repository_id=RepositoryId(UUID(str(args[0]))),
                snapshot_id=_snapshot_id(args),
                is_running=bool(await self._redis.exists(in_progress_key_prefix + key)),
            )
            (running if build.is_running else waiting).append(build)

        return [*running, *waiting]


def _snapshot_id(args: tuple[object, ...]) -> IndexSnapshotId | None:
    if len(args) < 4 or not args[3]:
        return None
    return IndexSnapshotId(UUID(str(args[3])))

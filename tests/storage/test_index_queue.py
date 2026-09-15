import pickle
from uuid import (
    uuid4,
)

from arq.constants import (
    in_progress_key_prefix,
    job_key_prefix,
)

from ducktective.config.queues import (
    INDEX_QUEUE,
    INDEX_TASK_NAME,
)
from ducktective.storage.index_queue import (
    ArqIndexQueue,
)


class FakeRedis:
    """Ровно то, что arq оставляет в Redis: отсортированную очередь и ключи задач."""

    def __init__(self) -> None:
        self.queue: list[bytes] = []
        self.values: dict[str, bytes] = {}

    def enqueue(self, function: str, *args: str | None, running: bool = False) -> str:
        job_id = uuid4().hex
        self.queue.append(job_id.encode())
        self.values[job_key_prefix + job_id] = pickle.dumps(
            {"t": 0, "f": function, "a": args, "k": {}, "et": 0}
        )
        if running:
            self.values[in_progress_key_prefix + job_id] = b"1"
        return job_id

    async def zrange(self, name: str, start: int, end: int) -> list[bytes]:
        assert name == INDEX_QUEUE
        return list(self.queue)

    async def get(self, name: str) -> bytes | None:
        return self.values.get(name)

    async def exists(self, *names: str) -> int:
        return sum(1 for name in names if name in self.values)


async def test_running_build_comes_first_then_waiting_in_order() -> None:
    redis = FakeRedis()
    busy, first, second = str(uuid4()), str(uuid4()), str(uuid4())
    snapshots = [str(uuid4()) for _ in range(3)]
    redis.enqueue(INDEX_TASK_NAME, first, "tenant", "HEAD", snapshots[1], "")
    redis.enqueue(INDEX_TASK_NAME, busy, "tenant", "HEAD", snapshots[0], "", running=True)
    redis.enqueue(INDEX_TASK_NAME, second, "tenant", "HEAD", snapshots[2], "")

    builds = await ArqIndexQueue(redis).builds()

    assert [str(build.repository_id) for build in builds] == [busy, first, second]
    assert [build.is_running for build in builds] == [True, False, False]
    assert str(builds[1].snapshot_id) == snapshots[1]


async def test_foreign_and_vanished_jobs_are_skipped() -> None:
    """Между чтением очереди и ключа задача могла исполниться; чужие задачи не сборки."""
    redis = FakeRedis()
    gone = redis.enqueue(INDEX_TASK_NAME, str(uuid4()), "tenant", "HEAD", str(uuid4()), "")
    del redis.values[job_key_prefix + gone]
    redis.enqueue("forget_checkpoint_task", str(uuid4()), "tenant")
    kept = str(uuid4())
    redis.enqueue(INDEX_TASK_NAME, kept, "tenant", "HEAD", None, "")

    builds = await ArqIndexQueue(redis).builds()

    assert [str(build.repository_id) for build in builds] == [kept]
    assert builds[0].snapshot_id is None

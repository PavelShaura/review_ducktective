from dataclasses import (
    dataclass,
)
from datetime import (
    datetime,
)

from ducktective.core.indexing.entities import (
    IndexStats,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStage,
    SnapshotStatus,
)
from ducktective.core.types import (
    CommitSha,
    IndexSnapshotId,
)


@dataclass(frozen=True, kw_only=True)
class IndexStateView:
    """Состояние индекса репозитория для клиента.

    Показывать его нужно всегда: ревью без индекса работает в вырожденном
    режиме «только дифф», и человек должен видеть, на что смотрит.
    """

    snapshot_id: IndexSnapshotId | None = None
    status: SnapshotStatus | None = None
    stage: SnapshotStage | None = None
    commit_sha: CommitSha | None = None
    stats: IndexStats | None = None
    finished_at: datetime | None = None
    failure_reason: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status is SnapshotStatus.READY

    @property
    def is_running(self) -> bool:
        return self.status in {SnapshotStatus.PENDING, SnapshotStatus.RUNNING}

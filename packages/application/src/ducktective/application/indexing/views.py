from dataclasses import (
    dataclass,
    field,
)
from datetime import (
    datetime,
)

from ducktective.core.indexing.entities import (
    IndexStats,
)
from ducktective.core.indexing.ports import (
    VectorCoverage,
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
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_reason: str | None = None
    vectors: VectorCoverage = field(default_factory=VectorCoverage)
    """Покрытие фрагментов векторами.

    Снапшот помечается готовым до подсчёта векторов: символы и граф полезны
    сами по себе, а модель может быть недоступна. Значит, «индекс собран» и
    «поиск по смыслу работает» — разные состояния, и различать их приходится
    здесь."""

    embedding_stopped: bool = False
    context_ready: bool = False
    """Есть ли снапшот, из которого ревью может взять окружение.

    Отличается от `is_ready`: тот говорит про последний снапшот, а ревью
    работает с последним завершённым. Пока идёт пересборка, это разные
    вещи — и разница определяет, найдёт ревью вдвое меньше или столько же."""

    @property
    def is_ready(self) -> bool:
        return self.status is SnapshotStatus.READY

    @property
    def is_running(self) -> bool:
        return self.status in {SnapshotStatus.PENDING, SnapshotStatus.RUNNING}

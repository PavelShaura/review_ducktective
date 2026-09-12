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
    IndexTotals,
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
    embedding_backend: str = ""
    """Ключ сервера эмбеддингов, чей набор векторов ищет поиск."""

    totals: IndexTotals = field(default_factory=IndexTotals)
    """Что лежит в индексе сейчас — по базе, а не по последней сборке.

    `stats` описывают одну сборку: сколько она разобрала. Инкрементальная
    сборка без изменений разбирает ноль, и это не размер индекса."""

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

    @property
    def is_embedding(self) -> bool:
        """Идёт ли досчёт векторов прямо сейчас.

        Готовый снапшот на этапе досчёта без признака остановки и без
        причины отказа. Неполное покрытие само по себе досчётом не считается:
        векторы другой модели или прерванный досчёт выглядят так же.
        """
        return (
            self.status is SnapshotStatus.READY
            and self.stage is SnapshotStage.EMBEDDING
            and not self.embedding_stopped
            and self.failure_reason is None
        )

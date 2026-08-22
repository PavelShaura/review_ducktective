from dataclasses import (
    dataclass,
    field,
    replace,
)
from datetime import (
    UTC,
    datetime,
)
from typing import (
    Self,
)
from uuid import (
    uuid4,
)

from ducktective.core.aggregate import (
    AggregateRoot,
)
from ducktective.core.diff.value_objects import (
    LineRange,
)
from ducktective.core.exceptions import (
    InvariantViolationError,
)
from ducktective.core.indexing.events import (
    IndexSnapshotCreated,
    IndexSnapshotStatusChanged,
    SourceFileIndexed,
)
from ducktective.core.indexing.value_objects import (
    TERMINAL_SNAPSHOT_STATUSES,
    EdgeKind,
    SnapshotStage,
    SnapshotStatus,
    SymbolKind,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    CommitSha,
    ContentHash,
    IndexSnapshotId,
    QualifiedName,
    RepositoryId,
    SourceFileId,
    SymbolEdgeId,
)


@dataclass(kw_only=True)
class CodeSymbol:
    """Именованная единица кода: модуль, класс, функция, метод.

    Границы хранятся и в строках, и в байтах: строки нужны для пересечения
    с ханками диффа, байты — для точной вырезки текста из файла.
    """

    id: CodeSymbolId
    kind: SymbolKind
    name: str
    qualified_name: QualifiedName
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    content_hash: ContentHash
    parent_id: CodeSymbolId | None = None
    signature: str | None = None
    docstring: str | None = None

    @property
    def line_range(self) -> LineRange:
        return LineRange(start=self.start_line, end=self.end_line)

    def overlaps(self, lines: LineRange) -> bool:
        return self.line_range.overlaps(lines)


@dataclass(kw_only=True)
class CodeChunk:
    """Фрагмент, попадающий в векторный и лексический индекс.

    Хлебная крошка хранится рядом с содержимым: вырванный из файла фрагмент
    без указания, чей это метод, для модели почти бесполезен.
    """

    id: CodeChunkId
    content: str
    content_hash: ContentHash
    token_count: int
    start_line: int
    end_line: int
    breadcrumb: str
    symbol_id: CodeSymbolId | None = None


@dataclass(kw_only=True)
class SymbolEdge:
    """Связь между символами.

    Ребро существует и без разрешённой цели: имя, которое не удалось привязать
    к символу, сохраняется как есть. Гнаться за полнотой графа в динамическом
    языке — заведомо проигранная задача, а частичный граф уже полезен.
    """

    id: SymbolEdgeId
    repository_id: RepositoryId
    source_symbol_id: CodeSymbolId
    kind: EdgeKind
    target_symbol_id: CodeSymbolId | None = None
    target_qualified_name: QualifiedName | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.target_symbol_id is None and self.target_qualified_name is None:
            raise InvariantViolationError(
                "Ребро графа должно указывать либо на символ, либо на имя цели"
            )

    @property
    def is_resolved(self) -> bool:
        return self.target_symbol_id is not None


@dataclass(kw_only=True)
class SourceFile(AggregateRoot):
    """Проиндексированный файл вместе со своими символами и чанками.

    Агрегат совпадает с единицей переиндексации: при изменении файл
    разбирается целиком, поэтому частичное обновление символов невозможно
    по построению. Рёбра графа сюда не входят — они связывают символы
    разных файлов и живут отдельно.
    """

    id: SourceFileId
    repository_id: RepositoryId
    path: str
    language: str | None
    content_hash: ContentHash
    first_seen_snapshot_id: IndexSnapshotId
    last_seen_snapshot_id: IndexSnapshotId
    is_deleted: bool = False
    symbols: list[CodeSymbol] = field(default_factory=list)
    chunks: list[CodeChunk] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        repository_id: RepositoryId,
        path: str,
        language: str | None,
        content_hash: ContentHash,
        snapshot_id: IndexSnapshotId,
    ) -> Self:
        return cls(
            id=SourceFileId(uuid4()),
            repository_id=repository_id,
            path=path,
            language=language,
            content_hash=content_hash,
            first_seen_snapshot_id=snapshot_id,
            last_seen_snapshot_id=snapshot_id,
        )

    def replace_contents(
        self,
        *,
        content_hash: ContentHash,
        symbols: list[CodeSymbol],
        chunks: list[CodeChunk],
        snapshot_id: IndexSnapshotId,
    ) -> None:
        """Заменяет разбор файла результатом нового прохода."""
        self.content_hash = content_hash
        self.symbols = symbols
        self.chunks = chunks
        self.is_deleted = False
        self.last_seen_snapshot_id = snapshot_id
        self.record_event(
            SourceFileIndexed(
                snapshot_id=snapshot_id,
                repository_id=self.repository_id,
                path=self.path,
                symbols=len(symbols),
                chunks=len(chunks),
            )
        )

    def mark_seen(self, snapshot_id: IndexSnapshotId) -> None:
        """Отмечает, что файл не изменился и переразбирать его не нужно."""
        self.last_seen_snapshot_id = snapshot_id

    def mark_deleted(self, snapshot_id: IndexSnapshotId) -> None:
        """Помечает файл исчезнувшим, не стирая разбор.

        История нужна: находки прошлых прогонов ссылаются на эти символы,
        и удаление файла не должно превращать их в висячие ссылки.
        """
        self.is_deleted = True
        self.last_seen_snapshot_id = snapshot_id

    def symbols_covering(self, lines: LineRange) -> list[CodeSymbol]:
        """Символы, пересекающиеся с диапазоном строк.

        Точка входа ретривала от диффа: ханк превращается не в «строки 40–52»,
        а в «метод ReportBuilder.build».
        """
        return [symbol for symbol in self.symbols if symbol.overlaps(lines)]

    def find_symbol(self, qualified_name: QualifiedName) -> CodeSymbol | None:
        for symbol in self.symbols:
            if symbol.qualified_name == qualified_name:
                return symbol
        return None


@dataclass(frozen=True, kw_only=True)
class IndexStats:
    files_total: int = 0
    files_parsed: int = 0
    files_reused: int = 0
    files_stored: int = 0
    files_deleted: int = 0
    symbols: int = 0
    chunks: int = 0
    edges: int = 0
    edges_resolved: int = 0


@dataclass(kw_only=True)
class IndexSnapshot(AggregateRoot):
    """Состояние индекса репозитория на конкретной ревизии.

    Ревью работает против снапшота, а не против «текущего индекса»: иначе
    параллельная переиндексация меняла бы контекст посреди прогона.
    """

    id: IndexSnapshotId
    repository_id: RepositoryId
    commit_sha: CommitSha
    status: SnapshotStatus
    created_at: datetime
    parent_snapshot_id: IndexSnapshotId | None = None
    stage: SnapshotStage = SnapshotStage.PARSING
    embedding_stopped: bool = False
    stats: IndexStats = field(default_factory=IndexStats)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_reason: str | None = None

    @classmethod
    def create(
        cls,
        *,
        repository_id: RepositoryId,
        commit_sha: CommitSha,
        parent_snapshot_id: IndexSnapshotId | None = None,
    ) -> Self:
        snapshot = cls(
            id=IndexSnapshotId(uuid4()),
            repository_id=repository_id,
            commit_sha=commit_sha,
            status=SnapshotStatus.PENDING,
            created_at=datetime.now(UTC),
            parent_snapshot_id=parent_snapshot_id,
        )
        snapshot.record_event(
            IndexSnapshotCreated(
                snapshot_id=snapshot.id,
                repository_id=repository_id,
                commit_sha=commit_sha,
                parent_snapshot_id=parent_snapshot_id,
            )
        )
        return snapshot

    @property
    def is_finished(self) -> bool:
        return self.status in TERMINAL_SNAPSHOT_STATUSES

    @property
    def is_incremental(self) -> bool:
        return self.parent_snapshot_id is not None

    def mark_running(self) -> None:
        self._change_status(SnapshotStatus.RUNNING)
        self.started_at = datetime.now(UTC)

    def record_progress(self, *, files_total: int, files_parsed: int, files_reused: int) -> None:
        """Отмечает, сколько файлов уже разобрано.

        Индексация крупного репозитория идёт минутами, и без этого числа
        интерфейсу нечего показать, кроме бесконечного «собирается».
        """
        self.stats = IndexStats(
            files_total=files_total,
            files_parsed=files_parsed,
            files_reused=files_reused,
        )

    def record_stored(self, files_stored: int) -> None:
        """Отмечает, сколько разобранных файлов уже записано.

        Считается отдельно от разбора: разбор идёт по всем файлам дерева,
        а записывать нужно только изменившиеся, и одна шкала на два разных
        знаменателя показывала бы неправду.

        Прежние числа сохраняются — здесь известно только про запись.
        """
        self.stats = replace(self.stats, files_stored=files_stored)

    def enter_stage(self, stage: SnapshotStage) -> None:
        """Переключает этап работы.

        Шкала разбора доходит до конца задолго до окончания индексации:
        дальше идут запись и построение графа. Название этапа — единственное,
        что отличает долгую работу от зависшей.
        """
        self.stage = stage

    def stop_embedding(self) -> None:
        """Просит прекратить досчёт векторов.

        Отменять сам снапшот на этом этапе нельзя и не нужно: символы и граф
        записаны, он честно готов. Прекратить можно только продолжение —
        поэтому это отдельный признак, а не смена статуса.

        Посчитанное сохраняется: следующий запуск досчитает остаток.
        """
        if self.stage is not SnapshotStage.EMBEDDING:
            raise InvariantViolationError(f"Досчёт векторов не идёт: снапшот на этапе {self.stage}")
        self.embedding_stopped = True

    def record_embedding_failure(self, reason: str) -> None:
        """Отмечает, что векторы досчитать не удалось.

        Статус не меняется: символы и граф записаны, снапшот честно готов,
        и недоступность модели ничего из этого не отменяет — ради этого
        досчёт и вынесен из разбора. Но молчать нельзя: остановившийся
        досчёт неотличим от идущего, и доля посчитанных векторов замирает
        на месте, продолжая обещать поиск по смыслу, которого не будет.

        Причина пишется рядом со статусом, а не вместо него — тем же
        способом, каким прогон ревью отмечает частичную беду.
        """
        self.failure_reason = reason

    def cancel(self) -> None:
        """Помечает индексацию отменённой.

        Записанное откатывается само: всё пишется одной транзакцией в конце,
        а файлы отменённого снапшота не считаются разобранными — при
        следующем запуске они попадут в работу заново.
        """
        self._change_status(SnapshotStatus.CANCELLED)
        self.finished_at = datetime.now(UTC)

    @property
    def is_cancelled(self) -> bool:
        return self.status is SnapshotStatus.CANCELLED

    def mark_ready(self, stats: IndexStats) -> None:
        self._change_status(SnapshotStatus.READY)
        self.stats = stats
        self.finished_at = datetime.now(UTC)

    def mark_failed(self, reason: str) -> None:
        self._change_status(SnapshotStatus.FAILED)
        self.failure_reason = reason
        self.finished_at = datetime.now(UTC)

    def _change_status(self, status: SnapshotStatus) -> None:
        if self.is_finished:
            raise InvariantViolationError(
                f"Снапшот уже завершён со статусом {self.status}, переход в {status} невозможен"
            )
        if status is self.status:
            return

        previous_status = self.status
        self.status = status
        self.record_event(
            IndexSnapshotStatusChanged(
                snapshot_id=self.id,
                previous_status=previous_status,
                current_status=status,
            )
        )

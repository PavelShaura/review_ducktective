from uuid import (
    uuid4,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.indexing.entities import (
    CodeChunk,
    CodeSymbol,
    IndexSnapshot,
    SourceFile,
    SymbolEdge,
)
from ducktective.core.indexing.ports import (
    VectorCoverage,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStatus,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    ContentHash,
    EmbeddingModelId,
    IndexSnapshotId,
    QualifiedName,
    RepositoryId,
    ReviewRunId,
    TenantId,
)


class InMemoryCodeRepositoryRepository:
    """Репозиторий агрегата CodeRepository в памяти процесса.

    Добавленные агрегаты попадают в основное хранилище только после commit —
    так соблюдается тот же контракт, что и у реализации поверх SQLAlchemy.
    """

    def __init__(self) -> None:
        self._committed: dict[RepositoryId, CodeRepository] = {}
        self._pending: dict[RepositoryId, CodeRepository] = {}
        self._removed_events: list[DomainEvent] = []

    def add(self, repository: CodeRepository) -> None:
        self._pending[repository.id] = repository

    async def get(self, repository_id: RepositoryId) -> CodeRepository:
        repository = self._pending.get(repository_id) or self._committed.get(repository_id)
        if repository is None:
            raise EntityNotFoundError("CodeRepository", repository_id)
        return repository

    async def find_by_name(self, tenant_id: TenantId, name: str) -> CodeRepository | None:
        for repository in self._tracked():
            if repository.tenant_id == tenant_id and repository.name == name:
                return repository
        return None

    async def list_for_tenant(self, tenant_id: TenantId) -> list[CodeRepository]:
        return [repository for repository in self._tracked() if repository.tenant_id == tenant_id]

    async def remove(self, repository: CodeRepository) -> None:
        self._pending.pop(repository.id, None)
        self._committed.pop(repository.id, None)
        self._removed_events.extend(repository.pull_events())

    def commit(self) -> None:
        self._committed.update(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()

    def collect_events(self) -> list[DomainEvent]:
        collected = self._removed_events
        self._removed_events = []
        for repository in self._tracked():
            collected.extend(repository.pull_events())
        return collected

    def _tracked(self) -> list[CodeRepository]:
        return [*self._committed.values(), *self._pending.values()]


class InMemoryReviewRunRepository:
    """Репозиторий агрегата ReviewRun в памяти процесса."""

    def __init__(self) -> None:
        self._committed: dict[ReviewRunId, ReviewRun] = {}
        self._pending: dict[ReviewRunId, ReviewRun] = {}
        self._removed_events: list[DomainEvent] = []

    def add(self, run: ReviewRun) -> None:
        self._pending[run.id] = run

    async def get(self, run_id: ReviewRunId) -> ReviewRun:
        run = self._pending.get(run_id) or self._committed.get(run_id)
        if run is None:
            raise EntityNotFoundError("ReviewRun", run_id)
        return run

    async def list_for_repository(
        self,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[ReviewRun]:
        runs = [run for run in self._tracked() if run.repository_id == repository_id]
        return runs[:limit]

    async def remove(self, run: ReviewRun) -> None:
        self._pending.pop(run.id, None)
        self._committed.pop(run.id, None)
        self._removed_events.extend(run.pull_events())

    def commit(self) -> None:
        self._committed.update(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()

    def collect_events(self) -> list[DomainEvent]:
        collected = self._removed_events
        self._removed_events = []
        for run in self._tracked():
            collected.extend(run.pull_events())
        return collected

    def _tracked(self) -> list[ReviewRun]:
        return [*self._committed.values(), *self._pending.values()]


class InMemoryIndexSnapshotRepository:
    """Репозиторий агрегата IndexSnapshot в памяти процесса."""

    def __init__(self) -> None:
        self._committed: dict[IndexSnapshotId, IndexSnapshot] = {}
        self._pending: dict[IndexSnapshotId, IndexSnapshot] = {}

    def add(self, snapshot: IndexSnapshot) -> None:
        self._pending[snapshot.id] = snapshot

    async def get(self, snapshot_id: IndexSnapshotId) -> IndexSnapshot:
        snapshot = self._pending.get(snapshot_id) or self._committed.get(snapshot_id)
        if snapshot is None:
            raise EntityNotFoundError("IndexSnapshot", snapshot_id)
        return snapshot

    async def find_latest_ready(self, repository_id: RepositoryId) -> IndexSnapshot | None:
        ready = [
            snapshot
            for snapshot in self._tracked()
            if snapshot.repository_id == repository_id
            and snapshot.status is SnapshotStatus.READY
            and snapshot.finished_at is not None
        ]
        if not ready:
            return None
        return max(ready, key=lambda snapshot: snapshot.finished_at or snapshot.created_at)

    async def find_latest(self, repository_id: RepositoryId) -> IndexSnapshot | None:
        snapshots = [
            snapshot for snapshot in self._tracked() if snapshot.repository_id == repository_id
        ]
        if not snapshots:
            return None
        return max(snapshots, key=lambda snapshot: snapshot.created_at)

    async def remove_for_repository(self, repository_id: RepositoryId) -> int:
        removed = [
            snapshot_id
            for snapshot_id, snapshot in [
                *self._committed.items(),
                *self._pending.items(),
            ]
            if snapshot.repository_id == repository_id
        ]
        for snapshot_id in removed:
            self._committed.pop(snapshot_id, None)
            self._pending.pop(snapshot_id, None)
        return len(removed)

    def ready_ids(self, repository_id: RepositoryId) -> set[IndexSnapshotId]:
        """Снапшоты, доведённые до конца."""
        return {
            snapshot.id
            for snapshot in self._tracked()
            if snapshot.repository_id == repository_id and snapshot.status is SnapshotStatus.READY
        }

    def commit(self) -> None:
        self._committed.update(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for snapshot in self._tracked():
            collected.extend(snapshot.pull_events())
        return collected

    def _tracked(self) -> list[IndexSnapshot]:
        return [*self._committed.values(), *self._pending.values()]


class InMemorySourceFileRepository:
    """Репозиторий агрегата SourceFile в памяти процесса.

    Смотрит в репозиторий снапшотов, чтобы отличать разобранное начисто
    от оставшегося после прерванного прогона.
    """

    def __init__(self, snapshots: InMemoryIndexSnapshotRepository) -> None:
        self._snapshots = snapshots
        self._committed: dict[tuple[RepositoryId, str], SourceFile] = {}
        self._pending: dict[tuple[RepositoryId, str], SourceFile] = {}

    def add(self, source_file: SourceFile) -> None:
        self._pending[(source_file.repository_id, source_file.path)] = source_file

    async def find_by_path(self, repository_id: RepositoryId, path: str) -> SourceFile | None:
        key = (repository_id, path)
        return self._pending.get(key) or self._committed.get(key)

    async def load_many(
        self,
        repository_id: RepositoryId,
        paths: list[str],
    ) -> dict[str, SourceFile]:
        wanted = set(paths)
        return {
            source_file.path: source_file
            for source_file in self._tracked()
            if source_file.repository_id == repository_id and source_file.path in wanted
        }

    async def list_paths(self, repository_id: RepositoryId) -> dict[str, str]:
        ready = self._snapshots.ready_ids(repository_id)
        return {
            source_file.path: source_file.content_hash
            for source_file in self._tracked()
            if source_file.repository_id == repository_id
            and not source_file.is_deleted
            and source_file.last_seen_snapshot_id in ready
        }

    def live_files(self, repository_id: RepositoryId) -> list[SourceFile]:
        """Неудалённые файлы репозитория."""
        return [
            source_file
            for source_file in self._tracked()
            if source_file.repository_id == repository_id and not source_file.is_deleted
        ]

    def symbols_of(self, repository_id: RepositoryId) -> list[CodeSymbol]:
        """Все символы репозитория. Нужны рёбрам для разрешения имён."""
        return [
            symbol
            for source_file in self._tracked()
            if source_file.repository_id == repository_id
            for symbol in source_file.symbols
        ]

    def commit(self) -> None:
        self._committed.update(self._pending)
        self._pending.clear()

    def rollback(self) -> None:
        self._pending.clear()

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for source_file in self._tracked():
            collected.extend(source_file.pull_events())
        return collected

    def _tracked(self) -> list[SourceFile]:
        return [*self._committed.values(), *self._pending.values()]


class InMemorySymbolEdgeRepository:
    """Рёбра графа символов в памяти процесса.

    Смотрит в репозиторий файлов, чтобы разрешать имена: символы живут там,
    и второй их копии заводить незачем.
    """

    def __init__(self, source_files: InMemorySourceFileRepository) -> None:
        self._source_files = source_files
        self._edges: list[SymbolEdge] = []

    async def replace_for_symbols(
        self,
        repository_id: RepositoryId,
        symbol_ids: list[CodeSymbolId],
        edges: list[SymbolEdge],
    ) -> None:
        obsolete = set(symbol_ids)
        self._edges = [
            edge
            for edge in self._edges
            if edge.repository_id != repository_id or edge.source_symbol_id not in obsolete
        ]
        self._edges.extend(edges)

    async def refresh_statistics(self) -> None:
        """В памяти планировать нечего."""

    async def resolve_pending(self, repository_id: RepositoryId) -> int:
        known = self._known_symbols(repository_id)

        resolved = 0
        for edge in self._edges:
            if edge.repository_id != repository_id or edge.is_resolved:
                continue

            symbol_id = known.get(edge.target_qualified_name or QualifiedName(""))
            if symbol_id is not None:
                edge.target_symbol_id = symbol_id
                resolved += 1
        return resolved

    def _known_symbols(self, repository_id: RepositoryId) -> dict[QualifiedName, CodeSymbolId]:
        known: dict[QualifiedName, CodeSymbolId] = {}
        for symbol in self._source_files.symbols_of(repository_id):
            known.setdefault(symbol.qualified_name, symbol.id)
        return known

    async def list_incoming(self, symbol_id: CodeSymbolId) -> list[SymbolEdge]:
        return [edge for edge in self._edges if edge.target_symbol_id == symbol_id]

    async def list_outgoing(self, symbol_id: CodeSymbolId) -> list[SymbolEdge]:
        return [edge for edge in self._edges if edge.source_symbol_id == symbol_id]

    def commit(self) -> None:
        """Рёбра пишутся сразу: отдельного состояния для фиксации нет."""

    def rollback(self) -> None:
        """Откат рёбер не поддерживается — см. ограничение InMemoryUnitOfWork."""

    def collect_events(self) -> list[DomainEvent]:
        return []


class InMemoryEmbeddingStore:
    """Векторы чанков в памяти процесса.

    Существует ради автономного режима и тестов: настоящий поиск по векторам
    здесь не нужен, нужен тот же контракт хранения.
    """

    def __init__(self, source_files: InMemorySourceFileRepository) -> None:
        self._source_files = source_files
        self._models: dict[str, EmbeddingModelId] = {}
        self._vectors: dict[tuple[EmbeddingModelId, CodeChunkId], list[float]] = {}

    async def count_coverage(self, repository_id: RepositoryId) -> VectorCoverage:
        chunk_ids = {
            chunk.id
            for source_file in self._source_files.live_files(repository_id)
            for chunk in source_file.chunks
        }
        embedded = {chunk_id for _, chunk_id in self._vectors}
        return VectorCoverage(
            chunks=len(chunk_ids),
            embedded=len(chunk_ids & embedded),
        )

    async def register_model(self, name: str, dimensions: int) -> EmbeddingModelId:
        return self._models.setdefault(name, EmbeddingModelId(uuid4()))

    async def missing_chunks(
        self,
        repository_id: RepositoryId,
        model_id: EmbeddingModelId,
    ) -> list[tuple[CodeChunkId, ContentHash, str]]:
        return [
            (chunk.id, chunk.content_hash, chunk.content)
            for chunk in self._chunks_of(repository_id)
            if (model_id, chunk.id) not in self._vectors
        ]

    async def reuse_by_hash(
        self,
        repository_id: RepositoryId,
        model_id: EmbeddingModelId,
    ) -> int:
        known: dict[ContentHash, list[float]] = {}
        for chunk in self._chunks_of(repository_id):
            vector = self._vectors.get((model_id, chunk.id))
            if vector is not None:
                known.setdefault(chunk.content_hash, vector)

        reused = 0
        for chunk in self._chunks_of(repository_id):
            if (model_id, chunk.id) in self._vectors:
                continue
            vector = known.get(chunk.content_hash)
            if vector is not None:
                self._vectors[(model_id, chunk.id)] = vector
                reused += 1
        return reused

    async def store(
        self,
        model_id: EmbeddingModelId,
        vectors: list[tuple[CodeChunkId, list[float]]],
    ) -> None:
        for chunk_id, vector in vectors:
            self._vectors[(model_id, chunk_id)] = vector

    def commit(self) -> None:
        """Векторы пишутся сразу: отдельного состояния для фиксации нет."""

    def rollback(self) -> None:
        """Откат векторов не поддерживается — см. ограничение InMemoryUnitOfWork."""

    def collect_events(self) -> list[DomainEvent]:
        return []

    def _chunks_of(self, repository_id: RepositoryId) -> list[CodeChunk]:
        return [
            chunk
            for source_file in self._source_files.live_files(repository_id)
            for chunk in source_file.chunks
        ]

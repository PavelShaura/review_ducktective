from dataclasses import (
    dataclass,
)
from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.core.diff.languages import (
    detect_language,
)
from ducktective.core.diff.ports import (
    VcsProvider,
)
from ducktective.core.indexing.entities import (
    IndexSnapshot,
    IndexStats,
    SourceFile,
    SymbolEdge,
)
from ducktective.core.indexing.ports import (
    CodeParser,
    ParsedFile,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStage,
    SnapshotStatus,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.types import (
    CommitSha,
    ContentHash,
    IndexSnapshotId,
    RepositoryId,
    SymbolEdgeId,
    TenantId,
)


PROGRESS_EVERY = 25

STORE_BATCH_SIZE = 200
"""Сколько разобранных файлов пишется одной транзакцией.

Меньше — чаще коммиты и точнее шкала, больше — меньше накладных расходов.
Двести файлов дают заметное движение на крупном репозитории, не превращая
запись в тысячи транзакций."""


class IndexingCancelledError(ApplicationError):
    """Индексацию попросили прекратить.

    Записанное откатывается вместе с транзакцией: до самого конца работа
    идёт в памяти, а в базу ложится одной операцией.
    """

    def __init__(self) -> None:
        super().__init__("Индексация отменена")


@dataclass(frozen=True, kw_only=True)
class BuildIndexCommand:
    """Задание на сборку.

    Снапшот назван, когда задачу ставил интерфейс: он завёл его заранее,
    чтобы очередь была видна и отменяема. У CLI его нет — там задача идёт
    прямо в работу.
    """

    tenant_id: TenantId
    repository_id: RepositoryId
    revision: str = "HEAD"
    snapshot_id: IndexSnapshotId | None = None


@dataclass(frozen=True, kw_only=True)
class IndexOutcome:
    """Итог индексации вместе с тем, что удалось не делать."""

    snapshot: IndexSnapshot
    stats: IndexStats
    unreadable: tuple[str, ...] = ()

    @property
    def is_incremental(self) -> bool:
        return self.snapshot.is_incremental


@dataclass(frozen=True, kw_only=True)
class _PendingFile:
    path: str
    language: str
    content_hash: ContentHash
    parsed: ParsedFile


class BuildIndex(TransactionalUseCase):
    """Строит снапшот индекса репозитория на заданной ревизии.

    Транзакция не удерживается на время обхода git и разбора файлов: снапшот
    создаётся и фиксируется, работа идёт вне транзакции, результат пишется
    короткими транзакциями.

    Символы и рёбра пишутся раздельно и в таком порядке: ребро замыкается на
    символ по имени, а искать его можно только среди уже сохранённых.

    Инкрементальность держится на хешах, которые отдаёт сама система контроля
    версий: файл с прежним хешем не читается и не разбирается вовсе.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        vcs_provider: VcsProvider,
        parser: CodeParser,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._vcs_provider = vcs_provider
        self._parser = parser

    async def execute(self, command: BuildIndexCommand) -> IndexOutcome:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(command.repository_id)
            if repository.tenant_id != command.tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            repository_path = repository.local_path
            previous = await self._unit_of_work.index_snapshots.find_latest_ready(
                command.repository_id
            )
            known_hashes = await self._unit_of_work.source_files.list_paths(command.repository_id)
            queued = await self._queued_snapshot(command)
            queued_sha = queued.commit_sha if queued else None

        commit_sha = queued_sha or await self._vcs_provider.resolve_revision(
            repository_path,
            command.revision,
        )

        async with self._unit_of_work:
            snapshot_id = await self._start_snapshot(
                command,
                commit_sha=commit_sha,
                parent_id=previous.id if previous else None,
            )
            await self._commit_and_publish()

        try:
            return await self._index(
                command, snapshot_id, repository_path, commit_sha, known_hashes
            )
        except IndexingCancelledError:
            raise
        except Exception as error:
            await self._mark_failed(snapshot_id, error)
            raise

    async def _queued_snapshot(self, command: BuildIndexCommand) -> IndexSnapshot | None:
        """Снапшот, заведённый постановкой в очередь, если он ещё ждёт работы.

        Отменённый здесь не возвращается, и это главное: задача остаётся
        в очереди и после отмены — прекратить её можно только тем, что воркер
        посмотрит на состояние снапшота, за которым его позвали.
        """
        if command.snapshot_id is None:
            return None

        snapshot = await self._unit_of_work.index_snapshots.get(command.snapshot_id)
        if snapshot.status is SnapshotStatus.CANCELLED:
            raise IndexingCancelledError

        return snapshot if snapshot.status is SnapshotStatus.PENDING else None

    async def _start_snapshot(
        self,
        command: BuildIndexCommand,
        *,
        commit_sha: CommitSha,
        parent_id: IndexSnapshotId | None,
    ) -> IndexSnapshotId:
        """Переводит в работу снапшот, заведённый при постановке в очередь.

        Интерфейс заводит его заранее, чтобы очередь была видна и отменяема;
        CLI ставит задачу напрямую, и там заводить снапшот некому. Оба случая
        должны приводить к одному состоянию, поэтому здесь либо подхват,
        либо создание.
        """
        queued = await self._queued_snapshot(command)
        if queued is not None:
            queued.mark_running()
            return queued.id

        snapshot = IndexSnapshot.create(
            repository_id=command.repository_id,
            commit_sha=commit_sha,
            parent_snapshot_id=parent_id,
        )
        snapshot.mark_running()
        self._unit_of_work.index_snapshots.add(snapshot)
        return snapshot.id

    async def _index(
        self,
        command: BuildIndexCommand,
        snapshot_id: IndexSnapshotId,
        repository_path: Path,
        commit_sha: CommitSha,
        known_hashes: dict[str, str],
    ) -> IndexOutcome:
        tree = await self._vcs_provider.list_tree(repository_path, commit_sha)
        supported = {
            path: file_hash
            for path, file_hash in tree.items()
            if self._parser.supports(detect_language(path))
        }

        pending, unchanged, unreadable = await self._parse_changed(
            repository_path,
            commit_sha,
            supported,
            known_hashes,
            snapshot_id=snapshot_id,
        )
        vanished = [path for path in known_hashes if path not in supported]

        await self._enter_stage(snapshot_id, SnapshotStage.STORING)
        return await self._store(
            command.repository_id,
            snapshot_id,
            pending=pending,
            unchanged=unchanged,
            vanished=vanished,
            unreadable=unreadable,
            files_total=len(supported),
        )

    async def _save_progress(
        self,
        snapshot_id: IndexSnapshotId,
        *,
        files_total: int,
        files_parsed: int,
        files_reused: int,
    ) -> None:
        """Сохраняет счёт разобранных файлов и сверяется с просьбой прекратить.

        Пишется не на каждый файл, а раз в несколько десятков: индексация
        и так работает пачками, а транзакция на каждый файл стоила бы дороже
        самой пользы от точной шкалы. Здесь же удобно заметить отмену —
        отдельный опрос ради неё был бы лишним.
        """
        async with self._unit_of_work:
            snapshot = await self._unit_of_work.index_snapshots.get(snapshot_id)
            if snapshot.is_cancelled:
                raise IndexingCancelledError

            snapshot.record_progress(
                files_total=files_total,
                files_parsed=files_parsed,
                files_reused=files_reused,
            )
            await self._unit_of_work.commit()

    async def _enter_stage(self, snapshot_id: IndexSnapshotId, stage: SnapshotStage) -> None:
        async with self._unit_of_work:
            snapshot = await self._unit_of_work.index_snapshots.get(snapshot_id)
            if snapshot.is_cancelled:
                raise IndexingCancelledError

            snapshot.enter_stage(stage)
            await self._unit_of_work.commit()

    async def _mark_failed(self, snapshot_id: IndexSnapshotId, error: Exception) -> None:
        """Переводит снапшот в состояние ошибки.

        Без этого прерванный прогон навсегда остаётся «в работе»: интерфейс
        показывает бесконечную сборку, а следующая попытка выглядит как
        вторая параллельная. Отдельная транзакция нужна потому, что упасть
        могла как раз предыдущая.
        """
        try:
            async with self._unit_of_work:
                snapshot = await self._unit_of_work.index_snapshots.get(snapshot_id)
                if not snapshot.is_finished:
                    snapshot.mark_failed(str(error))
                await self._commit_and_publish()
        except Exception:
            return

    async def _parse_changed(
        self,
        repository_path: Path,
        commit_sha: str,
        supported: dict[str, ContentHash],
        known_hashes: dict[str, str],
        *,
        snapshot_id: IndexSnapshotId,
    ) -> tuple[list[_PendingFile], list[str], list[str]]:
        pending: list[_PendingFile] = []
        unchanged: list[str] = []
        unreadable: list[str] = []

        for number, (path, file_hash) in enumerate(supported.items(), start=1):
            if number % PROGRESS_EVERY == 0:
                await self._save_progress(
                    snapshot_id,
                    files_total=len(supported),
                    files_parsed=len(pending),
                    files_reused=len(unchanged),
                )

            if known_hashes.get(path) == file_hash:
                unchanged.append(path)
                continue

            content = await self._vcs_provider.get_file_content(
                repository_path,
                revision=commit_sha,
                path=path,
            )
            if content is None:
                unreadable.append(path)
                continue

            language = detect_language(path)
            pending.append(
                _PendingFile(
                    path=path,
                    language=language or "",
                    content_hash=file_hash,
                    parsed=self._parser.parse(path=path, content=content),
                )
            )

        return pending, unchanged, unreadable

    async def _store(
        self,
        repository_id: RepositoryId,
        snapshot_id: IndexSnapshotId,
        *,
        pending: list[_PendingFile],
        unchanged: list[str],
        vanished: list[str],
        unreadable: list[str],
        files_total: int,
    ) -> IndexOutcome:
        for start in range(0, len(pending), STORE_BATCH_SIZE):
            batch = pending[start : start + STORE_BATCH_SIZE]
            await self._store_batch(repository_id, snapshot_id, batch=batch, stored=start)

        async with self._unit_of_work:
            known = await self._unit_of_work.source_files.load_many(
                repository_id,
                unchanged + vanished,
            )
            _mark_seen(known, unchanged, snapshot_id)
            _mark_vanished(known, vanished, snapshot_id)
            await self._commit_and_publish()

        await self._enter_stage(snapshot_id, SnapshotStage.LINKING)

        async with self._unit_of_work:
            await self._write_edges(repository_id, pending)
            await self._commit_and_publish()

        async with self._unit_of_work:
            await self._unit_of_work.symbol_edges.refresh_statistics()
            await self._unit_of_work.commit()

        async with self._unit_of_work:
            snapshot = await self._unit_of_work.index_snapshots.get(snapshot_id)
            if snapshot.is_cancelled:
                raise IndexingCancelledError

            resolved = await self._unit_of_work.symbol_edges.resolve_pending(repository_id)

            stats = IndexStats(
                files_total=files_total,
                files_parsed=len(pending),
                files_reused=len(unchanged),
                files_stored=len(pending),
                files_deleted=len(vanished),
                symbols=sum(len(item.parsed.symbols) for item in pending),
                chunks=sum(len(item.parsed.chunks) for item in pending),
                edges=sum(len(item.parsed.references) for item in pending),
                edges_resolved=resolved,
            )
            snapshot.mark_ready(stats)
            await self._commit_and_publish()

            return IndexOutcome(
                snapshot=snapshot,
                stats=stats,
                unreadable=tuple(unreadable),
            )

    async def _store_batch(
        self,
        repository_id: RepositoryId,
        snapshot_id: IndexSnapshotId,
        *,
        batch: list[_PendingFile],
        stored: int,
    ) -> None:
        """Записывает часть разобранных файлов и отмечает продвижение.

        Запись разбита на пачки не ради памяти, а ради видимости: одной
        транзакцией на тысячи файлов интерфейс получал застывшую шкалу
        и выглядел зависшим на самом долгом этапе.

        Незавершённый прогон оставляет записанное в базе, и это безопасно:
        разобранными считаются только файлы завершённых снапшотов, поэтому
        следующий запуск перечитает их заново.
        """
        async with self._unit_of_work:
            snapshot = await self._unit_of_work.index_snapshots.get(snapshot_id)
            if snapshot.is_cancelled:
                raise IndexingCancelledError

            known = await self._unit_of_work.source_files.load_many(
                repository_id,
                [item.path for item in batch],
            )

            for item in batch:
                source_file = known.get(item.path)
                if source_file is None:
                    source_file = SourceFile.create(
                        repository_id=repository_id,
                        path=item.path,
                        language=item.language,
                        content_hash=item.content_hash,
                        snapshot_id=snapshot_id,
                    )
                    self._unit_of_work.source_files.add(source_file)

                source_file.replace_contents(
                    content_hash=item.content_hash,
                    symbols=item.parsed.symbols,
                    chunks=item.parsed.chunks,
                    snapshot_id=snapshot_id,
                )

            snapshot.record_stored(stored + len(batch))
            await self._commit_and_publish()

    async def _write_edges(
        self,
        repository_id: RepositoryId,
        pending: list[_PendingFile],
    ) -> None:
        """Перекладывает ссылки разобранных файлов в граф.

        Рёбра пишутся неразрешёнными, а замыкаются отдельным проходом:
        цель ссылки может лежать в файле, который разобран позже источника,
        либо появиться только в этом прогоне.

        Запись и замыкание разнесены по транзакциям не ради красоты. Пока
        рёбра лежат незакоммиченными, планировщик их не видит: статистика
        обновляется только по видимым данным, и запрос замыкания строил план
        на «в таблице три тысячи рёбер» вместо ста тысяч, и замыкание
        обходилось часом работы вместо секунд.
        """
        edges = [
            SymbolEdge(
                id=SymbolEdgeId(uuid4()),
                repository_id=repository_id,
                source_symbol_id=reference.source_symbol_id,
                kind=reference.kind,
                target_qualified_name=reference.target_name,
                confidence=reference.confidence,
            )
            for item in pending
            for reference in item.parsed.references
        ]
        symbol_ids = [symbol.id for item in pending for symbol in item.parsed.symbols]

        await self._unit_of_work.symbol_edges.replace_for_symbols(
            repository_id,
            symbol_ids,
            edges,
        )


def _mark_seen(
    known: dict[str, SourceFile],
    paths: list[str],
    snapshot_id: IndexSnapshotId,
) -> None:
    for path in paths:
        source_file = known.get(path)
        if source_file is not None:
            source_file.mark_seen(snapshot_id)


def _mark_vanished(
    known: dict[str, SourceFile],
    paths: list[str],
    snapshot_id: IndexSnapshotId,
) -> None:
    for path in paths:
        source_file = known.get(path)
        if source_file is not None:
            source_file.mark_deleted(snapshot_id)

from sqlalchemy import (
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.indexing.entities import (
    IndexSnapshot,
    SourceFile,
    SymbolEdge,
)
from ducktective.core.indexing.ports import (
    IndexTotals,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStatus,
    SymbolKind,
)
from ducktective.core.types import (
    CodeSymbolId,
    IndexSnapshotId,
    RepositoryId,
)
from ducktective.storage.mappers import indexing as mapper
from ducktective.storage.models.indexing import (
    ChunkEmbeddingModel,
    CodeChunkModel,
    CodeSymbolModel,
    IndexSnapshotModel,
    SourceFileModel,
    SymbolEdgeModel,
)


SUFFIX_MATCH_CONFIDENCE = 0.3

DELETE_BATCH_SIZE = 10_000
LOAD_BATCH_SIZE = 5_000
"""Сколько идентификаторов кладётся в один `IN`.

Postgres принимает не больше 32767 параметров на запрос. При полной
индексации крупного репозитория символов оказывается больше, и запрос
падает целиком — поэтому удаление идёт пачками.
"""


class SqlAlchemyIndexSnapshotRepository:
    """Репозиторий агрегата IndexSnapshot."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[IndexSnapshotId, tuple[IndexSnapshot, IndexSnapshotModel]] = {}

    def add(self, snapshot: IndexSnapshot) -> None:
        model = mapper.snapshot_to_model(snapshot)
        self._session.add(model)
        self._identity_map[snapshot.id] = (snapshot, model)

    async def get(self, snapshot_id: IndexSnapshotId) -> IndexSnapshot:
        tracked = self._identity_map.get(snapshot_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(IndexSnapshotModel, snapshot_id)
        if model is None:
            raise EntityNotFoundError("IndexSnapshot", snapshot_id)
        return self._track(model)

    async def find_latest_ready(self, repository_id: RepositoryId) -> IndexSnapshot | None:
        statement = (
            select(IndexSnapshotModel)
            .where(
                IndexSnapshotModel.repository_id == repository_id,
                IndexSnapshotModel.status == SnapshotStatus.READY,
            )
            .order_by(IndexSnapshotModel.finished_at.desc())
            .limit(1)
        )
        model = (await self._session.execute(statement)).scalars().first()
        return None if model is None else self._track(model)

    async def find_latest(self, repository_id: RepositoryId) -> IndexSnapshot | None:
        statement = (
            select(IndexSnapshotModel)
            .where(IndexSnapshotModel.repository_id == repository_id)
            .order_by(IndexSnapshotModel.created_at.desc())
            .limit(1)
        )
        model = (await self._session.execute(statement)).scalars().first()
        return None if model is None else self._track(model)

    async def remove_for_repository(self, repository_id: RepositoryId) -> int:
        """Удаляет снапшоты репозитория, а с ними и весь индекс.

        Порядок задан явно, хотя схема убрала бы всё каскадом сама: каскад
        в Postgres — это триггер на каждую строку, и снапшоты крупного
        репозитория разворачиваются в четверть миллиона удалений по одному.
        Замерено:
        76 секунд каскадом против доли секунды перечислением, при том что
        индексы на внешних ключах уже стояли.

        Дубль знания о порядке — цена, заплаченная сознательно: схема
        остаётся источником правды о связях, а здесь их обход выражен
        множествами, потому что по одной строке это слишком медленно
        для действия, за которым ждут у экрана.

        Отслеживаемые агрегаты забываются: после удаления их нельзя писать
        обратно, а `flush_changes` попыталась бы.
        """
        belongs = IndexSnapshotModel.repository_id == repository_id
        counted = await self._session.execute(
            select(func.count()).select_from(IndexSnapshotModel).where(belongs)
        )
        removed = int(counted.scalar_one())

        chunks_of_repository = select(CodeChunkModel.id).where(
            CodeChunkModel.repository_id == repository_id
        )
        await self._session.execute(
            delete(ChunkEmbeddingModel).where(
                ChunkEmbeddingModel.chunk_id.in_(chunks_of_repository)
            )
        )
        for model in (CodeChunkModel, SymbolEdgeModel, CodeSymbolModel, SourceFileModel):
            await self._session.execute(delete(model).where(model.repository_id == repository_id))

        await self._session.execute(delete(IndexSnapshotModel).where(belongs))
        self._identity_map.clear()
        return removed

    def flush_changes(self) -> None:
        for snapshot, model in self._identity_map.values():
            mapper.apply_snapshot_changes(model, snapshot)

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for snapshot, _ in self._identity_map.values():
            collected.extend(snapshot.pull_events())
        return collected

    def _track(self, model: IndexSnapshotModel) -> IndexSnapshot:
        snapshot_id = IndexSnapshotId(model.id)
        tracked = self._identity_map.get(snapshot_id)
        if tracked is not None:
            return tracked[0]

        snapshot = mapper.snapshot_to_domain(model)
        self._identity_map[snapshot_id] = (snapshot, model)
        return snapshot


class SqlAlchemySourceFileRepository:
    """Репозиторий агрегата SourceFile."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[str, tuple[SourceFile, SourceFileModel]] = {}

    def add(self, source_file: SourceFile) -> None:
        model = mapper.source_file_to_model(source_file)
        self._session.add(model)
        self._identity_map[self._key(source_file.repository_id, source_file.path)] = (
            source_file,
            model,
        )

    async def find_by_path(self, repository_id: RepositoryId, path: str) -> SourceFile | None:
        tracked = self._identity_map.get(self._key(repository_id, path))
        if tracked is not None:
            return tracked[0]

        statement = select(SourceFileModel).where(
            SourceFileModel.repository_id == repository_id,
            SourceFileModel.path == path,
        )
        model = (await self._session.execute(statement)).scalars().first()
        return None if model is None else self._track(model)

    async def load_many(
        self,
        repository_id: RepositoryId,
        paths: list[str],
    ) -> dict[str, SourceFile]:
        loaded: dict[str, SourceFile] = {}
        for start in range(0, len(paths), LOAD_BATCH_SIZE):
            statement = select(SourceFileModel).where(
                SourceFileModel.repository_id == repository_id,
                SourceFileModel.path.in_(paths[start : start + LOAD_BATCH_SIZE]),
            )
            for model in (await self._session.execute(statement)).scalars().all():
                loaded[model.path] = self._track(model)

        return loaded

    async def count_totals(self, repository_id: RepositoryId) -> IndexTotals:
        live = (
            SourceFileModel.repository_id == repository_id,
            SourceFileModel.is_deleted.is_(False),
        )
        files = select(func.count()).select_from(SourceFileModel).where(*live)
        symbols = (
            select(func.count())
            .select_from(CodeSymbolModel)
            .join(SourceFileModel, SourceFileModel.id == CodeSymbolModel.file_id)
            .where(*live)
        )
        chunks = (
            select(func.count())
            .select_from(CodeChunkModel)
            .join(SourceFileModel, SourceFileModel.id == CodeChunkModel.file_id)
            .where(*live)
        )
        row = (
            await self._session.execute(
                select(files.scalar_subquery(), symbols.scalar_subquery(), chunks.scalar_subquery())
            )
        ).one()
        return IndexTotals(files=int(row[0]), symbols=int(row[1]), chunks=int(row[2]))

    async def list_paths(self, repository_id: RepositoryId) -> dict[str, str]:
        """Путь → хеш содержимого без загрузки символов и чанков.

        На этом строится инкрементальность: сверяются хеши, а разбирается
        только то, что действительно изменилось.

        Учитываются лишь файлы из готового снапшота. Прерванная индексация
        оставляет символы записанными, но граф — недостроенным; если считать
        такие файлы разобранными, следующий запуск найдёт совпадение хешей,
        ничего не переразберёт и оставит индекс битым навсегда.
        """
        statement = (
            select(SourceFileModel.path, SourceFileModel.content_hash)
            .join(
                IndexSnapshotModel,
                IndexSnapshotModel.id == SourceFileModel.last_seen_snapshot_id,
            )
            .where(
                SourceFileModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                IndexSnapshotModel.status == SnapshotStatus.READY,
            )
        )
        rows = await self._session.execute(statement)
        return dict(rows.all())  # type: ignore[arg-type]

    def flush_changes(self) -> None:
        for source_file, model in self._identity_map.values():
            mapper.apply_source_file_changes(model, source_file)

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for source_file, _ in self._identity_map.values():
            collected.extend(source_file.pull_events())
        return collected

    def _track(self, model: SourceFileModel) -> SourceFile:
        key = self._key(RepositoryId(model.repository_id), model.path)
        tracked = self._identity_map.get(key)
        if tracked is not None:
            return tracked[0]

        source_file = mapper.source_file_to_domain(model)
        self._identity_map[key] = (source_file, model)
        return source_file

    @staticmethod
    def _key(repository_id: RepositoryId, path: str) -> str:
        return f"{repository_id}:{path}"


class SqlAlchemySymbolEdgeRepository:
    """Рёбра графа символов.

    Агрегата у рёбер нет: они связывают символы разных файлов, и владеть ими
    не может ни один из них. Поэтому и запись идёт напрямую, пачкой.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_symbols(
        self,
        repository_id: RepositoryId,
        symbol_ids: list[CodeSymbolId],
        edges: list[SymbolEdge],
    ) -> None:
        """Заменяет исходящие рёбра перечисленных символов.

        Записанное выгружается в базу сразу: следом идёт разрешение имён
        запросом, а оно видит только то, что уже попало в сессию.
        """
        for start in range(0, len(symbol_ids), DELETE_BATCH_SIZE):
            await self._session.execute(
                delete(SymbolEdgeModel).where(
                    SymbolEdgeModel.repository_id == repository_id,
                    SymbolEdgeModel.source_symbol_id.in_(
                        symbol_ids[start : start + DELETE_BATCH_SIZE]
                    ),
                )
            )

        self._session.add_all([mapper.edge_to_model(edge) for edge in edges])
        await self._session.flush()

    async def refresh_statistics(self) -> None:
        """Пересчитывает статистику таблиц, по которым планируется замыкание.

        `ANALYZE` видит только закоммиченные строки, поэтому вызывать его
        имеет смысл после записи рёбер и до их замыкания. Автоматический
        сбор статистики здесь не помогает: он запускается по своему
        расписанию и к моменту запроса не успевает.
        """
        for table in ("symbol_edge", "code_symbol"):
            await self._session.execute(text(f"ANALYZE {table}"))

    async def count_resolved(self, repository_id: RepositoryId) -> int:
        statement = (
            select(func.count())
            .select_from(SymbolEdgeModel)
            .where(
                SymbolEdgeModel.repository_id == repository_id,
                SymbolEdgeModel.target_symbol_id.is_not(None),
            )
        )
        return int((await self._session.execute(statement)).scalar_one())

    async def resolve_pending(self, repository_id: RepositoryId) -> int:
        """Замыкает висящие рёбра.

        Два прохода. Первый — по полному имени: надёжно и точно. Второй —
        по последнему сегменту имени, и только когда такой символ в проекте
        ровно один.

        Второй проход нужен из-за того, как выглядит обычный код: `run.add_finding()`
        не даёт статически узнать тип `run`, и без него метод остался бы вообще
        без входящих связей — то есть без ответа на вопрос «кто это вызывает».
        Однозначность имени — единственная гарантия, которую здесь можно дать,
        поэтому уверенность у таких рёбер понижена.
        """
        return await self._resolve_by_full_name(repository_id) + await self._resolve_by_suffix(
            repository_id
        )

    async def _resolve_by_full_name(self, repository_id: RepositoryId) -> int:
        earliest = (
            select(
                CodeSymbolModel.qualified_name.label("qualified_name"),
                func.min(CodeSymbolModel.start_line).label("start_line"),
            )
            .where(CodeSymbolModel.repository_id == repository_id)
            .group_by(CodeSymbolModel.qualified_name)
            .subquery()
        )
        target = (
            select(CodeSymbolModel.id, CodeSymbolModel.qualified_name)
            .join(
                earliest,
                (CodeSymbolModel.qualified_name == earliest.c.qualified_name)
                & (CodeSymbolModel.start_line == earliest.c.start_line),
            )
            .where(CodeSymbolModel.repository_id == repository_id)
            .subquery()
        )

        result = await self._session.execute(
            update(SymbolEdgeModel)
            .where(
                SymbolEdgeModel.repository_id == repository_id,
                SymbolEdgeModel.is_resolved.is_(False),
                SymbolEdgeModel.target_qualified_name == target.c.qualified_name,
            )
            .values(target_symbol_id=target.c.id, is_resolved=True)
            .returning(SymbolEdgeModel.id)
        )
        return len(result.all())

    async def _resolve_by_suffix(self, repository_id: RepositoryId) -> int:
        """Замыкает рёбра по последнему сегменту имени.

        Идентификатор берётся тем же агрегатом, что и проверка однозначности:
        при `count(*) = 1` в группе ровно один символ, и второе соединение
        с таблицей символов ради его выборки не нужно.

        Дело не в лишнем запросе, а в плане. С двумя соединениями Postgres
        оценивал `having count(*) = 1` в 85 строк вместо десятков тысяч,
        выбирал вложенный цикл и сравнивал имена строками: на сотне тысяч
        рёбер такой `UPDATE` шёл больше часа. Без второго соединения ошибка
        перестаёт быть решающей, и план становится слиянием отсортированных
        входов.
        """
        singletons = (
            select(
                CodeSymbolModel.name.label("name"),
                func.array_agg(CodeSymbolModel.id)[1].label("id"),
            )
            .where(
                CodeSymbolModel.repository_id == repository_id,
                CodeSymbolModel.kind != SymbolKind.MODULE,
            )
            .group_by(CodeSymbolModel.name)
            .having(func.count() == 1)
            .cte("singletons")
        )
        result = await self._session.execute(
            update(SymbolEdgeModel)
            .where(
                SymbolEdgeModel.repository_id == repository_id,
                SymbolEdgeModel.is_resolved.is_(False),
                SymbolEdgeModel.target_name == singletons.c.name,
            )
            .values(
                target_symbol_id=singletons.c.id,
                is_resolved=True,
                confidence=SUFFIX_MATCH_CONFIDENCE,
            )
            .returning(SymbolEdgeModel.id)
        )
        return len(result.all())

    async def list_incoming(self, symbol_id: CodeSymbolId) -> list[SymbolEdge]:
        """Кто ссылается на символ — тот самый обход вверх по графу."""
        statement = select(SymbolEdgeModel).where(SymbolEdgeModel.target_symbol_id == symbol_id)
        models = (await self._session.execute(statement)).scalars().all()
        return [mapper.edge_to_domain(model) for model in models]

    async def list_outgoing(self, symbol_id: CodeSymbolId) -> list[SymbolEdge]:
        statement = select(SymbolEdgeModel).where(SymbolEdgeModel.source_symbol_id == symbol_id)
        models = (await self._session.execute(statement)).scalars().all()
        return [mapper.edge_to_domain(model) for model in models]

    def flush_changes(self) -> None:
        """Рёбра пишутся сразу и не отслеживаются как агрегат."""

    def collect_events(self) -> list[DomainEvent]:
        return []

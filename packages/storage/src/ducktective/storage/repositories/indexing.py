from sqlalchemy import (
    delete,
    func,
    select,
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
        singletons = (
            select(CodeSymbolModel.name.label("name"))
            .where(
                CodeSymbolModel.repository_id == repository_id,
                CodeSymbolModel.kind != SymbolKind.MODULE,
            )
            .group_by(CodeSymbolModel.name)
            .having(func.count() == 1)
            .subquery()
        )
        unique_names = (
            select(CodeSymbolModel.id, CodeSymbolModel.name)
            .join(singletons, CodeSymbolModel.name == singletons.c.name)
            .where(
                CodeSymbolModel.repository_id == repository_id,
                CodeSymbolModel.kind != SymbolKind.MODULE,
            )
            .subquery()
        )
        result = await self._session.execute(
            update(SymbolEdgeModel)
            .where(
                SymbolEdgeModel.repository_id == repository_id,
                SymbolEdgeModel.is_resolved.is_(False),
                SymbolEdgeModel.target_name == unique_names.c.name,
            )
            .values(
                target_symbol_id=unique_names.c.id,
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

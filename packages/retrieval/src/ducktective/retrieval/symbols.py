from typing import (
    Any,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    ColumnElement,
    Select,
    case,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)
from sqlalchemy.orm import (
    InstrumentedAttribute,
)

from ducktective.core.indexing.value_objects import (
    EdgeKind,
)
from ducktective.core.retrieval.ports import (
    CALL_EDGES,
    RelatedSymbol,
    SymbolContext,
)
from ducktective.core.types import (
    CodeSymbolId,
    QualifiedName,
    RepositoryId,
)
from ducktective.storage.models.indexing import (
    CodeChunkModel,
    CodeSymbolModel,
    SourceFileModel,
    SymbolEdgeModel,
)


def _ordering(pattern: str) -> list[Any]:
    """Порядок выдачи путей, разный у двух вопросов.

    «Какой из файлов с таким именем» — короткий путь ближе к названному,
    и он идёт первым. «Что тут вообще есть» — алфавит: он собирает файлы
    по каталогам, а длина поднимает наверх вендорные файлы из корня
    и прячет за ними код приложения.
    """
    if "*" in pattern or pattern.startswith("."):
        return [SourceFileModel.path]
    return [func.length(SourceFileModel.path), SourceFileModel.path]


def _matching(pattern: str) -> ColumnElement[bool]:
    """Условие на путь по образцу.

    Звёздочка переводится в подстановку SQL, расширение — в совпадение
    по концу, всё остальное считается хвостом пути. Разделять эти случаи
    приходится, потому что `.js` и `app/report.py` спрашивают о разном:
    первое — обо всех файлах вида, второе — об одном месте.
    """
    if "*" in pattern:
        return SourceFileModel.path.like(pattern.replace("*", "%"))

    if pattern.startswith("."):
        return SourceFileModel.path.like(f"%{pattern}")

    return or_(
        SourceFileModel.path == pattern,
        SourceFileModel.path.endswith(f"/{pattern}"),
    )


class PostgresSymbolReader:
    """Чтение символов и обход графа.

    Текст символа собирается из его чанков: они уже лежат в базе, и читать
    ради этого файл с диска значило бы держать рядом два источника правды.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def symbols_covering(
        self,
        repository_id: RepositoryId,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[SymbolContext]:
        statement = (
            self._base_query()
            .where(
                CodeSymbolModel.repository_id == repository_id,
                SourceFileModel.path == path,
                CodeSymbolModel.start_line <= end_line,
                CodeSymbolModel.end_line >= start_line,
            )
            .order_by(CodeSymbolModel.end_line - CodeSymbolModel.start_line)
        )
        return await self._read(statement)

    async def find_paths(
        self,
        repository_id: RepositoryId,
        needle: str,
        *,
        limit: int = 5,
    ) -> list[str]:
        """Пути по образцу, короткие сначала.

        Образцов два вида, и оба нужны. Хвост пути — так называют
        конкретный файл: `.../selection_packs.py` найдёт и сам файл,
        и одноимённый в соседнем каталоге, и первым пойдёт тот, у кого
        совпадение занимает большую часть пути.

        Кусок с `*` или расширение — так спрашивают «что тут есть»:
        `.js` перечислит скрипты, `templates/*` — шаблоны. Без этого
        спрашивающий проверяет догадки вместо того, чтобы посмотреть.
        """
        pattern = needle.strip().lstrip("/")
        if not pattern:
            return []

        statement = (
            select(SourceFileModel.path)
            .where(
                SourceFileModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                _matching(pattern),
            )
            .order_by(*_ordering(pattern))
            .limit(limit)
        )
        rows = await self._session.execute(statement)
        return [row.path for row in rows]

    async def find_by_name(
        self,
        repository_id: RepositoryId,
        name: str,
        *,
        limit: int = 10,
    ) -> list[SymbolContext]:
        wanted = name.strip()
        if not wanted:
            return []

        precision = case(
            (CodeSymbolModel.qualified_name == wanted, 0),
            else_=1,
        )
        statement = (
            self._base_query()
            .where(
                CodeSymbolModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                or_(
                    CodeSymbolModel.qualified_name == wanted,
                    CodeSymbolModel.qualified_name.endswith(f".{wanted}"),
                ),
            )
            .order_by(precision, CodeSymbolModel.qualified_name)
            .limit(limit)
        )
        return await self._read(statement)

    async def callees(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = CALL_EDGES,
        limit: int = 20,
    ) -> list[SymbolContext]:
        return await self._neighbours(symbol_ids, incoming=False, kinds=kinds, limit=limit)

    async def callers(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = CALL_EDGES,
        limit: int = 20,
    ) -> list[SymbolContext]:
        return await self._neighbours(symbol_ids, incoming=True, kinds=kinds, limit=limit)

    async def referring(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = (),
        limit: int = 20,
    ) -> list[RelatedSymbol]:
        if not symbol_ids:
            return []

        related = (
            select(
                SymbolEdgeModel.source_symbol_id.label("symbol_id"),
                SymbolEdgeModel.kind.label("edge_kind"),
                SymbolEdgeModel.is_resolved.label("is_resolved"),
                SymbolEdgeModel.confidence.label("confidence"),
            )
            .where(*self._edges(symbol_ids, incoming=True, kinds=kinds))
            .subquery()
        )
        statement = (
            self._base_query()
            .add_columns(related.c.edge_kind, related.c.is_resolved)
            .join(related, related.c.symbol_id == CodeSymbolModel.id)
            .order_by(related.c.confidence.desc())
            .limit(limit)
        )

        rows = (await self._session.execute(statement)).all()
        texts = await self._texts_of([row.id for row in rows])
        return [
            RelatedSymbol(
                context=_context(row, texts.get(row.id, "")),
                kind=row.edge_kind,
                is_resolved=row.is_resolved,
            )
            for row in rows
        ]

    async def edge_kinds(self, symbol_ids: list[CodeSymbolId]) -> dict[EdgeKind, int]:
        if not symbol_ids:
            return {}

        statement = (
            select(SymbolEdgeModel.kind, func.count().label("total"))
            .where(*self._edges(symbol_ids, incoming=True, kinds=()))
            .group_by(SymbolEdgeModel.kind)
        )
        rows = (await self._session.execute(statement)).all()
        return {row.kind: row.total for row in rows}

    async def _neighbours(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        incoming: bool,
        kinds: tuple[EdgeKind, ...],
        limit: int,
    ) -> list[SymbolContext]:
        """Соседи по графу в одну сторону и по названным видам связи.

        Уверенные рёбра идут первыми: связь, восстановленная по совпадению
        имени, слабее той, что разрешена через импорт, и вытеснять её
        из бюджета не должна.
        """
        if not symbol_ids:
            return []

        _, neighbour = self._directions(incoming=incoming)
        related = (
            select(neighbour.label("symbol_id"), SymbolEdgeModel.confidence)
            .where(*self._edges(symbol_ids, incoming=incoming, kinds=kinds))
            .subquery()
        )
        statement = (
            self._base_query()
            .join(related, related.c.symbol_id == CodeSymbolModel.id)
            .order_by(related.c.confidence.desc())
            .limit(limit)
        )
        return await self._read(statement)

    @staticmethod
    def _edges(
        symbol_ids: list[CodeSymbolId],
        *,
        incoming: bool,
        kinds: tuple[EdgeKind, ...],
    ) -> list[ColumnElement[bool]]:
        """Условия на ребро: сторона, наличие соседа и вид связи.

        Пустой перечень видов означает «любая связь» — так спрашивают,
        когда хотят увидеть карту зависимостей символа целиком.
        """
        anchor, neighbour = PostgresSymbolReader._directions(incoming=incoming)
        conditions: list[ColumnElement[bool]] = [
            anchor.in_(symbol_ids),
            neighbour.isnot(None),
            neighbour.notin_(symbol_ids),
        ]
        if kinds:
            conditions.append(SymbolEdgeModel.kind.in_(kinds))
        return conditions

    @staticmethod
    def _directions(
        *,
        incoming: bool,
    ) -> tuple[InstrumentedAttribute[Any], InstrumentedAttribute[Any]]:
        """Колонки ребра со стороны изменённого символа и со стороны соседа."""
        if incoming:
            return SymbolEdgeModel.target_symbol_id, SymbolEdgeModel.source_symbol_id
        return SymbolEdgeModel.source_symbol_id, SymbolEdgeModel.target_symbol_id

    def _base_query(self) -> Select[Any]:
        return select(
            CodeSymbolModel.id,
            CodeSymbolModel.qualified_name,
            CodeSymbolModel.kind,
            SourceFileModel.path,
            CodeSymbolModel.start_line,
            CodeSymbolModel.end_line,
            CodeSymbolModel.signature,
            CodeSymbolModel.docstring,
        ).join(SourceFileModel, SourceFileModel.id == CodeSymbolModel.file_id)

    async def _read(self, statement: Select[Any]) -> list[SymbolContext]:
        rows = (await self._session.execute(statement)).all()
        texts = await self._texts_of([row.id for row in rows])
        return [_context(row, texts.get(row.id, "")) for row in rows]

    async def _texts_of(self, symbol_ids: list[UUID]) -> dict[UUID, str]:
        if not symbol_ids:
            return {}

        statement = (
            select(CodeChunkModel.symbol_id, CodeChunkModel.content)
            .where(CodeChunkModel.symbol_id.in_(symbol_ids))
            .order_by(CodeChunkModel.symbol_id, CodeChunkModel.start_line)
        )
        rows = (await self._session.execute(statement)).all()

        texts: dict[UUID, str] = {}
        for symbol_id, content in rows:
            texts[symbol_id] = f"{texts[symbol_id]}\n{content}" if symbol_id in texts else content
        return texts


def _context(row: Any, text: str) -> SymbolContext:
    return SymbolContext(
        symbol_id=CodeSymbolId(row.id),
        qualified_name=QualifiedName(row.qualified_name),
        kind=row.kind,
        path=row.path,
        start_line=row.start_line,
        end_line=row.end_line,
        signature=row.signature,
        docstring=row.docstring,
        text=text,
    )

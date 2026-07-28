from typing import (
    Any,
)
from uuid import (
    UUID,
)

from sqlalchemy import (
    Select,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)
from sqlalchemy.orm import (
    InstrumentedAttribute,
)

from ducktective.core.retrieval.ports import (
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

    async def callees(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        limit: int = 20,
    ) -> list[SymbolContext]:
        return await self._neighbours(symbol_ids, incoming=False, limit=limit)

    async def callers(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        limit: int = 20,
    ) -> list[SymbolContext]:
        return await self._neighbours(symbol_ids, incoming=True, limit=limit)

    async def _neighbours(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        incoming: bool,
        limit: int,
    ) -> list[SymbolContext]:
        """Соседи по графу в одну сторону.

        Уверенные рёбра идут первыми: связь, восстановленная по совпадению
        имени, слабее той, что разрешена через импорт, и вытеснять её
        из бюджета не должна.
        """
        if not symbol_ids:
            return []

        anchor, neighbour = self._directions(incoming=incoming)
        related = (
            select(neighbour.label("symbol_id"), SymbolEdgeModel.confidence)
            .where(
                anchor.in_(symbol_ids),
                neighbour.isnot(None),
                neighbour.notin_(symbol_ids),
            )
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

        return [
            SymbolContext(
                symbol_id=CodeSymbolId(row.id),
                qualified_name=QualifiedName(row.qualified_name),
                kind=row.kind,
                path=row.path,
                start_line=row.start_line,
                end_line=row.end_line,
                signature=row.signature,
                docstring=row.docstring,
                text=texts.get(row.id, ""),
            )
            for row in rows
        ]

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

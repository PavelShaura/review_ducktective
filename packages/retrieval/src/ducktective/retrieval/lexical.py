from typing import (
    Any,
)

from sqlalchemy import (
    ColumnElement,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.indexing.search import (
    build_search_text,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    SymbolHit,
)
from ducktective.core.types import (
    CodeChunkId,
    CodeSymbolId,
    QualifiedName,
    RepositoryId,
)
from ducktective.storage.models.indexing import (
    CodeChunkModel,
    CodeSymbolModel,
    SourceFileModel,
)


SEARCH_CONFIGURATION = "simple"


class PostgresLexicalSearch:
    """Полнотекстовый поиск средствами Postgres.

    Отдельный поисковый движок не поднимается: индекс уже лежит рядом
    с данными, и лишнее хранилище дало бы рассинхронизацию вместо выигрыша.

    Запрос проходит ту же подготовку, что и индексируемый текст: иначе
    «ReviewRun» не нашёл бы то, что записано как «review run».
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[ChunkHit]:
        terms = _to_tsquery(query)
        if terms is None:
            return []

        rank = func.ts_rank_cd(CodeChunkModel.search_vector, terms)
        statement = (
            select(
                CodeChunkModel.id,
                CodeChunkModel.symbol_id,
                SourceFileModel.path,
                CodeChunkModel.breadcrumb,
                CodeChunkModel.content,
                CodeChunkModel.start_line,
                CodeChunkModel.end_line,
                rank.label("score"),
            )
            .join(SourceFileModel, SourceFileModel.id == CodeChunkModel.file_id)
            .where(
                CodeChunkModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                CodeChunkModel.search_vector.op("@@")(terms),
            )
            .order_by(rank.desc())
            .limit(limit)
        )

        rows = await self._session.execute(statement)
        return [
            ChunkHit(
                chunk_id=CodeChunkId(row.id),
                symbol_id=CodeSymbolId(row.symbol_id) if row.symbol_id else None,
                path=row.path,
                breadcrumb=row.breadcrumb,
                content=row.content,
                start_line=row.start_line,
                end_line=row.end_line,
                score=float(row.score),
            )
            for row in rows
        ]

    async def search_symbols(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[SymbolHit]:
        terms = _to_tsquery(query)
        if terms is None:
            return []

        rank = func.ts_rank_cd(CodeSymbolModel.search_vector, terms)
        statement = (
            select(
                CodeSymbolModel.id,
                CodeSymbolModel.qualified_name,
                CodeSymbolModel.kind,
                SourceFileModel.path,
                CodeSymbolModel.start_line,
                CodeSymbolModel.end_line,
                CodeSymbolModel.signature,
                rank.label("score"),
            )
            .join(SourceFileModel, SourceFileModel.id == CodeSymbolModel.file_id)
            .where(
                CodeSymbolModel.repository_id == repository_id,
                SourceFileModel.is_deleted.is_(False),
                CodeSymbolModel.search_vector.op("@@")(terms),
            )
            .order_by(rank.desc())
            .limit(limit)
        )

        rows = await self._session.execute(statement)
        return [
            SymbolHit(
                symbol_id=CodeSymbolId(row.id),
                qualified_name=QualifiedName(row.qualified_name),
                kind=row.kind,
                path=row.path,
                start_line=row.start_line,
                end_line=row.end_line,
                signature=row.signature,
                score=float(row.score),
            )
            for row in rows
        ]


def _to_tsquery(query: str) -> ColumnElement[Any] | None:
    """Превращает запрос в набор слов, соединённых «или».

    Строгое «и» на коде почти всегда даёт пустую выдачу: человек пишет
    «where review run created», а в тексте эти слова живут порознь.
    Ранжирование само поднимет фрагменты, где совпало больше.
    """
    prepared = build_search_text(query)
    words = {word for word in prepared.replace("\n", " ").split() if word.isalnum()}
    if not words:
        return None

    return func.to_tsquery(SEARCH_CONFIGURATION, " | ".join(sorted(words)))

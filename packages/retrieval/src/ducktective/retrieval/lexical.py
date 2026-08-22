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
from ducktective.retrieval.deadline import (
    DEFAULT_SEARCH_TIMEOUT_MS,
    within_deadline,
)
from ducktective.storage.models.indexing import (
    CodeChunkModel,
    CodeSymbolModel,
    SourceFileModel,
)


SEARCH_CONFIGURATION = "simple"

MAX_QUERY_TERMS = 40
"""Сколько слов запроса доходит до базы.

Слова соединяются через «или», поэтому длина запроса решает не точность,
а объём работы: под условие из семисот слов подходит почти каждый фрагмент
базы, ранг приходится считать для всех, и `LIMIT` не спасает — сортировать
всё равно надо посчитанное. На `ssuz` такой запрос — 762 слова на 38 826
чанков — шёл восемь минут и держал прогон целиком.

Предел стоит здесь, а не у вызывающего: запрос из целого файла может
прийти и от внешнего клиента, а обещание отвечать за отведённое время
даёт поиск, а не тот, кто его позвал.
"""

MIN_TERM_LENGTH = 3
"""Короткое слово есть везде и не различает ничего.

Отбор идёт по длине: составные имена вроде `declaration_pack` и `weasyprint`
сужают выдачу, а `if`, `to` и `id` только расширяют её до всей базы.
"""


class PostgresLexicalSearch:
    """Полнотекстовый поиск средствами Postgres.

    Отдельный поисковый движок не поднимается: индекс уже лежит рядом
    с данными, и лишнее хранилище дало бы рассинхронизацию вместо выигрыша.

    Запрос проходит ту же подготовку, что и индексируемый текст: иначе
    «ReviewRun» не нашёл бы то, что записано как «review run».
    """

    def __init__(
        self, session: AsyncSession, *, timeout_ms: int = DEFAULT_SEARCH_TIMEOUT_MS
    ) -> None:
        self._session = session
        self._timeout_ms = timeout_ms

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

        rows = await within_deadline(
            self._session,
            lambda: self._session.execute(statement),
            timeout_ms=self._timeout_ms,
        )
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

        rows = await within_deadline(
            self._session,
            lambda: self._session.execute(statement),
            timeout_ms=self._timeout_ms,
        )
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

    Слов берётся ограниченное число и самые длинные из них: «или» по всему
    словарю запроса перестаёт быть поиском — под него подходит вся база.
    """
    words = _distinctive_terms(query)
    if not words:
        return None

    return func.to_tsquery(SEARCH_CONFIGURATION, " | ".join(sorted(words)))


def _distinctive_terms(query: str, *, limit: int = MAX_QUERY_TERMS) -> set[str]:
    """Отбирает слова, которые сужают выдачу, а не расширяют её.

    Короткий запрос доходит целиком: у человека, спросившего два слова,
    отбирать нечего. Обрезается длинный — тот, что собран из целого файла.
    """
    prepared = build_search_text(query)
    words = {word for word in prepared.replace("\n", " ").split() if word.isalnum()}
    if len(words) <= limit:
        return words

    long_enough = {word for word in words if len(word) >= MIN_TERM_LENGTH} or words
    return set(sorted(long_enough, key=lambda word: (-len(word), word))[:limit])

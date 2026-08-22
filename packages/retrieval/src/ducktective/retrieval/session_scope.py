from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.indexing.ports import (
    Embedder,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.retrieval.ports import (
    ChunkHit,
    SymbolContext,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.types import (
    CodeSymbolId,
    RepositoryId,
)
from ducktective.retrieval.diff_context import (
    DEFAULT_TOKEN_BUDGET,
    DiffContextBuilder,
)
from ducktective.retrieval.hybrid import (
    HybridSearch,
)
from ducktective.retrieval.lexical import (
    PostgresLexicalSearch,
)
from ducktective.retrieval.symbols import (
    PostgresSymbolReader,
)
from ducktective.retrieval.vector import (
    VectorSearch,
)


class SessionScopedContextBuilder:
    """Сборщик контекста, живущий на своей сессии.

    Чтение индекса не участвует в транзакции прогона: контекст собирается
    между короткими транзакциями ревью, и держать ради него открытой чужую
    сессию незачем.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        *,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._token_budget = token_budget

    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext:
        async with self._session_factory() as session:
            builder = DiffContextBuilder(
                PostgresSymbolReader(session),
                HybridSearch(
                    PostgresLexicalSearch(session),
                    VectorSearch(session, self._embedder),
                ),
                token_budget=self._token_budget,
            )
            return await builder.build(repository_id, file)


class SessionScopedSymbolReader:
    """Чтение символов, живущее на своей сессии.

    Нужен точкам входа, у которых нет прогона ревью и его транзакции:
    каждый запрос внешнего клиента самодостаточен и открывает сессию на себя.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def symbols_covering(
        self,
        repository_id: RepositoryId,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[SymbolContext]:
        async with self._session_factory() as session:
            return await PostgresSymbolReader(session).symbols_covering(
                repository_id,
                path,
                start_line,
                end_line,
            )

    async def find_by_name(
        self,
        repository_id: RepositoryId,
        name: str,
        *,
        limit: int = 10,
    ) -> list[SymbolContext]:
        async with self._session_factory() as session:
            return await PostgresSymbolReader(session).find_by_name(
                repository_id,
                name,
                limit=limit,
            )

    async def find_paths(
        self,
        repository_id: RepositoryId,
        needle: str,
        *,
        limit: int = 5,
    ) -> list[str]:
        async with self._session_factory() as session:
            return await PostgresSymbolReader(session).find_paths(
                repository_id,
                needle,
                limit=limit,
            )

    async def callees(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        limit: int = 20,
    ) -> list[SymbolContext]:
        async with self._session_factory() as session:
            return await PostgresSymbolReader(session).callees(symbol_ids, limit=limit)

    async def callers(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        limit: int = 20,
    ) -> list[SymbolContext]:
        async with self._session_factory() as session:
            return await PostgresSymbolReader(session).callers(symbol_ids, limit=limit)


class SessionScopedHybridSearch:
    """Гибридный поиск, живущий на своей сессии."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 20,
    ) -> list[ChunkHit]:
        async with self._session_factory() as session:
            search = HybridSearch(
                PostgresLexicalSearch(session),
                VectorSearch(session, self._embedder),
            )
            return await search.search_chunks(repository_id, query, limit=limit)

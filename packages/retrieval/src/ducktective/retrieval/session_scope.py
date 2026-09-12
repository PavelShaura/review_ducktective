from collections.abc import (
    AsyncIterator,
    Mapping,
)
from contextlib import (
    asynccontextmanager,
)

from sqlalchemy import (
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.indexing.ports import (
    Embedder,
)
from ducktective.core.indexing.value_objects import (
    EdgeKind,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.retrieval.ports import (
    CALL_EDGES,
    ChunkHit,
    RelatedSymbol,
    RepositoryDigest,
    SymbolContext,
    SymbolHit,
)
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.types import (
    CodeSymbolId,
    RepositoryId,
    TenantId,
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
from ducktective.storage.models.code_repository import (
    CodeRepositoryModel,
)
from ducktective.storage.tenant_scope import (
    bind_tenant,
)


@asynccontextmanager
async def _tenant_session(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: TenantId | None,
) -> AsyncIterator[AsyncSession]:
    """Сессия чтения, назвавшая своего тенанта.

    Индекс закрыт политикой базы наравне с находками, и сессия без
    названного тенанта не увидит ни одного символа. Читающие классы живут
    вне транзакции прогона (D-016), поэтому называть тенанта приходится
    каждой из них, а не одному Unit of Work.
    """
    async with session_factory() as session:
        await bind_tenant(session, tenant_id)
        yield session


class SessionScopedContextBuilder:
    """Сборщик контекста, живущий на своей сессии.

    Чтение индекса не участвует в транзакции прогона: контекст собирается
    между короткими транзакциями ревью, и держать ради него открытой чужую
    сессию незачем.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedders: Mapping[str, Embedder],
        *,
        tenant_id: TenantId | None = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> None:
        self._session_factory = session_factory
        self._embedders = embedders
        self._tenant_id = tenant_id
        self._token_budget = token_budget

    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            embedder = await _embedder_for(session, self._embedders, repository_id)
            builder = DiffContextBuilder(
                PostgresSymbolReader(session),
                HybridSearch(
                    PostgresLexicalSearch(session),
                    VectorSearch(session, embedder),
                ),
                token_budget=self._token_budget,
            )
            return await builder.build(repository_id, file)


class SessionScopedSymbolReader:
    """Чтение символов, живущее на своей сессии.

    Нужен точкам входа, у которых нет прогона ревью и его транзакции:
    каждый запрос внешнего клиента самодостаточен и открывает сессию на себя.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: TenantId | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id

    async def symbols_covering(
        self,
        repository_id: RepositoryId,
        path: str,
        start_line: int,
        end_line: int,
    ) -> list[SymbolContext]:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
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
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
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
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).find_paths(
                repository_id,
                needle,
                limit=limit,
            )

    async def describe(self, repository_id: RepositoryId) -> RepositoryDigest:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).describe(repository_id)

    async def symbols_in_file(
        self,
        repository_id: RepositoryId,
        path: str,
        *,
        limit: int = 200,
    ) -> list[SymbolContext]:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).symbols_in_file(
                repository_id,
                path,
                limit=limit,
            )

    async def read_lines(
        self,
        repository_id: RepositoryId,
        path: str,
        *,
        start_line: int,
        end_line: int,
    ) -> str | None:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).read_lines(
                repository_id,
                path,
                start_line=start_line,
                end_line=end_line,
            )

    async def search_symbols(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 10,
    ) -> list[SymbolHit]:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).search_symbols(
                repository_id,
                query,
                limit=limit,
            )

    async def callees(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = CALL_EDGES,
        limit: int = 20,
    ) -> list[SymbolContext]:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).callees(
                symbol_ids,
                kinds=kinds,
                limit=limit,
            )

    async def callers(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = CALL_EDGES,
        limit: int = 20,
    ) -> list[SymbolContext]:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).callers(
                symbol_ids,
                kinds=kinds,
                limit=limit,
            )

    async def referring(
        self,
        symbol_ids: list[CodeSymbolId],
        *,
        kinds: tuple[EdgeKind, ...] = (),
        limit: int = 20,
    ) -> list[RelatedSymbol]:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).referring(
                symbol_ids,
                kinds=kinds,
                limit=limit,
            )

    async def edge_kinds(self, symbol_ids: list[CodeSymbolId]) -> dict[EdgeKind, int]:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            return await PostgresSymbolReader(session).edge_kinds(symbol_ids)


class SessionScopedHybridSearch:
    """Гибридный поиск, живущий на своей сессии.

    Эмбеддер запроса выбирается по репозиторию: у того записан ключ сервера,
    которым считался индекс, а искать можно только по векторам того же
    набора. Первый в перечне — сервер по умолчанию; запрос уходит ему,
    если он пишет в тот же набор, что и выбранный.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedders: Mapping[str, Embedder],
        *,
        tenant_id: TenantId | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedders = embedders
        self._tenant_id = tenant_id

    async def search_chunks(
        self,
        repository_id: RepositoryId,
        query: str,
        *,
        languages: tuple[str, ...] = (),
        limit: int = 20,
    ) -> list[ChunkHit]:
        async with _tenant_session(self._session_factory, self._tenant_id) as session:
            embedder = await _embedder_for(session, self._embedders, repository_id)
            search = HybridSearch(
                PostgresLexicalSearch(session),
                VectorSearch(session, embedder),
            )
            return await search.search_chunks(
                repository_id,
                query,
                languages=languages,
                limit=limit,
            )


async def _embedder_for(
    session: AsyncSession,
    embedders: Mapping[str, Embedder],
    repository_id: RepositoryId,
) -> Embedder:
    """Эмбеддер запроса под набор векторов репозитория.

    Первый в перечне — сервер по умолчанию; он и отвечает, если пишет
    в тот же набор, что выбранный для репозитория.
    """
    if not embedders:
        raise ValueError("Перечень эмбеддеров пуст")

    key = await session.scalar(
        select(CodeRepositoryModel.embedding_backend).where(CodeRepositoryModel.id == repository_id)
    )
    default = next(iter(embedders.values()))
    chosen = embedders.get(key or "", default)
    for candidate in embedders.values():
        if candidate.name == chosen.name:
            return candidate
    return chosen

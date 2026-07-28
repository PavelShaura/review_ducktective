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
from ducktective.core.review.entities import (
    ReviewFile,
)
from ducktective.core.types import (
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

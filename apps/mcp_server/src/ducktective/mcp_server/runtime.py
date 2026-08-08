from collections.abc import (
    AsyncIterator,
    Callable,
)
from contextlib import (
    asynccontextmanager,
)
from dataclasses import (
    dataclass,
)
from uuid import (
    UUID,
)

from ducktective.config.settings import (
    Settings,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.retrieval.navigation import (
    CodeNavigatorFactory,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.llm.embedder import (
    LiteLlmEmbedder,
)
from ducktective.retrieval.navigation import (
    IndexedNavigators,
)
from ducktective.retrieval.session_scope import (
    SessionScopedHybridSearch,
    SessionScopedSymbolReader,
)
from ducktective.storage.database import (
    build_engine,
    build_session_factory,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


@dataclass(frozen=True, kw_only=True)
class McpRuntime:
    """Зависимости инструментов сервера.

    Тенант фиксируется на запуске, а не приходит с вызовом: у stdio-транспорта
    нет ни сессии, ни идентичности вызывающего — сервер работает от того, кто
    его запустил. Когда тенантов станет больше одного, идентичность придётся
    брать из транспорта, и это отдельное решение (D-012).

    Unit of Work отдаётся фабрикой, а не готовым экземпляром: он держит одну
    сессию, а инструменты вызываются одновременно.
    """

    tenant_id: TenantId
    unit_of_work: Callable[[], UnitOfWork]
    navigators: CodeNavigatorFactory


@asynccontextmanager
async def build_runtime(settings: Settings, tenant_id: TenantId) -> AsyncIterator[McpRuntime]:
    engine = build_engine(
        settings.require_database_url(),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
    )
    session_factory = build_session_factory(engine)
    embedder = LiteLlmEmbedder(
        model=settings.local_embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.local_embedding_base_url or None,
        api_key=settings.local_llm_api_key,
    )

    try:
        yield McpRuntime(
            tenant_id=tenant_id,
            unit_of_work=lambda: SqlAlchemyUnitOfWork(session_factory),
            navigators=IndexedNavigators(
                symbols=SessionScopedSymbolReader(session_factory),
                search=SessionScopedHybridSearch(session_factory, embedder),
            ),
        )
    finally:
        await engine.dispose()


def resolve_tenant(settings: Settings, override: str | None) -> TenantId:
    reference = override or settings.mcp_tenant_id
    if not reference:
        raise SystemExit("Укажите --tenant или задайте MCP_TENANT_ID")

    try:
        return TenantId(UUID(reference))
    except ValueError as error:
        raise SystemExit(f"Тенант должен быть UUID, получено: {reference}") from error

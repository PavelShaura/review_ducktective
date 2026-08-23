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

import httpx

from ducktective.application.tenancy.sign_in import (
    ResolveSignedInUser,
)
from ducktective.auth.oidc import (
    OidcIdentityVerifier,
    OidcSettings,
)
from ducktective.auth.session import (
    TerminalSession,
)
from ducktective.config.settings import (
    Settings,
)
from ducktective.core.exceptions import (
    NotAuthenticatedError,
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
from ducktective.storage.events.null_publisher import (
    NullEventPublisher,
)
from ducktective.storage.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


@dataclass(frozen=True, kw_only=True)
class McpRuntime:
    """Зависимости инструментов сервера.

    Тенант фиксируется на запуске, а не приходит с вызовом: у stdio-транспорта
    нет ни сессии, ни идентичности вызывающего — сервер работает от того, кто
    его запустил. Организация при этом берётся из его входа (`ducktective
    login`), а не из настройки: идентификатор в конфигурации открывал бы
    чужую кодовую базу тому, кто его подставит.

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
            unit_of_work=lambda: SqlAlchemyUnitOfWork(session_factory, tenant_id=tenant_id),
            navigators=IndexedNavigators(
                symbols=SessionScopedSymbolReader(session_factory, tenant_id=tenant_id),
                search=SessionScopedHybridSearch(session_factory, embedder, tenant_id=tenant_id),
            ),
        )
    finally:
        await engine.dispose()


async def resolve_tenant(settings: Settings) -> TenantId:
    """Организация запустившего сервер, по его сохранённому входу.

    Сервер живёт рядом с терминалом и пользуется его входом: отдельного
    способа представиться у stdio нет, а второй набор учётных данных
    развалился бы с первым же обновлением токена.
    """
    if not settings.authentication_required:
        raise SystemExit("Не задан OIDC_ISSUER: сервер не может выяснить, от чьего имени работает")

    session = TerminalSession(
        issuer=settings.oidc_issuer,
        client_id=settings.oidc_device_client_id,
    )
    engine = build_engine(settings.require_database_url())
    try:
        token = await session.access_token()
        async with httpx.AsyncClient(timeout=10.0) as client:
            verifier = OidcIdentityVerifier(
                OidcSettings(issuer=settings.oidc_issuer, audience=settings.oidc_audience),
                client,
            )
            identity = await verifier.verify(token)

        resolved = await ResolveSignedInUser(
            SqlAlchemyUnitOfWork(build_session_factory(engine)),
            NullEventPublisher(),
        ).execute(identity)
    except NotAuthenticatedError as error:
        raise SystemExit(f"{error}. Выполните `ducktective login`") from error
    finally:
        await engine.dispose()

    if resolved.account is None:
        raise SystemExit("Учётная запись не состоит в организации: принять приглашение или создать")
    return resolved.account.tenant_id

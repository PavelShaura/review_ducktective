from types import (
    TracebackType,
)
from typing import (
    Protocol,
    Self,
)

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.types import (
    TenantId,
)
from ducktective.storage.repositories.chat import (
    SqlAlchemyConversationRepository,
)
from ducktective.storage.repositories.code_repository import (
    SqlAlchemyCodeRepositoryRepository,
)
from ducktective.storage.repositories.embeddings import (
    SqlAlchemyEmbeddingStore,
)
from ducktective.storage.repositories.indexing import (
    SqlAlchemyIndexSnapshotRepository,
    SqlAlchemySourceFileRepository,
    SqlAlchemySymbolEdgeRepository,
)
from ducktective.storage.repositories.provider_connection import (
    SqlAlchemyProviderConnectionRepository,
)
from ducktective.storage.repositories.review_run import (
    SqlAlchemyReviewRunRepository,
)
from ducktective.storage.repositories.tenancy import (
    SqlAlchemyInvitationRepository,
    SqlAlchemyTenantRepository,
    SqlAlchemyUserAccountRepository,
)
from ducktective.storage.tenant_scope import (
    bind_tenant,
)


class TrackingRepository(Protocol):
    """Репозиторий, отслеживающий загруженные агрегаты."""

    def flush_changes(self) -> None: ...

    def collect_events(self) -> list[DomainEvent]: ...


class SqlAlchemyUnitOfWork:
    """Реализация Unit of Work поверх сессии SQLAlchemy.

    Одна единица работы — одна сессия — одна транзакция. Выход из контекста без
    явного commit откатывает изменения. Перед коммитом изменения агрегатов
    переносятся в ORM-модели, а их события накапливаются для публикации.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: TenantId | None = None,
    ) -> None:
        """Единица работы, знающая, от чьего имени она открыта.

        Тенант нужен не use case'ам — они и так фильтруют, — а политикам
        базы: без него транзакция не увидит ни одной строки с кодом.
        Отсутствие тенанта поэтому не «полный доступ», а «доступ только
        к контуру входа»: тенанту, приглашениям и учётным записям, которые
        читаются до того, как членство выяснено.
        """
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._session: AsyncSession | None = None
        self._code_repositories: SqlAlchemyCodeRepositoryRepository | None = None
        self._review_runs: SqlAlchemyReviewRunRepository | None = None
        self._index_snapshots: SqlAlchemyIndexSnapshotRepository | None = None
        self._source_files: SqlAlchemySourceFileRepository | None = None
        self._symbol_edges: SqlAlchemySymbolEdgeRepository | None = None
        self._embeddings: SqlAlchemyEmbeddingStore | None = None
        self._conversations: SqlAlchemyConversationRepository | None = None
        self._tenants: SqlAlchemyTenantRepository | None = None
        self._user_accounts: SqlAlchemyUserAccountRepository | None = None
        self._invitations: SqlAlchemyInvitationRepository | None = None
        self._provider_connections: SqlAlchemyProviderConnectionRepository | None = None
        self._collected_events: list[DomainEvent] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of Work используется вне контекстного менеджера")
        return self._session

    @property
    def code_repositories(self) -> SqlAlchemyCodeRepositoryRepository:
        if self._code_repositories is None:
            self._code_repositories = SqlAlchemyCodeRepositoryRepository(self.session)
        return self._code_repositories

    @property
    def review_runs(self) -> SqlAlchemyReviewRunRepository:
        if self._review_runs is None:
            self._review_runs = SqlAlchemyReviewRunRepository(self.session)
        return self._review_runs

    @property
    def index_snapshots(self) -> SqlAlchemyIndexSnapshotRepository:
        if self._index_snapshots is None:
            self._index_snapshots = SqlAlchemyIndexSnapshotRepository(self.session)
        return self._index_snapshots

    @property
    def source_files(self) -> SqlAlchemySourceFileRepository:
        if self._source_files is None:
            self._source_files = SqlAlchemySourceFileRepository(self.session)
        return self._source_files

    @property
    def symbol_edges(self) -> SqlAlchemySymbolEdgeRepository:
        if self._symbol_edges is None:
            self._symbol_edges = SqlAlchemySymbolEdgeRepository(self.session)
        return self._symbol_edges

    @property
    def embeddings(self) -> SqlAlchemyEmbeddingStore:
        if self._embeddings is None:
            self._embeddings = SqlAlchemyEmbeddingStore(self.session)
        return self._embeddings

    @property
    def conversations(self) -> SqlAlchemyConversationRepository:
        if self._conversations is None:
            self._conversations = SqlAlchemyConversationRepository(self.session)
        return self._conversations

    @property
    def tenants(self) -> SqlAlchemyTenantRepository:
        if self._tenants is None:
            self._tenants = SqlAlchemyTenantRepository(self.session)
        return self._tenants

    @property
    def user_accounts(self) -> SqlAlchemyUserAccountRepository:
        if self._user_accounts is None:
            self._user_accounts = SqlAlchemyUserAccountRepository(self.session)
        return self._user_accounts

    @property
    def invitations(self) -> SqlAlchemyInvitationRepository:
        if self._invitations is None:
            self._invitations = SqlAlchemyInvitationRepository(self.session)
        return self._invitations

    @property
    def provider_connections(self) -> SqlAlchemyProviderConnectionRepository:
        if self._provider_connections is None:
            self._provider_connections = SqlAlchemyProviderConnectionRepository(self.session)
        return self._provider_connections

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Вложенные Unit of Work запрещены")
        self._session = self._session_factory()
        self._reset_repositories()
        self._collected_events = []
        await bind_tenant(self._session, self._tenant_id)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self.session
        try:
            await session.rollback()
        finally:
            await session.close()
            self._session = None
            self._reset_repositories()

    async def commit(self) -> None:
        self._absorb_aggregate_changes()
        await self.session.commit()
        await bind_tenant(self.session, self._tenant_id)

    async def rollback(self) -> None:
        self._collected_events = []
        await self.session.rollback()
        await bind_tenant(self.session, self._tenant_id)

    def collect_events(self) -> list[DomainEvent]:
        collected = self._collected_events
        self._collected_events = []
        return collected

    def record_events(self, events: list[DomainEvent]) -> None:
        self._collected_events.extend(events)

    def _active_repositories(self) -> list[TrackingRepository]:
        candidates: list[TrackingRepository | None] = [
            self._code_repositories,
            self._review_runs,
            self._index_snapshots,
            self._source_files,
            self._symbol_edges,
            self._conversations,
            self._tenants,
            self._user_accounts,
            self._invitations,
            self._provider_connections,
        ]
        return [repository for repository in candidates if repository is not None]

    def _absorb_aggregate_changes(self) -> None:
        for repository in self._active_repositories():
            repository.flush_changes()
            self._collected_events.extend(repository.collect_events())

    def _reset_repositories(self) -> None:
        self._code_repositories = None
        self._review_runs = None
        self._index_snapshots = None
        self._source_files = None
        self._symbol_edges = None
        self._embeddings = None
        self._conversations = None
        self._tenants = None
        self._user_accounts = None
        self._invitations = None
        self._provider_connections = None

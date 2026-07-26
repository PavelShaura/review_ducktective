from sqlalchemy import (
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.events import (
    DomainEvent,
)
from ducktective.core.exceptions import (
    EntityNotFoundError,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)
from ducktective.storage.mappers import code_repository as mapper
from ducktective.storage.models.code_repository import (
    CodeRepositoryModel,
)


class SqlAlchemyCodeRepositoryRepository:
    """Репозиторий агрегата CodeRepository.

    Отслеживает загруженные агрегаты, чтобы при коммите перенести их изменения
    в ORM-модели. Транзакцию не фиксирует — этим управляет Unit of Work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identity_map: dict[RepositoryId, tuple[CodeRepository, CodeRepositoryModel]] = {}

    def add(self, repository: CodeRepository) -> None:
        model = mapper.to_model(repository)
        self._session.add(model)
        self._identity_map[repository.id] = (repository, model)

    async def get(self, repository_id: RepositoryId) -> CodeRepository:
        tracked = self._identity_map.get(repository_id)
        if tracked is not None:
            return tracked[0]

        model = await self._session.get(CodeRepositoryModel, repository_id)
        if model is None:
            raise EntityNotFoundError("CodeRepository", repository_id)
        return self._track(model)

    async def find_by_name(self, tenant_id: TenantId, name: str) -> CodeRepository | None:
        statement = select(CodeRepositoryModel).where(
            CodeRepositoryModel.tenant_id == tenant_id,
            CodeRepositoryModel.name == name,
        )
        model = (await self._session.execute(statement)).scalar_one_or_none()
        if model is None:
            return None
        return self._track(model)

    async def list_for_tenant(self, tenant_id: TenantId) -> list[CodeRepository]:
        statement = (
            select(CodeRepositoryModel)
            .where(CodeRepositoryModel.tenant_id == tenant_id)
            .order_by(CodeRepositoryModel.name)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._track(model) for model in models]

    def flush_changes(self) -> None:
        """Переносит изменения агрегатов в ORM-модели перед коммитом."""
        for repository, model in self._identity_map.values():
            mapper.apply_changes(model, repository)

    def collect_events(self) -> list[DomainEvent]:
        collected: list[DomainEvent] = []
        for repository, _ in self._identity_map.values():
            collected.extend(repository.pull_events())
        return collected

    def _track(self, model: CodeRepositoryModel) -> CodeRepository:
        repository_id = RepositoryId(model.id)
        tracked = self._identity_map.get(repository_id)
        if tracked is not None:
            return tracked[0]

        repository = mapper.to_domain(model)
        self._identity_map[repository_id] = (repository, model)
        return repository

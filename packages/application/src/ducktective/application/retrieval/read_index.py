from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.embedders import (
    EmbedderCatalogue,
)
from ducktective.application.indexing.read_state import (
    GetIndexState,
)
from ducktective.application.retrieval.views import (
    RepositoryOverview,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.retrieval.navigation import (
    CodeNavigator,
    CodeNavigatorFactory,
    NavigationAnswer,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class SurveyRepositories:
    """Перечисляет репозитории тенанта вместе с состоянием их индексов.

    Точка входа для того, кто ещё ничего не знает: без неё имя репозитория
    приходится угадывать, а угадав — выяснять, отвечает ли он вообще.
    """

    def __init__(self, unit_of_work: UnitOfWork, *, embedders: EmbedderCatalogue) -> None:
        self._unit_of_work = unit_of_work
        self._read_state = GetIndexState(unit_of_work, embedders=embedders)

    async def execute(self, tenant_id: TenantId) -> list[RepositoryOverview]:
        async with self._unit_of_work:
            repositories = await self._unit_of_work.code_repositories.list_for_tenant(tenant_id)

        return [
            RepositoryOverview(
                repository_id=repository.id,
                name=repository.name,
                index=await self._read_state.execute(tenant_id, repository.id),
            )
            for repository in repositories
        ]


class NavigateCode:
    """Навигация по коду репозитория от имени тенанта.

    Use case добавляет к операциям навигатора ровно одно — проверку, что
    репозиторий принадлежит спрашивающему. Сами операции объявлены доменным
    портом и имеют две реализации, поэтому здесь их не по одной на класс:
    разница между «поискать» и «найти вызывающих» лежит в навигаторе,
    а не в правах доступа (D-021).
    """

    def __init__(self, unit_of_work: UnitOfWork, navigators: CodeNavigatorFactory) -> None:
        self._unit_of_work = unit_of_work
        self._navigators = navigators

    async def search_code(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        query: str,
        *,
        limit: int = 10,
    ) -> NavigationAnswer:
        navigator = await self._navigator(tenant_id, repository_id)
        return await navigator.search_code(query, limit=limit)

    async def get_definition(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        name: str,
        *,
        limit: int = 5,
    ) -> NavigationAnswer:
        navigator = await self._navigator(tenant_id, repository_id)
        return await navigator.get_definition(name, limit=limit)

    async def find_callers(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        name: str,
        *,
        limit: int = 20,
    ) -> NavigationAnswer:
        navigator = await self._navigator(tenant_id, repository_id)
        return await navigator.find_callers(name, limit=limit)

    async def get_file_context(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        path: str,
        *,
        start_line: int,
        end_line: int,
        limit: int = 10,
    ) -> NavigationAnswer:
        navigator = await self._navigator(tenant_id, repository_id)
        return await navigator.get_file_context(
            path,
            start_line=start_line,
            end_line=end_line,
            limit=limit,
        )

    async def _navigator(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
    ) -> CodeNavigator:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

        return self._navigators.for_repository(repository_id)

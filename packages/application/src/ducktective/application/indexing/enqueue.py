from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.core.diff.ports import (
    VcsProvider,
)
from ducktective.core.indexing.entities import (
    IndexSnapshot,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.types import (
    IndexSnapshotId,
    RepositoryId,
    TenantId,
)


class IndexingAlreadyQueuedError(ApplicationError):
    """Индексация этого репозитория уже стоит в очереди или идёт."""


class EnqueueIndexing(TransactionalUseCase):
    """Заводит снапшот в состоянии ожидания перед постановкой задачи в очередь.

    След в базе появляется здесь, а не у воркера, и это принципиально.
    Пока снапшота нет, «в очереди» существует только в памяти вкладки:
    оно теряется при перезагрузке, а отменить нечего — отмена ищет
    незавершённый снапшот и, не найдя, молча ничего не делает.
    Задача при этом остаётся в очереди и срабатывает, когда воркер поднимут.

    Ревизия разрешается здесь же и вне транзакции: снапшот обязан знать свой
    коммит, а спрашивать его у git внутри открытой транзакции нельзя.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        vcs_provider: VcsProvider,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._vcs_provider = vcs_provider

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        revision: str,
    ) -> IndexSnapshotId:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            latest = await self._unit_of_work.index_snapshots.find_latest(repository_id)
            if latest is not None and not latest.is_finished:
                raise IndexingAlreadyQueuedError(
                    "Индексация этого репозитория уже идёт — дождитесь её или отмените"
                )

            repository_path = repository.local_path
            previous = await self._unit_of_work.index_snapshots.find_latest_ready(repository_id)
            parent_id = previous.id if previous else None

        commit_sha = await self._vcs_provider.resolve_revision(repository_path, revision)

        async with self._unit_of_work:
            snapshot = IndexSnapshot.create(
                repository_id=repository_id,
                commit_sha=commit_sha,
                parent_snapshot_id=parent_id,
            )
            self._unit_of_work.index_snapshots.add(snapshot)
            await self._commit_and_publish()

        return snapshot.id

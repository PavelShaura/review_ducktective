from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.application.indexing.embedders import (
    EmbedderCatalogue,
)
from ducktective.application.indexing.views import (
    IndexStateView,
)
from ducktective.core.indexing.ports import (
    IndexTotals,
)
from ducktective.core.indexing.value_objects import (
    SnapshotStatus,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class GetIndexState:
    """Отдаёт состояние индекса репозитория.

    Отсутствие снапшота — не ошибка, а обычное состояние нового репозитория,
    поэтому возвращается пустое представление, а не исключение.
    """

    def __init__(self, unit_of_work: UnitOfWork, *, embedders: EmbedderCatalogue) -> None:
        self._unit_of_work = unit_of_work
        self._embedders = embedders

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
    ) -> IndexStateView:
        async with self._unit_of_work:
            repository = await self._unit_of_work.code_repositories.get(repository_id)
            if repository.tenant_id != tenant_id:
                raise PermissionDeniedError("Репозиторий принадлежит другому тенанту")

            embedder = self._embedders.resolve(repository.embedding_backend)
            snapshot = await self._unit_of_work.index_snapshots.find_latest(repository_id)
            if snapshot is None:
                return IndexStateView(embedding_backend=embedder.key)

            context_ready = snapshot.status is SnapshotStatus.READY or (
                await self._unit_of_work.index_snapshots.find_latest_ready(repository_id)
                is not None
            )
            vectors = await self._unit_of_work.embeddings.count_coverage(
                repository_id, embedder.vector_set
            )
            counted = await self._unit_of_work.source_files.count_totals(repository_id)
            totals = IndexTotals(
                files=counted.files,
                symbols=counted.symbols,
                chunks=counted.chunks,
                edges=await self._unit_of_work.symbol_edges.count_resolved(repository_id),
            )

            return IndexStateView(
                snapshot_id=snapshot.id,
                status=snapshot.status,
                stage=snapshot.stage,
                commit_sha=snapshot.commit_sha,
                stats=snapshot.stats,
                started_at=snapshot.started_at,
                finished_at=snapshot.finished_at,
                failure_reason=snapshot.failure_reason,
                embedding_stopped=snapshot.embedding_stopped,
                totals=totals,
                embedding_backend=embedder.key,
                context_ready=context_ready,
                vectors=vectors,
            )

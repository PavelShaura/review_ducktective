from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.types import (
    RepositoryId,
    ReviewRunId,
    TenantId,
)


class GetReviewRun:
    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(self, tenant_id: TenantId, run_id: ReviewRunId) -> ReviewRun:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")
            return run


class ListReviewRuns:
    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        *,
        limit: int = 50,
    ) -> list[ReviewRun]:
        async with self._unit_of_work:
            runs = await self._unit_of_work.review_runs.list_for_repository(
                repository_id,
                limit=limit,
            )
            return [run for run in runs if run.tenant_id == tenant_id]

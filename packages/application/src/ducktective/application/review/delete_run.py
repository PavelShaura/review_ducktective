from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.types import (
    ReviewRunId,
    TenantId,
)


class DeleteReviewRun(TransactionalUseCase):
    """Удаляет прогон вместе с его находками и разметкой.

    Разметка находок — данные для оценки качества, поэтому удаление всегда
    осознанное действие пользователя, а не следствие чего-то ещё.
    """

    async def execute(self, tenant_id: TenantId, run_id: ReviewRunId) -> None:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")

            run.record_deletion()
            await self._unit_of_work.review_runs.remove(run)
            await self._commit_and_publish()

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


class CancelReviewRun(TransactionalUseCase):
    """Просит прекратить идущее расследование.

    Прогон не обрывается на месте: он помечается отменённым, а воркер видит
    это перед следующим файлом и выходит. Файл, который модель читает прямо
    сейчас, дочитывается — прерывать запрос к модели на середине незачем,
    результат всё равно не сохранится.
    """

    async def execute(self, tenant_id: TenantId, run_id: ReviewRunId) -> bool:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")
            if run.is_finished:
                return False

            run.cancel()
            await self._commit_and_publish()
            return True

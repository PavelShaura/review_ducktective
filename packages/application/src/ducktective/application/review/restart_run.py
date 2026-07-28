from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.types import (
    ReviewRunId,
    TenantId,
)


class RunNotRestartableError(ApplicationError):
    def __init__(self, status: str) -> None:
        super().__init__(f"Прогон в статусе {status} нельзя расследовать заново")


class RestartReviewRun(TransactionalUseCase):
    """Возвращает прекращённый или неудавшийся прогон в очередь.

    Дифф разбирать заново не нужно — файлы и ханки уже лежат в прогоне,
    поэтому повторяется только чтение моделью. Возобновления с места здесь
    нет: находки пишутся одной транзакцией в конце, промежуточного
    состояния не существует.
    """

    async def execute(self, tenant_id: TenantId, run_id: ReviewRunId) -> ReviewRun:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")
            if not run.is_restartable:
                raise RunNotRestartableError(run.status.value)

            run.restart()
            await self._commit_and_publish()
            return run

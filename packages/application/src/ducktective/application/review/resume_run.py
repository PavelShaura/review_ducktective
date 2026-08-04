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


class RunNotResumableError(ApplicationError):
    def __init__(self, status: str) -> None:
        super().__init__(f"Прогон в статусе {status} нельзя продолжить")


class ResumeReviewRun(TransactionalUseCase):
    """Возвращает прерванный прогон в очередь, не стирая проделанного.

    От «расследовать заново» отличается одним: сохранённый ход прогона
    остаётся, и уже прочитанные пары «файл × ревьюер» второй раз не читаются.
    При локальной модели в 19 токенов в секунду это и есть вся разница между
    минутами и часами.

    Забывает ход не этот use case, а `RunReview` перед прогоном с начала:
    решение принимает тот, кто запускает конвейер, иначе оно расходится
    с тем, что конвейер потом делает.
    """

    async def execute(self, tenant_id: TenantId, run_id: ReviewRunId) -> ReviewRun:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")
            if not run.is_restartable:
                raise RunNotResumableError(run.status.value)

            run.resume()
            await self._commit_and_publish()
            return run

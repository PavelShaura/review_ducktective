from dataclasses import (
    dataclass,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.review.entities import (
    FindingFeedback,
)
from ducktective.core.review.value_objects import (
    FeedbackVerdict,
)
from ducktective.core.types import (
    FindingId,
    ReviewRunId,
    TenantId,
    UserId,
)


@dataclass(frozen=True, kw_only=True)
class SubmitFindingFeedbackCommand:
    tenant_id: TenantId
    run_id: ReviewRunId
    finding_id: FindingId
    verdict: FeedbackVerdict
    comment: str | None = None
    user_id: UserId | None = None


class SubmitFindingFeedback(TransactionalUseCase):
    """Фиксирует оценку находки.

    Отметки накапливаются как размеченная выборка: на ней измеряется precision
    и проверяется, что изменения ретривала и промптов действительно улучшают
    качество.
    """

    async def execute(self, command: SubmitFindingFeedbackCommand) -> FindingFeedback:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(command.run_id)
            if run.tenant_id != command.tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")

            entry = run.submit_feedback(
                command.finding_id,
                command.verdict,
                user_id=command.user_id,
                comment=command.comment,
            )
            await self._commit_and_publish()
            return entry

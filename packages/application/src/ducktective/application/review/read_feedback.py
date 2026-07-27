from collections import (
    Counter,
)

from ducktective.application.review.views import (
    FeedbackDigestView,
    MarkedFindingView,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.types import (
    RepositoryId,
    TenantId,
)


class CollectFeedback:
    """Собирает отметки, проставленные человеком на находках репозитория.

    Отметки — источник набора для оценки качества, но лежат они порознь внутри
    прогонов. Сводка нужна, чтобы видеть, сколько размеченного материала уже
    накопилось и каково соотношение подтверждённых находок к ложным.

    Берётся последняя отметка находки: мнение можно менять, и решением
    считается свежее.
    """

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    async def execute(
        self,
        tenant_id: TenantId,
        repository_id: RepositoryId,
        *,
        runs_limit: int = 50,
    ) -> FeedbackDigestView:
        async with self._unit_of_work:
            runs = await self._unit_of_work.review_runs.list_for_repository(
                repository_id,
                limit=runs_limit,
            )
            owned = [run for run in runs if run.tenant_id == tenant_id]

        marked = [view for run in owned for view in _marked_findings(run)]
        marked.sort(key=lambda item: item.marked_at, reverse=True)

        return FeedbackDigestView(
            marked=tuple(marked),
            counts=dict(Counter(item.verdict.value for item in marked)),
            total_findings=sum(len(run.findings) for run in owned),
        )


def _marked_findings(run: ReviewRun) -> list[MarkedFindingView]:
    views: list[MarkedFindingView] = []
    for finding in run.findings:
        entry = finding.latest_feedback
        if entry is None:
            continue

        views.append(
            MarkedFindingView(
                run_id=run.id,
                finding_id=finding.id,
                file_path=finding.file_path,
                line_start=finding.line_start,
                severity=finding.severity,
                category=finding.category,
                title=finding.title,
                producer_name=finding.producer_name,
                verdict=entry.verdict,
                comment=entry.comment,
                marked_at=entry.created_at,
            )
        )
    return views

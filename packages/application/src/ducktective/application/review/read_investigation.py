from dataclasses import (
    dataclass,
)

from ducktective.application.exceptions import (
    PermissionDeniedError,
)
from ducktective.core.ports import (
    UnitOfWork,
)
from ducktective.core.review.investigation import (
    InvestigationLog,
    StepKind,
)
from ducktective.core.types import (
    ReviewRunId,
    TenantId,
)


DEFAULT_PAGE = 200


@dataclass(frozen=True, kw_only=True)
class InvestigationStepView:
    """Шаг расследования, каким его видит интерфейс."""

    cursor: int
    file_path: str
    number: int
    kind: StepKind
    tool_name: str | None
    arguments: str | None
    detail: str
    duration_ms: int
    is_error: bool


@dataclass(frozen=True, kw_only=True)
class InvestigationView:
    """Кусок ленты вместе с местом, с которого её продолжать."""

    steps: tuple[InvestigationStepView, ...]
    next_cursor: int


class ReadInvestigation:
    """Отдаёт ход расследования по прогону.

    Читается кусками от курсора: лента дописывается по ходу работы, и клиент
    спрашивает не «всю трассу заново», а «что появилось с прошлого раза».
    """

    def __init__(self, unit_of_work: UnitOfWork, log: InvestigationLog) -> None:
        self._unit_of_work = unit_of_work
        self._log = log

    async def execute(
        self,
        tenant_id: TenantId,
        run_id: ReviewRunId,
        *,
        after: int = 0,
        limit: int = DEFAULT_PAGE,
    ) -> InvestigationView:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")

        recorded = await self._log.list_for_run(run_id, after=after, limit=limit)
        steps = tuple(
            InvestigationStepView(
                cursor=item.cursor,
                file_path=item.step.file_path,
                number=item.step.number,
                kind=item.step.kind,
                tool_name=item.step.tool_name,
                arguments=item.step.arguments,
                detail=item.step.detail,
                duration_ms=item.step.duration_ms,
                is_error=item.step.is_error,
            )
            for item in recorded
        )
        return InvestigationView(
            steps=steps,
            next_cursor=steps[-1].cursor if steps else after,
        )

from sqlalchemy import (
    select,
)
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
)

from ducktective.core.review.investigation import (
    InvestigationStep,
    RecordedStep,
)
from ducktective.core.types import (
    ReviewRunId,
    TenantId,
)
from ducktective.storage.models.review import (
    InvestigationStepModel,
)
from ducktective.storage.tenant_scope import (
    bind_tenant,
)


class SqlAlchemyInvestigationLog:
    """Ход расследования в Postgres.

    Сессия открывается своя на каждую запись, а не берётся из Unit of Work
    прогона: шаги пишутся между обращениями к модели, пока конвейер работает
    минутами, и удерживать ради них транзакцию нельзя (D-016). Цена —
    короткая транзакция на шаг; их десятки на прогон, а не тысячи.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,  # type: ignore[type-arg]
        *,
        tenant_id: TenantId | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id

    async def append(self, run_id: ReviewRunId, step: InvestigationStep) -> RecordedStep:
        model = InvestigationStepModel(
            run_id=run_id,
            file_path=step.file_path,
            number=step.number,
            kind=step.kind,
            tool_name=step.tool_name,
            arguments=step.arguments,
            detail=step.detail,
            duration_ms=step.duration_ms,
            is_error=step.is_error,
        )
        async with self._session_factory() as session, session.begin():
            await bind_tenant(session, self._tenant_id)
            session.add(model)
            await session.flush()
            cursor = model.id

        return RecordedStep(cursor=cursor, step=step)

    async def list_for_run(
        self,
        run_id: ReviewRunId,
        *,
        after: int = 0,
        limit: int = 500,
    ) -> list[RecordedStep]:
        statement = (
            select(InvestigationStepModel)
            .where(InvestigationStepModel.run_id == run_id)
            .where(InvestigationStepModel.id > after)
            .order_by(InvestigationStepModel.id)
            .limit(limit)
        )
        async with self._session_factory() as session:
            await bind_tenant(session, self._tenant_id)
            models = (await session.scalars(statement)).all()

        return [_to_recorded(model) for model in models]


def _to_recorded(model: InvestigationStepModel) -> RecordedStep:
    return RecordedStep(
        cursor=model.id,
        step=InvestigationStep(
            file_path=model.file_path,
            number=model.number,
            kind=model.kind,
            tool_name=model.tool_name,
            arguments=model.arguments,
            detail=model.detail,
            duration_ms=model.duration_ms,
            is_error=model.is_error,
        ),
    )

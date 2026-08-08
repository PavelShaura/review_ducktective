from typing import (
    Protocol,
)

from ducktective.core.review.investigation import (
    InvestigationLog,
    InvestigationSink,
    InvestigationStep,
    RecordedStep,
)
from ducktective.core.types import (
    ReviewRunId,
)
from ducktective.observability.logging import (
    get_logger,
)


logger = get_logger(__name__)


class StepBroadcaster(Protocol):
    """Рассылка шага тем, кто смотрит за прогоном прямо сейчас."""

    async def publish(self, run_id: ReviewRunId, recorded: RecordedStep) -> None: ...


class RecordingInvestigationSink:
    """Записывает ход расследования и рассылает его наблюдающим.

    Сбой записи не прерывает ревью: лента — способ смотреть за работой,
    а не сама работа, и падать из-за неё посреди расследования значит менять
    результат прогона ради его отображения.
    """

    def __init__(
        self,
        log: InvestigationLog,
        run_id: ReviewRunId,
        *,
        broadcaster: StepBroadcaster | None = None,
    ) -> None:
        self._log = log
        self._run_id = run_id
        self._broadcaster = broadcaster

    async def record(self, step: InvestigationStep) -> None:
        try:
            recorded = await self._log.append(self._run_id, step)
        except Exception as error:
            logger.warning(
                "investigation.step_not_saved", run_id=str(self._run_id), error=str(error)
            )
            return

        if self._broadcaster is None:
            return

        try:
            await self._broadcaster.publish(self._run_id, recorded)
        except Exception as error:
            logger.warning(
                "investigation.step_not_broadcast",
                run_id=str(self._run_id),
                error=str(error),
            )


class RecordingInvestigationSinks:
    """Слушатели хода — по одному на прогон."""

    def __init__(
        self,
        log: InvestigationLog,
        *,
        broadcaster: StepBroadcaster | None = None,
    ) -> None:
        self._log = log
        self._broadcaster = broadcaster

    def for_run(self, run_id: ReviewRunId) -> InvestigationSink:
        return RecordingInvestigationSink(self._log, run_id, broadcaster=self._broadcaster)

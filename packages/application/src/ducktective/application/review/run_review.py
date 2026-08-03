from dataclasses import (
    dataclass,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.core.llm.value_objects import (
    ModelRequirements,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.review.entities import (
    ReviewRun,
)
from ducktective.core.review.pipeline import (
    PipelineRequest,
)
from ducktective.core.review.ports import (
    ReviewPipeline,
)
from ducktective.core.review.value_objects import (
    ReviewStatus,
)
from ducktective.core.types import (
    ReviewRunId,
    TenantId,
)


DEFAULT_MAX_OUTPUT_TOKENS = ModelRequirements().max_output_tokens


class ReviewCancelledError(ApplicationError):
    """Расследование попросили прекратить.

    Ничего не сохраняется: находки пишутся одной транзакцией в конце,
    и половина прогона результатом не является.
    """

    def __init__(self) -> None:
        super().__init__("Расследование прекращено")


class RunNotReviewableError(ApplicationError):
    def __init__(self, status: ReviewStatus) -> None:
        super().__init__(f"Прогон в статусе {status} нельзя отправить на ревью")
        self.status = status


@dataclass(frozen=True, kw_only=True)
class ReviewOutcome:
    """Итог прогона вместе с тем, что было отброшено по дороге.

    Без этих чисел «находок 0» означает сразу две разные ситуации: модель
    ничего не нашла или все её ответы не прошли проверку. Различать их нужно,
    иначе непонятно, что чинить — промпт или фильтры.
    """

    run: ReviewRun
    proposed: int = 0
    discarded_outside_diff: int = 0
    discarded_without_evidence: int = 0
    discarded_as_duplicate: int = 0
    failed_files: tuple[str, ...] = ()
    files_with_context: int = 0

    @property
    def discarded(self) -> int:
        return (
            self.discarded_outside_diff
            + self.discarded_without_evidence
            + self.discarded_as_duplicate
        )


class RunReview(TransactionalUseCase):
    """Прогоняет подготовленный дифф через конвейер ревью.

    Транзакция не удерживается на время работы конвейера: статус переводится
    в running и фиксируется, граф отрабатывает вне транзакции, находки
    записываются отдельной короткой транзакцией.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        pipeline: ReviewPipeline,
        *,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._pipeline = pipeline
        self._max_output_tokens = max_output_tokens

    async def _is_cancelled(self, run_id: ReviewRunId) -> bool:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            return run.is_cancelled

    async def execute(self, tenant_id: TenantId, run_id: ReviewRunId) -> ReviewOutcome:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")
            if run.status is not ReviewStatus.QUEUED:
                raise RunNotReviewableError(run.status)

            repository = await self._unit_of_work.code_repositories.get(run.repository_id)
            request = PipelineRequest(
                repository_id=run.repository_id,
                files=tuple(run.reviewable_files()),
                requirements=ModelRequirements(
                    needs_deep_reasoning=True,
                    cloud_allowed=repository.cloud_processing_allowed,
                    max_output_tokens=self._max_output_tokens,
                ),
            )
            run.mark_running()
            await self._commit_and_publish()

        result = await self._pipeline.run(
            request,
            cancellation=lambda: self._is_cancelled(run_id),
        )
        if result.is_cancelled:
            raise ReviewCancelledError

        duplicates = result.discarded_as_duplicate

        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            run.record_usage(result.usage)
            run.record_context_usage(result.files_with_context)

            for finding in result.findings:
                if not run.add_finding(finding):
                    duplicates += 1

            run.record_node_failures(result.degradations)

            if result.failed_files and not result.reviewed_files:
                run.mark_failed("\n".join(result.failed_files))
            else:
                if result.failed_files:
                    run.record_degradation(
                        _describe_failures(
                            result.failed_files,
                            unreviewed=len(result.unreviewed_files),
                            total_files=len(request.files),
                        )
                    )
                run.mark_completed()

            await self._commit_and_publish()

            return ReviewOutcome(
                run=run,
                proposed=result.proposed,
                discarded_outside_diff=result.discarded_outside_diff,
                discarded_without_evidence=result.discarded_without_evidence,
                discarded_as_duplicate=duplicates,
                failed_files=result.failed_files,
                files_with_context=result.files_with_context,
            )


def _describe_failures(failures: tuple[str, ...], *, unreviewed: int, total_files: int) -> str:
    """Причины, по которым часть файлов осталась без ревью.

    Доля важнее перечня: она сразу говорит, стоит ли доверять пустому
    результату по остальным файлам. Считается она по файлам, которых
    не прочитал никто: сбой случается на паре «файл × ревьюер», и файл,
    упавший у одного из четверых, проревьюен — просто не всеми глазами.
    """
    headline = (
        f"Не проверено файлов: {unreviewed} из {total_files}."
        if unreviewed
        else "Часть ревьюеров не дочитала свои файлы — замечаний может быть меньше обычного."
    )
    return "\n".join([headline, *failures])

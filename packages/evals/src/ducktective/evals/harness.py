from dataclasses import (
    dataclass,
)
from pathlib import (
    Path,
)
from uuid import (
    uuid4,
)

from ducktective.application.review.run_review import (
    RunReview,
)
from ducktective.core.code_repository.entities import (
    CodeRepository,
)
from ducktective.core.code_repository.value_objects import (
    VcsProvider,
)
from ducktective.core.diff.ports import (
    DiffParser,
)
from ducktective.core.exceptions import (
    DomainError,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.retrieval.ports import (
    ContextBuilder,
)
from ducktective.core.review.entities import (
    ReviewFile,
    ReviewRun,
)
from ducktective.core.review.ports import (
    CodeReviewer,
)
from ducktective.core.review.value_objects import (
    ReviewSource,
)
from ducktective.core.types import (
    CommitSha,
    RepositoryId,
    TenantId,
)
from ducktective.evals.cases import (
    EvalCase,
    EvalDataset,
)
from ducktective.evals.metrics import (
    CaseOutcome,
    Metrics,
    MetricsBuilder,
)
from ducktective.storage.events.null_publisher import (
    NullEventPublisher,
)
from ducktective.storage.memory.unit_of_work import (
    InMemoryUnitOfWork,
)


_EVAL_PATH = Path("/eval")

BASE_SHA = CommitSha("0" * 40)
HEAD_SHA = CommitSha("1" * 40)


@dataclass(frozen=True, kw_only=True)
class EvaluationOutcome:
    label: str
    metrics: Metrics
    outcomes: tuple[CaseOutcome, ...]
    attempts: tuple[Metrics, ...] = ()

    @property
    def mean_recall(self) -> float:
        return (
            sum(item.recall for item in self.attempts) / len(self.attempts)
            if self.attempts
            else 0.0
        )

    @property
    def recall_spread(self) -> tuple[float, float]:
        """Худший и лучший прогон: разброс важнее среднего, когда он велик."""
        if not self.attempts:
            return (0.0, 0.0)
        values = [item.recall for item in self.attempts]
        return (min(values), max(values))


class _IndexedRepositoryContext:
    """Подменяет репозиторий на тот, для которого построен индекс.

    Случай набора живёт в хранилище на словарях и своего индекса не имеет;
    контекст берётся у настоящего проиндексированного репозитория, иначе
    обход графа возвращает пустоту, а прогон «с контекстом» тихо оказывается
    прогоном без него.
    """

    def __init__(self, inner: ContextBuilder, repository_id: RepositoryId) -> None:
        self._inner = inner
        self._repository_id = repository_id

    async def build(self, repository_id: RepositoryId, file: ReviewFile) -> DiffContext:
        return await self._inner.build(self._repository_id, file)


class EvaluationHarness:
    """Прогоняет набор случаев через тот же путь, что и настоящее ревью.

    Проверяется вся система, а не только модель: черновики проходят ту же
    проверку доказательств и ту же привязку к строкам, иначе цифра говорила бы
    о качестве ответов, а не о качестве того, что доходит до человека.

    Хранилище — в памяти: набор не должен зависеть от состояния базы, иначе
    повторный прогон перестаёт быть повторным.
    """

    def __init__(
        self,
        reviewer: CodeReviewer,
        diff_parser: DiffParser,
        *,
        context_builder: ContextBuilder | None = None,
        indexed_repository_id: RepositoryId | None = None,
    ) -> None:
        self._reviewer = reviewer
        self._diff_parser = diff_parser
        self._context_builder = (
            _IndexedRepositoryContext(context_builder, indexed_repository_id)
            if context_builder is not None and indexed_repository_id is not None
            else context_builder
        )

    async def run(
        self,
        dataset: EvalDataset,
        *,
        label: str,
        repeats: int = 1,
    ) -> EvaluationOutcome:
        """Прогоняет набор, при необходимости несколько раз.

        Повторы нужны не для надёжности, а потому что модель отвечает
        по-разному на один и тот же запрос: одиночный прогон меряет удачу,
        а не качество.
        """
        attempts: list[Metrics] = []
        last: list[CaseOutcome] = []

        for _ in range(max(repeats, 1)):
            builder = MetricsBuilder()
            for case in dataset.cases:
                builder.add(await self._run_case(case))

            attempts.append(builder.build())
            last = builder.outcomes

        return EvaluationOutcome(
            label=label,
            metrics=attempts[-1],
            outcomes=tuple(last),
            attempts=tuple(attempts),
        )

    async def _run_case(self, case: EvalCase) -> CaseOutcome:
        unit_of_work = InMemoryUnitOfWork()
        tenant_id = TenantId(uuid4())

        try:
            diff = self._diff_parser.parse(case.patch, base_sha=BASE_SHA, head_sha=HEAD_SHA)
        except DomainError as error:
            return CaseOutcome(case=case, failure=f"патч не разобран: {error}")

        async with unit_of_work:
            repository = CodeRepository.register(
                tenant_id=tenant_id,
                name=f"eval-{case.name}",
                vcs_provider=VcsProvider.LOCAL,
                local_path=_EVAL_PATH,
            )
            unit_of_work.code_repositories.add(repository)

            run = ReviewRun.create(
                tenant_id=tenant_id,
                repository_id=repository.id,
                source=ReviewSource.LOCAL_DIFF,
                diff=diff,
            )
            unit_of_work.review_runs.add(run)
            await unit_of_work.commit()

        try:
            outcome = await RunReview(
                unit_of_work,
                NullEventPublisher(),
                self._reviewer,
                self._context_builder,
            ).execute(tenant_id, run.id)
        except DomainError as error:
            return CaseOutcome(case=case, failure=str(error))

        return CaseOutcome(
            case=case,
            findings=tuple(outcome.run.findings),
            had_context=outcome.files_with_context > 0,
        )

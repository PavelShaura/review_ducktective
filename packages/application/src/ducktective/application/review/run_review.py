from dataclasses import (
    dataclass,
)
from uuid import (
    uuid4,
)

from ducktective.application.base import (
    TransactionalUseCase,
)
from ducktective.application.exceptions import (
    ApplicationError,
    PermissionDeniedError,
)
from ducktective.core.exceptions import (
    DomainError,
)
from ducktective.core.llm.value_objects import (
    LlmUsage,
    ModelRequirements,
)
from ducktective.core.ports import (
    EventPublisher,
    UnitOfWork,
)
from ducktective.core.retrieval.context import (
    DiffContext,
)
from ducktective.core.retrieval.ports import (
    ContextBuilder,
)
from ducktective.core.review.dedup import (
    build_dedup_key,
)
from ducktective.core.review.drafts import (
    FindingDraft,
)
from ducktective.core.review.entities import (
    Evidence,
    Finding,
    ReviewFile,
    ReviewRun,
)
from ducktective.core.review.ports import (
    CodeReviewer,
)
from ducktective.core.review.value_objects import (
    EvidenceKind,
    FindingProducer,
    FindingStatus,
    ReviewStatus,
)
from ducktective.core.types import (
    FindingId,
    RepositoryId,
    ReviewRunId,
    TenantId,
)


WHITESPACE = " \t\r\n"


@dataclass(frozen=True, kw_only=True)
class _EvidenceSource:
    """Текст, в котором ищется цитата, вместе с его происхождением."""

    normalized_text: str
    kind: EvidenceKind
    file_path: str
    line_start: int
    line_end: int


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
    """Прогоняет подготовленный дифф через ревьюера.

    Транзакция не удерживается на время обращения к модели: статус переводится
    в running и фиксируется, файлы ревьюятся вне транзакции, находки
    записываются отдельной короткой транзакцией.
    """

    def __init__(
        self,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher,
        reviewer: CodeReviewer,
        context_builder: ContextBuilder | None = None,
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._reviewer = reviewer
        self._context_builder = context_builder

    async def _build_context(
        self,
        repository_id: RepositoryId,
        file: ReviewFile,
    ) -> DiffContext | None:
        """Собирает окружение изменений, если индекс доступен.

        Отсутствие или поломка индекса не отменяют ревью: оно продолжается
        по одному диффу, а число файлов с контекстом попадает в итог прогона,
        чтобы разницу в качестве не приходилось угадывать.
        """
        if self._context_builder is None:
            return None

        try:
            return await self._context_builder.build(repository_id, file)
        except DomainError:
            return None

    async def _ensure_not_cancelled(self, run_id: ReviewRunId) -> None:
        """Сверяется с просьбой прекратить перед очередным файлом.

        Между файлами — единственная дешёвая отсечка: чтение одного файла
        занимает десятки секунд, а прерывать запрос к модели на середине
        нечем и незачем.
        """
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.is_cancelled:
                raise ReviewCancelledError

    async def execute(self, tenant_id: TenantId, run_id: ReviewRunId) -> ReviewOutcome:
        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            if run.tenant_id != tenant_id:
                raise PermissionDeniedError("Прогон принадлежит другому тенанту")
            if run.status is not ReviewStatus.QUEUED:
                raise RunNotReviewableError(run.status)

            repository = await self._unit_of_work.code_repositories.get(run.repository_id)
            requirements = ModelRequirements(
                needs_deep_reasoning=True,
                cloud_allowed=repository.cloud_processing_allowed,
            )
            files = run.reviewable_files()
            repository_id = run.repository_id
            run.mark_running()
            await self._commit_and_publish()

        drafts_by_file: list[tuple[ReviewFile, list[FindingDraft], DiffContext | None]] = []
        total_usage = LlmUsage()
        failures: list[str] = []
        contextual_files = 0

        for file in files:
            await self._ensure_not_cancelled(run_id)
            context = await self._build_context(repository_id, file)
            try:
                result = await self._reviewer.review_file(
                    file,
                    patch_text=file.to_unified_patch(),
                    requirements=requirements,
                    context=context,
                )
            except DomainError as error:
                failures.append(f"{file.path}: {error}")
                continue

            drafts_by_file.append((file, result.drafts, context))
            total_usage = _accumulate(total_usage, result.usage)
            if context is not None and not context.is_empty:
                contextual_files += 1

        proposed = 0
        outside_diff = 0
        without_evidence = 0
        duplicates = 0

        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            run.record_usage(total_usage)
            run.record_context_usage(contextual_files)

            for file, drafts, context in drafts_by_file:
                for draft in drafts:
                    proposed += 1
                    if not file.covers_line(draft.line_start):
                        outside_diff += 1
                        continue

                    finding = _build_finding(draft, file, context)
                    if finding is None:
                        without_evidence += 1
                        continue

                    if not run.add_finding(finding):
                        duplicates += 1

            if failures and not drafts_by_file:
                run.mark_failed("; ".join(failures))
            else:
                run.mark_completed()

            await self._commit_and_publish()

            return ReviewOutcome(
                run=run,
                proposed=proposed,
                discarded_outside_diff=outside_diff,
                discarded_without_evidence=without_evidence,
                discarded_as_duplicate=duplicates,
                failed_files=tuple(failures),
                files_with_context=contextual_files,
            )


def _accumulate(total: LlmUsage, addition: LlmUsage) -> LlmUsage:
    return LlmUsage(
        input_tokens=total.input_tokens + addition.input_tokens,
        output_tokens=total.output_tokens + addition.output_tokens,
        cost_usd=total.cost_usd + addition.cost_usd,
    )


def _build_finding(
    draft: FindingDraft,
    file: ReviewFile,
    context: DiffContext | None = None,
) -> Finding | None:
    """Превращает черновик в находку, отбраковывая недостоверные.

    Находка без подтверждённой цитаты не создаётся: это типичный признак
    выдуманного контекста. Принадлежность строки диффу проверяется раньше,
    на уровне вызывающего кода, чтобы различать причины отбраковки.
    """
    evidence = _collect_evidence(draft, file.to_unified_patch(), context)
    if not evidence:
        return None

    return Finding(
        id=FindingId(uuid4()),
        file_path=file.path,
        line_start=draft.line_start,
        line_end=draft.line_end,
        side=draft.side,
        severity=draft.severity,
        category=draft.category,
        title=draft.title,
        body_markdown=draft.body_markdown,
        dedup_key=build_dedup_key(
            category=draft.category,
            rule_id=None,
            symbol_name=draft.anchor_symbol,
            file_path=file.path,
            code_fragment=draft.code_fragment or draft.title,
        ),
        producer=FindingProducer.LLM,
        producer_name="reviewer:single-pass",
        suggested_patch=draft.suggested_patch,
        confidence=draft.confidence,
        status=FindingStatus.VERIFIED,
        evidence=evidence,
    )


def _collect_evidence(
    draft: FindingDraft,
    patch_text: str,
    context: DiffContext | None,
) -> list[Evidence]:
    """Оставляет только те цитаты, которые действительно существуют.

    Искать их приходится и в патче, и в показанном окружении: получив контекст,
    модель ссылается на вызывающий код, и такая ссылка — самое ценное, что она
    может сказать. Проверка от этого не слабеет, потому что окружение — это
    ровно то, что мы ей показали, а не то, что она придумала.
    """
    candidates = [item.snippet for item in draft.evidence]
    if draft.code_fragment:
        candidates.append(draft.code_fragment)

    sources = _evidence_sources(draft, patch_text, context)

    confirmed: list[Evidence] = []
    seen: set[str] = set()
    for snippet in candidates:
        normalized = _normalize(snippet)
        if not normalized or normalized in seen:
            continue

        source = next((item for item in sources if normalized in item.normalized_text), None)
        if source is None:
            continue

        seen.add(normalized)
        confirmed.append(
            Evidence(
                kind=source.kind,
                file_path=source.file_path,
                snippet=snippet.strip(),
                line_start=source.line_start,
                line_end=source.line_end,
            )
        )
    return confirmed


def _evidence_sources(
    draft: FindingDraft,
    patch_text: str,
    context: DiffContext | None,
) -> list[_EvidenceSource]:
    """Тексты, в которых цитата считается подтверждённой.

    Патч идёт первым: если строка встречается и в нём, и в окружении, находка
    относится к изменению, а не к соседнему коду.
    """
    sources = [
        _EvidenceSource(
            normalized_text=_normalize(patch_text),
            kind=EvidenceKind.QUOTED_CODE,
            file_path=draft.file_path,
            line_start=draft.line_start,
            line_end=draft.line_end,
        )
    ]
    sources.extend(
        _EvidenceSource(
            normalized_text=_normalize(piece.text),
            kind=EvidenceKind.RETRIEVED_CHUNK,
            file_path=piece.path,
            line_start=piece.start_line,
            line_end=piece.end_line,
        )
        for piece in (context.pieces if context else ())
    )
    return sources


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip(WHITESPACE)

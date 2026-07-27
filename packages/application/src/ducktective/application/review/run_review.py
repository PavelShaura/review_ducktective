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
    ReviewRunId,
    TenantId,
)


WHITESPACE = " \t\r\n"


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
    ) -> None:
        super().__init__(unit_of_work, event_publisher)
        self._reviewer = reviewer

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
            run.mark_running()
            await self._commit_and_publish()

        drafts_by_file: list[tuple[ReviewFile, list[FindingDraft]]] = []
        total_usage = LlmUsage()
        failures: list[str] = []

        for file in files:
            try:
                result = await self._reviewer.review_file(
                    file,
                    patch_text=file.to_unified_patch(),
                    requirements=requirements,
                )
            except DomainError as error:
                failures.append(f"{file.path}: {error}")
                continue

            drafts_by_file.append((file, result.drafts))
            total_usage = _accumulate(total_usage, result.usage)

        proposed = 0
        outside_diff = 0
        without_evidence = 0
        duplicates = 0

        async with self._unit_of_work:
            run = await self._unit_of_work.review_runs.get(run_id)
            run.record_usage(total_usage)

            for file, drafts in drafts_by_file:
                for draft in drafts:
                    proposed += 1
                    if not file.covers_line(draft.line_start):
                        outside_diff += 1
                        continue

                    finding = _build_finding(draft, file)
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
            )


def _accumulate(total: LlmUsage, addition: LlmUsage) -> LlmUsage:
    return LlmUsage(
        input_tokens=total.input_tokens + addition.input_tokens,
        output_tokens=total.output_tokens + addition.output_tokens,
        cost_usd=total.cost_usd + addition.cost_usd,
    )


def _build_finding(draft: FindingDraft, file: ReviewFile) -> Finding | None:
    """Превращает черновик в находку, отбраковывая недостоверные.

    Находка без подтверждённой цитаты не создаётся: это типичный признак
    выдуманного контекста. Принадлежность строки диффу проверяется раньше,
    на уровне вызывающего кода, чтобы различать причины отбраковки.
    """
    patch_text = file.to_unified_patch()
    evidence = _collect_evidence(draft, patch_text)
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


def _collect_evidence(draft: FindingDraft, patch_text: str) -> list[Evidence]:
    candidates = [item.snippet for item in draft.evidence]
    if draft.code_fragment:
        candidates.append(draft.code_fragment)

    confirmed: list[Evidence] = []
    seen: set[str] = set()
    for snippet in candidates:
        normalized = _normalize(snippet)
        if not normalized or normalized in seen:
            continue
        if normalized not in _normalize(patch_text):
            continue

        seen.add(normalized)
        confirmed.append(
            Evidence(
                kind=EvidenceKind.QUOTED_CODE,
                file_path=draft.file_path,
                snippet=snippet.strip(),
                line_start=draft.line_start,
                line_end=draft.line_end,
            )
        )
    return confirmed


def _normalize(text: str) -> str:
    return " ".join(text.split()).strip(WHITESPACE)
